from __future__ import annotations

from datetime import date
from typing import Callable, Optional
import uuid

from policybot.classify.data_classifier import classify_data
from policybot.classify.tool_registry import classify_tool_type, lookup_tool
from policybot.contract.criteres import CRITERIA_SEARCHES
from policybot.contract.offering import build_offering_identity
from policybot.llm import LLMProvider
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
    """Une demande à la fois : classification des données puis recherches configurées.

    `exa_search(tool_name, offering)` n'existe que pour substituer la recherche
    en test. Sa signature est fixe : la version précédente inspectait la
    signature de l'objet reçu pour deviner s'il acceptait `offering`.
    """

    def __init__(
        self,
        llm: LLMProvider,
        exa_search: Optional[Callable[..., list[CriterionFinding]]] = None,
    ):
        self._llm = llm
        self._exa_search = exa_search

    @property
    def llm(self) -> LLMProvider:
        return self._llm

    def _rechercher_constats(
        self,
        tool_name: str,
        offering: ContractOfferingIdentity,
    ) -> list[CriterionFinding]:
        with trace_step(None, "recherche_criteres", tool_name=tool_name) as extra:
            search = self._exa_search
            if search is None:
                from policybot.contract.exa import search_criteria_with_exa
                search = search_criteria_with_exa
            findings = list(search(tool_name, offering) or []) or _empty_findings()
            extra.update(
                finding_count=len(findings),
                total_cost_dollars=round(
                    sum(item.cost_dollars for item in findings), 8
                ),
            )
            return findings

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

                tool.findings = self._rechercher_constats(tool_name, offering)
                state.status = "complete"
        state.audit["llm_usage"] = llm_usage.as_dict()
        state.audit["search_cost_dollars"] = state.tools[0].total_cost_dollars
        return state
