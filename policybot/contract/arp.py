from __future__ import annotations

import re

from policybot.models import (
    ContractFacts,
    ContractOfferingIdentity,
    ArpRecord,
    RiskFactor,
    IagType,
    FactEvidence,
    ContractSource,
)
from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.contract.fact_search import CONTRACT_FACT_NAMES
from policybot.criteria import ARP_CRITERIA

CURRENT_ARP_SCHEMA_VERSION = 4

# En dessous de ce seuil (après normalisation), une citation matche trivialement
# n'importe quel texte ("yes", "encryption") et ne prouve rien : on la refuse.
_MIN_QUOTE_MATCH_CHARS = 15
# Ponctuation markdown/typographique effacée avant comparaison, pour qu'une
# citation honnête que le LLM a délestée de sa mise en forme reste reconnue.
_MATCH_STRIP = str.maketrans({
    "*": " ", "_": " ", "#": " ", "`": " ", ">": " ",
    "“": '"', "”": '"', "‘": "'", "’": "'", "—": "-", "–": "-", "…": " ",
})


def _normalize_for_match(text: str) -> str:
    """Forme comparable : minuscules, markdown/guillemets neutralisés, espaces écrasés."""
    return re.sub(r"\s+", " ", text.translate(_MATCH_STRIP).lower()).strip()

def _quote_is_anchored(quote: str, evidence_text: str) -> bool:
    """La citation est-elle réellement un extrait de la preuve (à la mise en forme près) ?

    Compare les deux formes normalisées : une citation honnête que le LLM a
    reformatée reste reconnue, mais une valeur+citation co-hallucinées, absentes
    de la page, ne le sont pas. Une citation trop courte ne prouve rien.
    """
    needle = _normalize_for_match(quote)
    if len(needle) < _MIN_QUOTE_MATCH_CHARS:
        return False
    return needle in _normalize_for_match(evidence_text)


def extract_contract_facts(evidence: ContractEvidence) -> ContractFacts:
    """Assemble already anchored Exa observations; this function calls no LLM."""
    proofs: dict[str, FactEvidence] = {}
    for fact in CONTRACT_FACT_NAMES:
        proof = evidence.facts.get(fact)
        if proof is None:
            outcome = "collection_failure" if fact in evidence.failed_facts else "evidence_missing"
            note = "collecte Exa échouée" if outcome == "collection_failure" else "aucune évidence Exa collectée"
            proof = FactEvidence(value="unknown", note=note, outcome=outcome)
        proofs[fact] = proof

    values = {name: proof.value for name, proof in proofs.items()}
    primary = evidence.primary_source_url()
    # Conservateur : la date de péremption du cache suit la page la PLUS
    # ANCIENNE parmi les documents collectés, pas l'ordre d'insertion du dict
    # (qui peut différer de l'ordre de `primary_source_url()`).
    fetched_at = min((
        document.collected_at
        for documents in evidence.documents_by_fact.values()
        for document in documents
    ), default=None)
    unique_documents: dict[str, EvidenceDocument] = {}
    for documents in evidence.documents_by_fact.values():
        for document in documents:
            unique_documents.setdefault(document.url, document)
    source_refs = [
        ContractSource(
            url=document.url,
            title=document.title,
            source_type=document.source_type,
            effective_date=document.effective_date,
            collected_at=document.collected_at,
            sha256=document.sha256,
        )
        for document in unique_documents.values()
    ]
    snapshot_ref = None
    if source_refs:
        import hashlib
        snapshot_ref = hashlib.sha256("|".join(
            f"{source.url}:{source.sha256}" for source in source_refs
        ).encode("utf-8")).hexdigest()

    return ContractFacts(
        **values,
        evidence=proofs,
        source_url=primary,
        fetched_at=fetched_at,
        snapshot_ref=snapshot_ref,
        extraction_confidence=round(
            sum(proof.outcome == "accepted" for proof in proofs.values()) / len(proofs), 2,
        ) if proofs else 0.0,
        sources=source_refs,
    )


def _observation(facts: ContractFacts, field_name: str) -> str:
    """La ligne que l'officier lit dans le rapport : la valeur, sa source, sa preuve."""
    base = f"{field_name}={getattr(facts, field_name)}"
    proof = facts.evidence.get(field_name)
    if proof is None:
        return base
    if proof.note:
        return f"{base} — {proof.note}"
    parts = [base]
    if proof.quote:
        parts.append(f"« {proof.quote} »")
    if proof.source_url:
        parts.append(f"source: {proof.source_url}")
    if proof.source_collected_at:
        parts.append(f"collectée le: {proof.source_collected_at}")
    if proof.source_sha256:
        parts.append(f"sha256: {proof.source_sha256}")
    return " — ".join(parts)


