"""Recherche Exa structurée, une requête indépendante par critère."""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Iterable, Mapping, Protocol

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.citations import validated_citation
from policybot.contract.criteres import (
    CRITERIA_SEARCHES,
    SEARCH_DEFAULTS,
    CriterionSearchConfig,
    SearchDefaults,
)
from policybot.contract.source_policy import source_sort_key
from policybot.models import ContractOfferingIdentity, CriterionFinding
from policybot.tracing import (
    record_exa_search_failed,
    record_exa_search_started,
    record_exa_search_succeeded,
    trace_step,
)


DEFAULT_MAX_WORKERS = 8


class ExaClient(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any: ...


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else {}
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _field(value: Any, *names: str, default: Any = None) -> Any:
    mapping = _mapping(value)
    for name in names:
        if name in mapping:
            return mapping[name]
        if hasattr(value, name):
            return getattr(value, name)
    return default


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    if isinstance(value, list):
        for item in value:
            parsed = _json_object(item)
            if parsed and any(
                key in parsed
                for key in ("answer", "inherent_risk", "justification", "citation")
            ):
                return parsed
        return {}
    mapping = _mapping(value)
    if not any(
        key in mapping for key in ("answer", "inherent_risk", "citation")
    ):
        for container in ("content", "text"):
            if container in mapping:
                nested = _json_object(mapping[container])
                if nested:
                    return nested
    return dict(mapping)


def _response_output(response: Any) -> dict[str, Any]:
    return _json_object(_field(response, "output", default={}))


def _response_cost(response: Any) -> float:
    raw = _field(response, "costDollars", "cost_dollars", default={})
    if isinstance(raw, (int, float)):
        return max(0.0, float(raw))
    mapping = _mapping(raw)
    for key in ("total", "totalCost", "total_cost"):
        try:
            return max(0.0, float(mapping[key]))
        except (KeyError, TypeError, ValueError):
            pass
    return 0.0


def _page_text(result: Any) -> str:
    value = _field(result, "text", "content", default="")
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return str(_field(value, "text", "content", default="") or "")


def _page_summary(result: Any) -> dict[str, Any]:
    return _json_object(_field(result, "summary", default={}))


def _identity_values(
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
) -> dict[str, str]:
    values = {
        "tool": tool_name,
        "vendor": vendor,
        "plan": offering.plan,
        "deployment_mode": offering.deployment_mode,
        "contract_type": offering.contract_type,
        "contract_version": offering.contract_version,
        "jurisdiction": offering.jurisdiction,
    }
    return {
        key: "" if not value or value.casefold() == "unknown" else value
        for key, value in values.items()
    }


def _collect_one(
    client: ExaClient,
    definition: CriterionSearchConfig,
    defaults: SearchDefaults,
    tool_name: str,
    offering: ContractOfferingIdentity,
    *,
    exa_type: str | None = None,
) -> CriterionFinding:
    vendor = offering.vendor or (lookup_tool(tool_name) or {}).get("vendor") or tool_name
    search_query = definition.render_query(
        **_identity_values(tool_name, vendor, offering)
    )
    query = "\n\n".join((
        search_query,
        defaults.prompts["global_instruction"].format(
            question=definition.question
        ).strip(),
    ))
    search_type = exa_type or definition.exa.type
    contents = dict(definition.exa.contents)
    contents["summary"] = {
        "query": defaults.prompts["per_page_instruction"].format(
            question=definition.question
        ),
        "schema": defaults.schemas["per_page"],
    }
    kwargs = {
        "num_results": definition.exa.num_results,
        "type": search_type,
        "output_schema": defaults.schemas["global"],
        "contents": contents,
    }
    if definition.exa.include_domains:
        kwargs["include_domains"] = definition.exa.include_domains

    record_exa_search_started()
    with trace_step(
        None, "exa_criterion_search", criterion_id=definition.id, exa_type=search_type
    ) as extra:
        try:
            response = client.search(query, **kwargs)
        except Exception:
            record_exa_search_failed()
            extra["outcome"] = "search_failed"
            raise

        output = _response_output(response)
        answer = str(output.get("answer") or "").strip()
        risk = str(output.get("inherent_risk") or "").strip().upper()
        if risk not in {"F", "M", "E"}:
            risk = None
        justification = str(output.get("justification") or "").strip()
        cost = _response_cost(response)

        accepted = []
        rejected = 0
        results = list(_field(response, "results", default=[]) or [])
        for result in sorted(
            results, key=lambda item: source_sort_key(dict(_mapping(item)), None)
        ):
            summary = _page_summary(result)
            quote_text = str(summary.get("citation") or "").strip()
            if not quote_text:
                continue
            citation = validated_citation(
                url=str(_field(result, "url", default="") or ""),
                title=str(_field(result, "title", default="") or ""),
                page_text=_page_text(result),
                quote_text=quote_text,
                begin=summary.get("begin"),
                end=summary.get("end"),
            )
            if citation is None:
                rejected += 1
                continue
            if citation.url not in {item.url for item in accepted}:
                accepted.append(citation)
            if len(accepted) >= defaults.max_citations_per_criterion:
                break

        outcome = "ok" if answer else "no_answer"
        record_exa_search_succeeded(cost, reported=cost > 0)
        extra.update(
            result_count=len(results),
            cost_dollars=cost,
            citations_retained=len(accepted),
            citations_rejected=rejected,
            outcome=outcome,
        )
        return CriterionFinding(
            id=definition.id,
            partie=definition.partie,
            category=definition.category,
            criterion=definition.criterion,
            question=definition.question,
            answer=answer,
            inherent_risk=risk,
            justification=justification,
            citations=accepted,
            rejected_citations=rejected,
            exa_type=search_type,
            cost_dollars=cost,
            outcome=outcome,
        )


def collect_criteria_from_exa(
    tool_name: str,
    offering: ContractOfferingIdentity,
    client: ExaClient,
    *,
    definitions: Iterable[CriterionSearchConfig] = CRITERIA_SEARCHES,
    defaults: SearchDefaults = SEARCH_DEFAULTS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[CriterionFinding]:
    definitions = tuple(definitions)
    budget = float(defaults.budget.get("max_cost_dollars_per_interview", 0) or 0)
    policy = str(defaults.budget.get("on_exceeded") or "continue")
    spent = 0.0
    lock = threading.Lock()

    def run(definition: CriterionSearchConfig) -> CriterionFinding:
        nonlocal spent
        with lock:
            force_neural = budget > 0 and spent >= budget and policy == "degrade_to_neural"
            stop = budget > 0 and spent >= budget and policy == "stop"
        if stop:
            return CriterionFinding(
                id=definition.id, partie=definition.partie,
                category=definition.category, criterion=definition.criterion,
                question=definition.question, outcome="search_failed",
                exa_type=definition.exa.type,
            )
        try:
            finding = _collect_one(
                client, definition, defaults, tool_name, offering,
                exa_type="neural" if force_neural else None,
            )
        except Exception:
            return CriterionFinding(
                id=definition.id, partie=definition.partie,
                category=definition.category, criterion=definition.criterion,
                question=definition.question, outcome="search_failed",
                exa_type="neural" if force_neural else definition.exa.type,
            )
        with lock:
            spent += finding.cost_dollars
        return finding

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as executor:
        futures = {executor.submit(run, item): item.id for item in definitions}
        findings = [future.result() for future in as_completed(futures)]
    order = {definition.id: index for index, definition in enumerate(definitions)}
    return sorted(findings, key=lambda finding: order[finding.id])


def search_criteria_with_exa(
    tool_name: str,
    offering: ContractOfferingIdentity,
    *,
    client: ExaClient | None = None,
    definitions: Iterable[CriterionSearchConfig] = CRITERIA_SEARCHES,
    defaults: SearchDefaults = SEARCH_DEFAULTS,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[CriterionFinding] | None:
    if client is None:
        key = os.environ.get("EXA_API_KEY")
        if not key:
            return None
        from exa_py import Exa
        client = Exa(key)
    return collect_criteria_from_exa(
        tool_name, offering, client, definitions=definitions,
        defaults=defaults, max_workers=max_workers,
    )
