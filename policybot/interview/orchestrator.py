from __future__ import annotations
from typing import Callable, Optional
from policybot.models import (
    InterviewState, RequestInfo, ToolRef, Usage, ContractFacts, IagType,
    QualificationProfile,
)
from policybot.llm.provider import LLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.classify.data_classifier import classify_data
from policybot.classify.tool_type import classify_tool_type
from policybot.classify.tool_registry import lookup_tool
from policybot.contract.fetcher import fetch_terms
from policybot.contract.arp import extract_contract_facts, build_arp
from policybot.grille.engine import evaluate_usage, synthesize
from policybot.tracing import trace_step, mask_text
import uuid


class UnknownToolError(ValueError):
    """Raised when a tool isn't in the registry and no IAG type override was
    supplied. Callers must disambiguate via
    policybot.classify.tool_type.tool_type_question() and retry with
    iag_type_override set."""

    def __init__(self, tool_name: str):
        super().__init__(
            f"Unknown tool '{tool_name}': cannot determine its IAG type. "
            "Ask the disambiguation question from "
            "policybot.classify.tool_type.tool_type_question() and retry "
            "assess() with iag_type_override set to the user's answer."
        )
        self.tool_name = tool_name


class Interview:
    def __init__(self, llm: LLMProvider, store: PreApprovedStore,
                 http_get: Optional[Callable[[str], str]] = None):
        self._llm = llm
        self._store = store
        self._http_get = http_get

    @property
    def llm(self) -> LLMProvider:
        return self._llm

    def _resolve_arp(self, tool_name: str, iag_type) -> ContractFacts:
        with trace_step(None, "resolve_arp", tool_name=tool_name) as extra:
            cached = self._store.get_arp(tool_name)
            if cached:
                extra["cache"] = "hit"
                return cached.contract_facts
            extra["cache"] = "miss"
            with trace_step(None, "resolve_arp_fetch", tool_name=tool_name) as fetch_extra:
                terms = fetch_terms(tool_name, http_get=self._http_get)
                fetch_extra["found"] = terms is not None
                if terms is None:
                    return ContractFacts()  # manual-paste fallback handled by the UI layer
                facts = extract_contract_facts(terms, self._llm)
            self._store.save_arp(build_arp(tool_name, iag_type, facts))
            return facts

    def assess(self, request: RequestInfo, tool_name: str,
               usage_inputs: list[dict],
               iag_type_override: IagType | None = None,
               qualification: QualificationProfile | None = None,
               tool_version_plan_tarifaire: str | None = None) -> InterviewState:
        state = InterviewState(interview_id=str(uuid.uuid4()), request=request)
        if qualification is not None:
            state.qualification = qualification
        with trace_step(state.interview_id, "assess", tool_name=tool_name):
            entry = lookup_tool(tool_name)
            iag_type = classify_tool_type(tool_name)
            if iag_type is None:
                if iag_type_override is None:
                    raise UnknownToolError(tool_name)
                iag_type = iag_type_override
            state.tools.append(ToolRef(
                name=tool_name,
                vendor=entry["vendor"] if entry else None,
                iag_type=iag_type,
                version_plan_tarifaire=tool_version_plan_tarifaire or "",
            ))

            # Classify each usage's data description first, then resolve (and cache)
            # the tool's contract facts once — this fixes the LLM call order to
            # (1) data classifier signals per usage, (2) ARP contract facts.
            classifications = []
            for i, item in enumerate(usage_inputs):
                description = item["data_description"]
                with trace_step(None, "classify_data", usage_index=i,
                                 **mask_text(description)) as extra:
                    classification = classify_data(description, self._llm)
                    extra.update(
                        data_classification=classification.data_classification,
                        rens_personnels=classification.rens_personnels,
                        confidence=classification.confidence,
                        needs_officer_confirmation=classification.needs_officer_confirmation,
                    )
                classifications.append((item, classification))

            facts = self._resolve_arp(tool_name, iag_type)

            for i, (item, classification) in enumerate(classifications):
                usage = Usage(
                    description=item.get("description", ""),
                    tool_ref=tool_name,
                    data_classification=classification.data_classification,
                    rens_personnels=classification.rens_personnels,
                    classifier_confidence=classification.confidence,
                    needs_officer_confirmation=classification.needs_officer_confirmation,
                    mode=item.get("mode", []),
                    frequence_utilisation=item.get("frequence_utilisation", ""),
                    nb_utilisateurs=item.get("nb_utilisateurs"),
                    systemes_api_cibles=item.get("systemes_api_cibles", ""),
                    result_use=item.get("result_use", []),
                    automated_decisions=item.get("automated_decisions", False),
                )
                with trace_step(None, "evaluate_usage", usage_index=i) as extra:
                    evaluated = evaluate_usage(usage, facts, iag_type)
                    extra.update(
                        matrix_result=evaluated.matrix_result,
                        risk_level=evaluated.risk_level,
                        verdict=evaluated.verdict,
                    )
                state.usages.append(evaluated)

            with trace_step(None, "synthesize") as extra:
                state.result_global = synthesize(state.usages)
                extra.update(
                    risk_level=state.result_global.risk_level,
                    recommendation=state.result_global.recommendation,
                    efvpr_required=state.result_global.efvpr_required,
                )
            state.status = "complete"
        return state
