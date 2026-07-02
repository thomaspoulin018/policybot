from __future__ import annotations
from typing import Callable, Optional
from policybot.models import (
    InterviewState, RequestInfo, ToolRef, Usage, ContractFacts, IagType,
)
from policybot.llm.provider import LLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.classify.data_classifier import classify_data
from policybot.classify.tool_type import classify_tool_type
from policybot.classify.tool_registry import lookup_tool
from policybot.contract.fetcher import fetch_terms
from policybot.contract.arp import extract_contract_facts, build_arp
from policybot.grille.engine import evaluate_usage, synthesize
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

    def _resolve_arp(self, tool_name: str, iag_type) -> ContractFacts:
        cached = self._store.get_arp(tool_name)
        if cached:
            return cached.contract_facts
        terms = fetch_terms(tool_name, http_get=self._http_get)
        if terms is None:
            return ContractFacts()  # manual-paste fallback handled by the UI layer
        facts = extract_contract_facts(terms, self._llm)
        self._store.save_arp(build_arp(tool_name, iag_type, facts))
        return facts

    def assess(self, request: RequestInfo, tool_name: str,
               usage_inputs: list[dict],
               iag_type_override: IagType | None = None) -> InterviewState:
        state = InterviewState(interview_id=str(uuid.uuid4()), request=request)
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
        ))

        # Classify each usage's data description first, then resolve (and cache)
        # the tool's contract facts once — this fixes the LLM call order to
        # (1) data classifier signals per usage, (2) ARP contract facts.
        classifications = [
            (item, classify_data(item["data_description"], self._llm))
            for item in usage_inputs
        ]
        facts = self._resolve_arp(tool_name, iag_type)

        for item, classification in classifications:
            usage = Usage(
                description=item.get("description", ""),
                tool_ref=tool_name,
                data_classification=classification.data_classification,
                rens_personnels=classification.rens_personnels,
                classifier_confidence=classification.confidence,
                needs_officer_confirmation=classification.needs_officer_confirmation,
                mode=item.get("mode", []),
                result_use=item.get("result_use", []),
                automated_decisions=item.get("automated_decisions", False),
            )
            state.usages.append(evaluate_usage(usage, facts, iag_type))

        state.result_global = synthesize(state.usages)
        state.status = "complete"
        return state
