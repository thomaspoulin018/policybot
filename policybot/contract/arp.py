from __future__ import annotations
from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), encryption_standard (strong|partial|none|"
    "unknown) [strong = chiffrement en transit ET au repos explicitement mentionné, "
    "partial = un seul des deux ou non précisé, none = absence explicite de "
    "chiffrement], ip_ownership (customer|vendor|unclear|unknown) [qui détient les "
    "droits sur le contenu généré], extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(_SYSTEM, terms.text[:12000])
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
        encryption_standard=raw.get("encryption_standard", "unknown"),
        ip_ownership=raw.get("ip_ownership", "unknown"),
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

    sub_processors_risk = "E" if facts.sub_processors in ("undisclosed", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Garanties contractuelles de non-divulgation",
        inherent=sub_processors_risk, residual=sub_processors_risk, origin="rule",
        observations=f"sub_processors={facts.sub_processors}",
    ))

    retention_risk = "E" if facts.data_retention in ("indefinite", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté", criterion="Conservation des données",
        inherent=retention_risk, residual=retention_risk, origin="rule",
        observations=f"data_retention={facts.data_retention}",
    ))

    human_review_risk = "E" if facts.human_review in ("no", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Révision humaine par le fournisseur",
        inherent=human_review_risk, residual=human_review_risk, origin="rule",
        observations=f"human_review={facts.human_review}",
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=f"encryption_standard={facts.encryption_standard}",
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle du contenu généré",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=f"ip_ownership={facts.ip_ownership}",
    ))

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
