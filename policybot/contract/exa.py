"""Exa-backed, deterministic collection of one contract fact per search."""
from __future__ import annotations

import contextvars
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Protocol

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.arp import _quote_is_anchored
from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.contract.fact_search import FACT_SEARCHES, FactSearchConfig
from policybot.contract.source_policy import (
    build_source_policy,
    contract_source_urls,
    classify_source,
    source_effective_date,
    source_is_allowed,
    source_sort_key,
)
from policybot.models import ContractOfferingIdentity, FactEvidence
from policybot.tracing import (
    mask_text,
    record_exa_search_failed,
    record_exa_search_started,
    record_exa_search_succeeded,
    trace_step,
)


DEFAULT_MAX_WORKERS = 8

# Exa does not return billing metadata with Search responses.  These public
# rates are therefore an estimate based on the request parameters, not an
# invoice value.  See https://exa.ai/pricing (verified 2026-07-21).
_EXA_SEARCH_BASE_COST_USD = {
    "auto": 0.007,
}
_EXA_AI_SUMMARY_COST_PER_RESULT_USD = 0.001


class ExaClient(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any:
        """Run one Exa search."""


@dataclass(frozen=True)
class _FactSearchResult:
    fact: str
    proof: FactEvidence
    documents: list[EvidenceDocument]
    failed: bool = False


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    if hasattr(value, "__dict__"):
        return vars(value)
    return None


def _field(value: Any, name: str, default: Any = None) -> Any:
    mapping = _as_mapping(value)
    if mapping is not None:
        return mapping.get(name, default)
    return getattr(value, name, default)


def _results(response: Any) -> list[Any]:
    raw = _field(response, "results", ())
    return list(raw) if isinstance(raw, (list, tuple)) else []


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(part for item in value if (part := _text(item)))
    if isinstance(value, Mapping):
        return _text(value.get("text") or value.get("content") or "")
    return ""


def _summary(result: Any) -> Mapping[str, Any] | None:
    raw = _field(result, "summary")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return _as_mapping(raw)


def _document_from_result(result: Any) -> tuple[EvidenceDocument, Mapping[str, Any]] | None:
    raw = _as_mapping(result)
    if raw is None:
        return None
    url = str(raw.get("url") or "").strip()
    if not url:
        return None
    page_text = _text(raw.get("text") or raw.get("content"))
    highlights = _text(raw.get("highlights"))
    content = "\n\n".join(part for part in (page_text, highlights) if part).strip()
    if not content:
        return None
    return EvidenceDocument(
        url=url,
        content=content,
        title=str(raw.get("title") or ""),
        source_type=classify_source(url),
        collection_method="exa_search",
        effective_date=source_effective_date(dict(raw)),
        collected_at=date.today(),
    ), raw


def _offering_scope(offering: ContractOfferingIdentity) -> str:
    return " ".join(part for part in (
        offering.plan, offering.deployment_mode, offering.contract_type,
        offering.contract_version,
    ) if part).strip()


def _search_kwargs(
    definition: FactSearchConfig,
    *,
    query: str,
    include_domains: Iterable[str],
) -> dict[str, Any]:
    contents = definition.exa.contents
    return {
        "type": definition.exa.type,
        "num_results": definition.exa.num_results,
        "include_domains": list(dict.fromkeys(domain for domain in include_domains if domain)),
        "contents": {
            "text": {"max_characters": contents.text.max_characters},
            "highlights": {
                "query": contents.highlights.query,
                "num_sentences": contents.highlights.num_sentences,
            },
            "summary": {
                "query": contents.summary.query,
                "schema": contents.summary.schema_,
            },
        },
    }


def estimate_search_cost_usd(definition: FactSearchConfig) -> float | None:
    """Return the public-rate estimate for one configured Exa search.

    The current contract-fact configuration always requests an AI summary for
    every result.  Exa's API-key response does not expose charged usage, so an
    unsupported search type deliberately produces ``None`` instead of a guess.
    """
    base_cost = _EXA_SEARCH_BASE_COST_USD.get(definition.exa.type)
    if base_cost is None:
        return None
    return base_cost + (
        definition.exa.num_results * _EXA_AI_SUMMARY_COST_PER_RESULT_USD
    )


def _unknown(note: str, outcome: str, *, source_url: str | None = None,
             quote: str | None = None, declared_source_url: str | None = None) -> FactEvidence:
    return FactEvidence(
        value="unknown", source_url=source_url, quote=quote,
        declared_source_url=declared_source_url,
        note=note, outcome=outcome,
    )


def _collect_one(
    definition: FactSearchConfig,
    *,
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
    client: ExaClient,
    source_urls: list[str],
) -> _FactSearchResult:
    rendered = definition.render(tool=tool_name, vendor=vendor)
    scope = _offering_scope(offering)
    query = " ".join(part for part in (rendered.query, scope) if part)
    policy = build_source_policy(
        offering, priority_urls=source_urls, source_urls=source_urls,
    )
    known_domains = [url.split("/", 3)[2] for url in source_urls if "://" in url]
    include_domains = (*rendered.include_domains, *known_domains)
    kwargs = _search_kwargs(definition, query=query, include_domains=include_domains)

    with trace_step(None, "exa_fact_search", fact=definition.fact) as extra:
        extra.update({
            "query": mask_text(query),
            "option_a": definition.selection.strategy,
            "option_d_require_declared_source_url": (
                definition.selection.require_declared_source_url
            ),
        })
        try:
            record_exa_search_started()
            response = client.search(query, **kwargs)
        except Exception as exc:  # noqa: BLE001 - a fact must never abort an interview
            record_exa_search_failed()
            extra.update(outcome="collection_failure", error=type(exc).__name__)
            return _FactSearchResult(
                definition.fact,
                _unknown("collecte Exa échouée", "collection_failure"),
                [],
                failed=True,
            )
        record_exa_search_succeeded(estimate_search_cost_usd(definition))

        documents: list[EvidenceDocument] = []
        accepted: list[tuple[FactEvidence, Mapping[str, Any]]] = []
        rejections: list[str] = []
        result_count = 0
        for result in _results(response):
            document_result = _document_from_result(result)
            if document_result is None:
                continue
            document, raw_result = document_result
            result_count += 1
            if not source_is_allowed(dict(raw_result), policy):
                rejections.append("source_rejected")
                continue
            documents.append(document)
            summary = _summary(result)
            if summary is None:
                rejections.append("summary_missing")
                continue
            value = str(summary.get("value") or "unknown")
            quote = str(summary.get("quote") or "").strip() or None
            declared_url = str(summary.get("source_url") or "").strip() or None
            if (
                definition.selection.require_declared_source_url
                and declared_url != document.url
            ):
                rejections.append("declared_source_url_rejected")
                continue
            if value not in definition.allowed_values:
                rejections.append("invalid_value")
                continue
            if value == "unknown":
                rejections.append("model_abstention")
                continue
            if not quote or not _quote_is_anchored(quote, document.content):
                rejections.append("citation_rejected")
                continue
            accepted.append((
                FactEvidence(
                    value=value,
                    source_url=document.url,
                    quote=quote,
                    declared_source_url=declared_url,
                    confidence=1.0,
                    outcome="accepted",
                    source_type=document.source_type,
                    source_effective_date=document.effective_date,
                    source_collected_at=document.collected_at,
                    source_sha256=document.sha256,
                ),
                raw_result,
            ))

        if accepted:
            # Option A: contractual > DPA > official technical > commercial >
            # secondary, then Exa relevance score.  Sorting is stable, so the
            # search response order breaks an exact tie deterministically.
            proof, selected = min(
                accepted, key=lambda item: source_sort_key(dict(item[1]), policy),
            )
            extra.update(
                outcome="accepted",
                result_count=result_count,
                accepted_candidates=len(accepted),
                selected_source_type=proof.source_type,
                selected_source_url=mask_text(proof.source_url or ""),
            )
            return _FactSearchResult(definition.fact, proof, documents)

        if not result_count:
            proof = _unknown("aucune évidence Exa collectée", "evidence_missing")
        elif rejections and set(rejections) == {"declared_source_url_rejected"}:
            proof = _unknown(
                "URL déclarée par Exa différente de la source du résultat",
                "declared_source_url_rejected",
            )
        elif "citation_rejected" in rejections:
            proof = _unknown(
                "citation introuvable dans la source Exa correspondante",
                "citation_rejected",
            )
        elif "invalid_value" in rejections:
            proof = _unknown(
                "valeur Exa hors des valeurs permises", "invalid_value",
            )
        elif "model_abstention" in rejections:
            proof = FactEvidence(value="unknown", outcome="model_abstention")
        else:
            proof = _unknown("aucune source Exa applicable", "evidence_missing")
        extra.update(
            outcome=proof.outcome,
            result_count=result_count,
            accepted_candidates=0,
            rejected_candidates=len(rejections),
        )
        return _FactSearchResult(definition.fact, proof, documents)


def collect_evidence_from_exa(
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
    client: ExaClient,
    *,
    definitions: Iterable[FactSearchConfig] = FACT_SEARCHES,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> ContractEvidence:
    """Collect every configured fact concurrently and degrade independently."""
    configs = tuple(definitions)
    source_urls = contract_source_urls(tool_name, offering)
    workers = max(1, min(max_workers, len(configs)))
    results: dict[str, _FactSearchResult] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="policybot-exa") as pool:
        futures = {
            pool.submit(
                contextvars.copy_context().run,
                _collect_one,
                definition,
                tool_name=tool_name,
                vendor=vendor,
                offering=offering,
                client=client,
                source_urls=source_urls,
            ): definition.fact
            for definition in configs
        }
        for future in as_completed(futures):
            fact = futures[future]
            try:
                results[fact] = future.result()
            except Exception as exc:  # defensive boundary around worker setup
                with trace_step(None, "exa_fact_search", fact=fact) as extra:
                    extra.update(outcome="collection_failure", error=type(exc).__name__)
                results[fact] = _FactSearchResult(
                    fact, _unknown("collecte Exa échouée", "collection_failure"), [], True,
                )

    return ContractEvidence(
        documents_by_fact={
            fact: result.documents for fact, result in results.items() if result.documents
        },
        facts={fact: result.proof for fact, result in results.items()},
        failed_facts=tuple(
            fact for fact, result in results.items() if result.failed
        ),
    )


def _configured_workers() -> int:
    raw = os.environ.get("POLICYBOT_EXA_MAX_WORKERS", "")
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_WORKERS
    except ValueError:
        return DEFAULT_MAX_WORKERS


def search_contract_facts_with_exa(
    tool_name: str,
    *,
    offering: ContractOfferingIdentity,
    api_key: str | None = None,
    client: ExaClient | None = None,
    definitions: Iterable[FactSearchConfig] = FACT_SEARCHES,
    max_workers: int | None = None,
) -> ContractEvidence | None:
    """Create the real client lazily; a missing key is a clean unknown fallback."""
    active_client = client
    if active_client is None:
        key = api_key or os.environ.get("EXA_API_KEY")
        if not key:
            return None
        try:
            from exa_py import Exa  # imported only for real, opted-in calls
            active_client = Exa(api_key=key)
        except Exception as exc:  # noqa: BLE001 - dependency/auth setup must not abort assessment
            with trace_step(None, "exa_client_init") as extra:
                extra.update(outcome="failed", error=type(exc).__name__)
            return None
    entry = lookup_tool(tool_name) or {}
    return collect_evidence_from_exa(
        tool_name,
        str(entry.get("vendor") or offering.vendor or tool_name),
        offering,
        active_client,
        definitions=definitions,
        max_workers=max_workers or _configured_workers(),
    )
