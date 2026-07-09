from __future__ import annotations
from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider
from policybot.criteria import ARP_CRITERIA

_SYSTEM = (
    "Tu extrais des faits normalisés des conditions d'utilisation d'un outil d'IA. "
    "Réponds uniquement en JSON avec: trains_on_input (yes|no|opt_out_available|"
    "unknown), data_retention (none|limited|indefinite|unknown), data_residency "
    "(canada|us|eu|other|unknown), sub_processors (disclosed|undisclosed|unknown), "
    "human_review (yes|no|unknown), encryption_standard (strong|partial|none|"
    "unknown) [strong = chiffrement en transit ET au repos explicitement mentionné, "
    "partial = un seul des deux ou non précisé, none = absence explicite de "
    "chiffrement], ip_ownership (customer|vendor|unclear|unknown) [qui détient les "
    "droits sur le contenu généré], applicable_law (quebec_canada|foreign|unknown) "
    "[le droit applicable au contrat est-il celui du Québec/Canada ou un droit "
    "étranger ?], foreign_vendor_dependency (yes|no|unknown) [l'usage de l'outil "
    "crée-t-il une dépendance envers un fournisseur étranger ?], "
    "contract_prohibits_reuse (yes|no|unknown) [le contrat interdit-il "
    "explicitement au fournisseur de réutiliser les données soumises ?], "
    "reentraining_opt_out (yes|no|unknown) [existe-t-il un mécanisme permettant "
    "d'interdire le réentraînement du modèle à partir des données soumises et de "
    "celles qui sont produites ?], extraction_confidence (0-1)."
)


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    raw = llm.complete_json(
        _SYSTEM, terms.text[:12000],
        run_name="extract_contract_facts", tags=["arp_extraction"],
    )
    return ContractFacts(
        trains_on_input=raw.get("trains_on_input", "unknown"),
        data_retention=raw.get("data_retention", "unknown"),
        data_residency=raw.get("data_residency", "unknown"),
        sub_processors=raw.get("sub_processors", "unknown"),
        human_review=raw.get("human_review", "unknown"),
        encryption_standard=raw.get("encryption_standard", "unknown"),
        ip_ownership=raw.get("ip_ownership", "unknown"),
        applicable_law=raw.get("applicable_law", "unknown"),
        foreign_vendor_dependency=raw.get("foreign_vendor_dependency", "unknown"),
        contract_prohibits_reuse=raw.get("contract_prohibits_reuse", "unknown"),
        reentraining_opt_out=raw.get("reentraining_opt_out", "unknown"),
        source_url=terms.source_url,
        fetched_at=terms.fetched_at,
        extraction_confidence=float(raw.get("extraction_confidence", 0.0)),
    )


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    """Produce the 8 Partie A criteria PolicyBot can derive automatically."""
    criteria: list[RiskFactor] = []

    residency_risk = "F" if facts.data_residency == "canada" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=f"data_residency={facts.data_residency}",
    ))

    law_risk = "F" if facts.applicable_law == "quebec_canada" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Juridiction applicable",
        inherent=law_risk, residual=law_risk, origin="rule",
        observations=f"applicable_law={facts.applicable_law}",
    ))

    dependency_risk = "F" if facts.foreign_vendor_dependency == "no" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Dépendance technologique",
        inherent=dependency_risk, residual=dependency_risk, origin="rule",
        observations=f"foreign_vendor_dependency={facts.foreign_vendor_dependency}",
    ))

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=f"trains_on_input={facts.trains_on_input}",
    ))

    reuse_risk = "F" if facts.contract_prohibits_reuse == "yes" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Garanties contractuelles de non-divulgation",
        inherent=reuse_risk, residual=reuse_risk, origin="rule",
        observations=f"contract_prohibits_reuse={facts.contract_prohibits_reuse}",
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=f"encryption_standard={facts.encryption_standard}",
    ))

    opt_out_risk = "F" if facts.reentraining_opt_out == "yes" else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=opt_out_risk, origin="rule",
        observations=f"reentraining_opt_out={facts.reentraining_opt_out}",
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=f"ip_ownership={facts.ip_ownership}",
    ))

    assert {factor.criterion for factor in criteria} <= {
        name for _, name, _ in ARP_CRITERIA
    }

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
