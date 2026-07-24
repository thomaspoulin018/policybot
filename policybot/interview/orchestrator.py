from __future__ import annotations

from datetime import date
import inspect
from pathlib import Path
from typing import Callable, Optional
import uuid

from policybot.classify.data_classifier import classify_data
from policybot.classify.tool_registry import lookup_tool
from policybot.classify.tool_type import classify_tool_type
from policybot.config import ArpCacheMode
from policybot.contract.arp import CURRENT_ARP_SCHEMA_VERSION, build_arp
from policybot.contract.criteres import CRITERIA_SEARCHES
from policybot.contract.offering import build_offering_identity
from policybot.llm.provider import LLMProvider
from policybot.models import (
    ContractOfferingIdentity,
    CriterionFinding,
    IagType,
    InterviewState,
    QualificationProfile,
    RequestInfo,
    ToolRef,
    Usage,
)
from policybot.preapproved.store import PreApprovedStore
from policybot.tracing import collect_llm_usage, mask_text, trace_step


class UnknownToolError(ValueError):
    def __init__(self, tool_name: str):
        super().__init__(f"Type IAG inconnu pour l'outil « {tool_name} ».")
        self.tool_name = tool_name


def _empty_findings(outcome: str = "no_answer") -> list[CriterionFinding]:
    return [
        CriterionFinding(
            id=item.id,
            partie=item.partie,
            category=item.category,
            criterion=item.criterion,
            question=item.question,
            exa_type=item.exa.type,
            outcome=outcome,
        )
        for item in CRITERIA_SEARCHES
    ]


class Interview:
    def __init__(
        self,
        llm: LLMProvider,
        store: PreApprovedStore,
        exa_search: Optional[Callable] = None,
        arp_cache_mode: ArpCacheMode = "read_write",
        debug_runs_enabled: bool = False,
        debug_runs_output_dir: str | Path = "logs/runs",
    ):
        self._llm = llm
        self._store = store
        self._exa_search = exa_search
        self._arp_cache_mode = arp_cache_mode
        self._debug_runs_enabled = debug_runs_enabled
        self._debug_runs_output_dir = debug_runs_output_dir

    @property
    def llm(self) -> LLMProvider:
        return self._llm

    def _resolve_arp(
        self,
        tool_name: str,
        iag_type: IagType,
        offering: ContractOfferingIdentity,
    ):
        with trace_step(None, "resolve_arp", tool_name=tool_name) as extra:
            cached = None
            if self._arp_cache_mode in ("read_write", "read_only"):
                cached = self._store.get_arp(offering)
            if cached and cached.schema_version >= CURRENT_ARP_SCHEMA_VERSION:
                extra["cache"] = "hit"
                return cached
            extra["cache"] = "stale" if cached else "miss"

            if self._arp_cache_mode == "read_only":
                findings = _empty_findings()
            elif self._exa_search is not None:
                parameters = inspect.signature(self._exa_search).parameters
                if "offering" in parameters:
                    result = self._exa_search(tool_name, offering=offering)
                else:
                    result = self._exa_search(tool_name)
                findings = result if isinstance(result, list) else _empty_findings()
            else:
                from policybot.contract.exa import search_criteria_with_exa
                findings = search_criteria_with_exa(tool_name, offering) or _empty_findings()

            arp = build_arp(tool_name, iag_type, findings, offering)
            extra.update(
                finding_count=len(findings),
                total_cost_dollars=arp.total_cost_dollars,
            )
            if self._arp_cache_mode in ("read_write", "refresh"):
                self._store.save_arp(arp)
            return arp

    def assess(
        self,
        request: RequestInfo,
        tool_name: str,
        usage_inputs: list[dict],
        iag_type_override: IagType | None = None,
        qualification: QualificationProfile | None = None,
        tool_version_plan_tarifaire: str | None = None,
        deployment_mode: str | None = None,
        contract_type: str | None = None,
        contract_version: str | None = None,
        jurisdiction: str | None = None,
        contract_effective_date: date | None = None,
        offering_override: ContractOfferingIdentity | None = None,
    ) -> InterviewState:
        state = InterviewState(interview_id=str(uuid.uuid4()), request=request)
        if qualification is not None:
            state.qualification = qualification
        with collect_llm_usage(state.interview_id) as llm_usage:
            with trace_step(state.interview_id, "assess", tool_name=tool_name):
                entry = lookup_tool(tool_name)
                iag_type = classify_tool_type(tool_name) or iag_type_override
                if iag_type is None:
                    raise UnknownToolError(tool_name)
                offering = offering_override or build_offering_identity(
                    tool_name,
                    iag_type,
                    vendor=entry["vendor"] if entry else None,
                    plan=tool_version_plan_tarifaire,
                    deployment_mode=deployment_mode,
                    contract_type=contract_type,
                    contract_version=contract_version,
                    jurisdiction=jurisdiction,
                    effective_date=contract_effective_date,
                )
                tool = ToolRef(
                    name=tool_name,
                    vendor=entry["vendor"] if entry else None,
                    iag_type=iag_type,
                    version_plan_tarifaire=tool_version_plan_tarifaire or "",
                    offering=offering,
                )
                state.tools.append(tool)

                for index, item in enumerate(usage_inputs):
                    description = item.get("data_description", "")
                    with trace_step(
                        None, "classify_data", usage_index=index, **mask_text(description)
                    ) as extra:
                        classification = classify_data(description, self._llm)
                        extra.update(
                            data_classification=classification.data_classification,
                            rens_personnels=classification.rens_personnels,
                            confidence=classification.confidence,
                        )
                    state.usages.append(Usage(
                        description=item.get("description", ""),
                        tool_ref=tool_name,
                        raw_answers={"data_description": description},
                        data_classification=classification.data_classification,
                        rens_personnels=classification.rens_personnels,
                        efvpr_required=classification.rens_personnels,
                        classifier_confidence=classification.confidence,
                        needs_officer_confirmation=classification.needs_officer_confirmation,
                        mode=item.get("mode", []),
                        frequence_utilisation=item.get("frequence_utilisation", ""),
                        nb_utilisateurs=item.get("nb_utilisateurs"),
                        systemes_api_cibles=item.get("systemes_api_cibles", ""),
                        result_use=item.get("result_use", []),
                        automated_decisions=item.get("automated_decisions", False),
                    ))

                tool.arp = self._resolve_arp(tool_name, iag_type, offering)
                state.status = "complete"
        state.audit["llm_usage"] = llm_usage.as_dict()
        state.audit["search_cost_dollars"] = (
            state.tools[0].arp.total_cost_dollars if state.tools[0].arp else 0.0
        )
        return state