def build_arp(
    tool_name: str,
    iag_type: IagType,
    facts: ContractFacts,
    offering: ContractOfferingIdentity | None = None,
) -> ArpRecord:
    """Produce the 13 Partie A criteria PolicyBot can derive automatically."""
    criteria: list[RiskFactor] = []

    residency_risk = "F" if facts.data_residency == "quebec" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=None, origin="rule",
        observations=_observation(facts, "data_residency"),
    ))

    law_risk = "F" if facts.applicable_law == "quebec_canada" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Juridiction applicable",
        inherent=law_risk, residual=None, origin="rule",
        observations=_observation(facts, "applicable_law"),
    ))

    dependency_risk = "F" if facts.foreign_vendor_dependency == "no" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Dépendance technologique",
        inherent=dependency_risk, residual=None, origin="rule",
        observations=_observation(facts, "foreign_vendor_dependency"),
    ))

    training_protected = (
        facts.training_default == "no" or facts.opt_out_confirmed_enabled == "yes"
    )
    training_risk = "F" if training_protected else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=None, origin="rule",
        observations=" | ".join((
            _observation(facts, "training_default"),
            _observation(facts, "opt_out_available"),
            _observation(facts, "opt_out_confirmed_enabled"),
        )),
    ))

    reuse_risk = "F" if facts.contract_prohibits_reuse == "yes" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Garanties contractuelles de non-divulgation",
        inherent=reuse_risk, residual=None, origin="rule",
        observations=" | ".join((
            _observation(facts, "contract_prohibits_reuse"),
            _observation(facts, "provider_human_access"),
        )),
    ))

    authentication_risk = {
        "sso_mfa": "F",
        "partial": "M",
    }.get(facts.authentication_support, "E")
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Mécanismes d'authentification",
        inherent=authentication_risk, residual=None, origin="rule",
        observations=_observation(facts, "authentication_support"),
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=None, origin="rule",
        observations=_observation(facts, "encryption_standard"),
    ))

    audit_logging_risk = {
        "prompt_output_accessible": "F",
        "access_logs_only": "M",
    }.get(facts.audit_logging, "E")
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Journalisation et traçabilité",
        inherent=audit_logging_risk, residual=None, origin="rule",
        observations=_observation(facts, "audit_logging"),
    ))

    opt_out_risk = "F" if training_protected else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=None, origin="rule",
        observations=" | ".join((
            _observation(facts, "opt_out_available"),
            _observation(facts, "opt_out_confirmed_enabled"),
        )),
    ))

    incident_response_risk = {
        "documented_with_notice": "F",
        "documented_no_notice": "M",
    }.get(facts.incident_response, "E")
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Gestion des incidents",
        inherent=incident_response_risk, residual=None, origin="rule",
        observations=_observation(facts, "incident_response"),
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=None, origin="rule",
        observations=_observation(facts, "ip_ownership"),
    ))

    if facts.institutional_use_restricted == "yes":
        acceptable_terms_risk = "E"
    elif (
        facts.institutional_terms_available == "yes"
        and facts.dpa_available == "yes"
    ):
        acceptable_terms_risk = "F"
    elif (
        facts.institutional_terms_available == "yes"
        or facts.dpa_available == "yes"
    ):
        acceptable_terms_risk = "M"
    else:
        acceptable_terms_risk = "E"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle",
        criterion="Conditions d'utilisation acceptables",
        inherent=acceptable_terms_risk, residual=None, origin="rule",
        observations=" | ".join((
            _observation(facts, "institutional_terms_available"),
            _observation(facts, "dpa_available"),
            _observation(facts, "institutional_use_restricted"),
        )),
    ))

    license_risk = "F" if facts.quebec_higher_ed_license == "yes" else "E"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle",
        criterion="Compatibilité licence usage gouvernemental",
        inherent=license_risk, residual=None, origin="rule",
        observations=_observation(facts, "quebec_higher_ed_license"),
    ))

    assert {factor.criterion for factor in criteria} <= {
        name for _, name, _ in ARP_CRITERIA
    }

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, offering=offering,
        contract_facts=facts,
        criteria=criteria, schema_version=CURRENT_ARP_SCHEMA_VERSION,
        terms_snapshot=facts.snapshot_ref or facts.source_url,
        fetched_at=facts.fetched_at,
    )
