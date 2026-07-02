from __future__ import annotations
from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(_SYSTEM, terms.text[:12000])
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
        source_url=terms.source_url,
        fetched_at=terms.fetched_at,
        extraction_confidence=float(raw.get("extraction_confidence", 0.0)),
    )


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    criteria: list[RiskFactor] = []

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Données soumises utilisées pour entraînement",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=f"trains_on_input={facts.trains_on_input}",
    ))

    residency_risk = "F" if facts.data_residency == "canada" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=f"data_residency={facts.data_residency}",
    ))

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
