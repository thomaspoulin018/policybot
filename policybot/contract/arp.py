from __future__ import annotations

import re
from statistics import mean
from typing import Optional

from pydantic import BaseModel, Field, create_model

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
from policybot.contract.families import FACT_FAMILIES, FactFamily, FactField
from policybot.llm.provider import LLMProvider
from policybot.prompts import get_prompt
from policybot.criteria import ARP_CRITERIA
from policybot.tracing import mask_text, trace_step

CURRENT_ARP_SCHEMA_VERSION = 3

_MAX_FAMILY_EVIDENCE_CHARS = 8000
_SOURCE_SEPARATOR = "\n\n---\n\n"
_MAX_QUOTE_CHARS = 300
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

class FieldExtraction(BaseModel):
    value: str = "unknown"
    source_url: Optional[str] = None
    quote: Optional[str] = Field(
        None, description="Verbatim sentence from the evidence supporting the value.",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)


_MODEL_CACHE: dict[str, type[BaseModel]] = {}


def family_extraction_model(family: FactFamily) -> type[BaseModel]:
    """Un schéma Pydantic par famille : le LLM ne voit que les champs qu'il doit remplir."""
    if family.name not in _MODEL_CACHE:
        class_name = "".join(part.capitalize() for part in family.name.split("_")) + "Extraction"
        _MODEL_CACHE[family.name] = create_model(
            class_name,
            **{
                field.name: (FieldExtraction, Field(default_factory=FieldExtraction))
                for field in family.fields
            },
        )
    return _MODEL_CACHE[family.name]


def _select_evidence_text(
    text: str, keywords: tuple[str, ...], max_chars: int = _MAX_FAMILY_EVIDENCE_CHARS,
) -> str:
    """Ne garde que les extraits pertinents pour CETTE famille quand l'évidence déborde.

    Sur le chemin Tavily l'évidence d'une famille tient presque toujours dans le
    budget ; sur le chemin de repli `fetch_terms` (une page de CGU entière), ce
    découpage est ce qui rend le prompt exploitable.
    """
    if len(text) <= max_chars:
        return text

    excerpts: list[str] = []
    seen: set[str] = set()
    used = 0

    def add_excerpt(excerpt: str, limit: int = max_chars) -> None:
        nonlocal used
        excerpt = excerpt.strip()
        if not excerpt or excerpt in seen or used >= limit:
            return
        remaining = limit - used
        if len(excerpt) > remaining:
            excerpt = excerpt[:remaining].rstrip()
        excerpts.append(excerpt)
        seen.add(excerpt)
        used += len(excerpt) + 7

    heading_budget = max_chars // 10
    for source in text.split(_SOURCE_SEPARATOR):
        if used >= heading_budget:
            break
        add_excerpt(source[:350], heading_budget)

    for pattern in keywords:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - 250)
            end = min(len(text), match.end() + 500)
            add_excerpt(text[start:end])
            break
        if used >= max_chars:
            break

    return "\n\n...\n\n".join(excerpts) if excerpts else text[:max_chars]


def _document_prompt_text(
    document: EvidenceDocument,
    family: FactFamily,
    max_chars: int,
) -> str:
    selected = _select_evidence_text(document.content, family.keywords, max_chars)
    return (
        "DOCUMENT SOURCE\n"
        f"URL: {document.url}\n"
        f"TYPE: {document.source_type}\n"
        f"DATE_EFFECTIVE: {document.effective_date or 'unknown'}\n"
        f"DATE_COLLECTE: {document.collected_at}\n"
        f"SHA256: {document.sha256}\n"
        f"TITRE: {document.title}\n"
        f"CONTENU:\n{selected}"
    )


def _family_evidence_text(family: FactFamily, documents: list[EvidenceDocument]) -> str:
    if not documents:
        return ""
    per_document = max(800, _MAX_FAMILY_EVIDENCE_CHARS // len(documents))
    return _SOURCE_SEPARATOR.join(
        _document_prompt_text(document, family, per_document)
        for document in documents
    )[:_MAX_FAMILY_EVIDENCE_CHARS + len(documents) * 350]


def _build_family_prompt(family: FactFamily, documents: list[EvidenceDocument]) -> str:
    fields = []
    for field in family.fields:
        fields.append(f"- {field.name}: {' | '.join(field.allowed_values)} — {field.hint}")
    return get_prompt("contract_extraction").render_user(
        fields="\n".join(fields),
        evidence=_family_evidence_text(family, documents),
    )


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


def _accept(
    field: FactField,
    raw: FieldExtraction,
    documents: list[EvidenceDocument],
) -> FactEvidence:
    """Aucune valeur n'entre dans ContractFacts sans citation ancrée dans la preuve."""
    if raw.value not in field.allowed_values:
        # Le LLM a inventé une valeur hors du contrat du champ : distinct d'un
        # "unknown" légitime, ça doit être visible pour l'officier.
        return FactEvidence(
            value="unknown", confidence=0.0,
            note="valeur écartée: valeur hors des valeurs permises",
            outcome="invalid_value",
        )
    value = raw.value
    quote = (raw.quote or "").strip()[:_MAX_QUOTE_CHARS]

    if value == "unknown":
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote or None,
            confidence=raw.confidence,
            outcome="model_abstention",
        )
    if not quote or not raw.source_url:
        return FactEvidence(
            value="unknown", confidence=0.0,
            note="valeur écartée: aucune citation vérifiable",
            outcome="citation_rejected",
        )
    source_document = next(
        (document for document in documents if document.url == raw.source_url),
        None,
    )
    if source_document is None:
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote,
            confidence=0.0, outcome="citation_rejected",
            note="source URL absente de la preuve collectée",
        )
    if not _quote_is_anchored(quote, source_document.content):
        # La citation n'est pas un extrait de la page : le LLM l'a peut-être
        # inventée en même temps que la valeur. On n'affirme rien sans ancrage.
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote, confidence=0.0,
            note="citation introuvable dans la source indiquée",
            outcome="citation_rejected",
        )
    return FactEvidence(
        value=value, source_url=raw.source_url, quote=quote, confidence=raw.confidence,
        outcome="accepted",
        source_type=source_document.source_type,
        source_effective_date=source_document.effective_date,
        source_collected_at=source_document.collected_at,
        source_sha256=source_document.sha256,
    )


def _unresolved(
    family: FactFamily,
    note: str,
    outcome: str,
) -> dict[str, FactEvidence]:
    return {
        field.name: FactEvidence(value="unknown", note=note, outcome=outcome)
        for field in family.fields
    }


def _trace_fact_decision(
    family: FactFamily,
    field: FactField,
    proof: FactEvidence,
    *,
    raw: FieldExtraction | None = None,
    documents: list[EvidenceDocument] = (),
) -> None:
    """Log one extraction decision without exposing contract or model text."""
    source_url = raw.source_url if raw else None
    quote = (raw.quote or "").strip() if raw else ""
    source_found = any(document.url == source_url for document in documents)
    model_value = None
    invalid_model_value = None
    if raw is not None:
        if raw.value in field.allowed_values:
            model_value = raw.value
        else:
            # A free-form model value can contain arbitrary text, so mask it.
            model_value = "invalid"
            invalid_model_value = mask_text(raw.value)

    with trace_step(
        None,
        "arp_fact_extraction",
        family=family.name,
        fact=field.name,
    ) as extra:
        extra.update({
            "model_value": model_value,
            "invalid_model_value": invalid_model_value,
            "model_confidence": raw.confidence if raw else None,
            "citation": mask_text(quote) if quote else None,
            "source_url_supplied": bool(source_url),
            "source_url_in_collected_evidence": source_found,
            "final_value": proof.value,
            "outcome": proof.outcome,
            # Notes are controlled PolicyBot messages, never source text.
            "reason": proof.note,
        })


def _trace_family_decisions(
    family: FactFamily,
    proofs: dict[str, FactEvidence],
    *,
    raw_extraction: BaseModel | None = None,
    documents: list[EvidenceDocument] = (),
) -> dict[str, FactEvidence]:
    for field in family.fields:
        raw = getattr(raw_extraction, field.name) if raw_extraction else None
        _trace_fact_decision(
            family, field, proofs[field.name], raw=raw, documents=documents,
        )
    return proofs


def _extract_family(
    family: FactFamily, evidence: ContractEvidence, llm: LLMProvider,
) -> dict[str, FactEvidence]:
    if family.name in evidence.failed_families:
        proofs = _unresolved(
            family, "collecte Tavily échouée", "collection_failure",
        )
        return _trace_family_decisions(family, proofs)
    documents = evidence.documents_for_family(family.name)
    if not documents:
        proofs = _unresolved(
            family, "aucune évidence collectée", "evidence_missing",
        )
        return _trace_family_decisions(family, proofs)

    with trace_step(None, "arp_family_extraction", family=family.name) as extra:
        try:
            prompt = get_prompt("contract_extraction")
            extracted = llm.complete_structured(
                prompt.render_system(),
                _build_family_prompt(family, documents),
                family_extraction_model(family),
                run_name=f"extract_contract_facts:{family.name}",
                tags=["arp_extraction", family.name],
                task="contract_extraction",
            )
        except Exception as exc:  # noqa: BLE001 — une famille perdue ne doit pas tuer l'entrevue
            extra["outcome"] = "failed"
            extra["error"] = type(exc).__name__
            proofs = _unresolved(
                family, "extraction LLM échouée", "llm_failure",
            )
            return _trace_family_decisions(family, proofs, documents=documents)
        extra["outcome"] = "ok"

    proofs = {
        field.name: _accept(field, getattr(extracted, field.name), documents)
        for field in family.fields
    }
    return _trace_family_decisions(
        family, proofs, raw_extraction=extracted, documents=documents,
    )


def extract_contract_facts(evidence: ContractEvidence, llm: LLMProvider) -> ContractFacts:
    proofs: dict[str, FactEvidence] = {}
    for family in FACT_FAMILIES:
        proofs.update(_extract_family(family, evidence, llm))

    values = {name: proof.value for name, proof in proofs.items()}
    confidences = [proof.confidence for proof in proofs.values() if proof.value != "unknown"]
    primary = evidence.primary_source_url()
    # Conservateur : la date de péremption du cache suit la page la PLUS
    # ANCIENNE parmi les familles collectées, pas l'ordre d'insertion du dict
    # (qui peut différer de l'ordre de `primary_source_url()`).
    fetched_at = min((
        document.collected_at
        for documents in evidence.documents_by_family.values()
        for document in documents
    ), default=None)
    unique_documents: dict[str, EvidenceDocument] = {}
    for documents in evidence.documents_by_family.values():
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
        extraction_confidence=round(mean(confidences), 2) if confidences else 0.0,
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
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=_observation(facts, "data_residency"),
    ))

    law_risk = "F" if facts.applicable_law == "quebec_canada" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Juridiction applicable",
        inherent=law_risk, residual=law_risk, origin="rule",
        observations=_observation(facts, "applicable_law"),
    ))

    dependency_risk = "F" if facts.foreign_vendor_dependency == "no" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Dépendance technologique",
        inherent=dependency_risk, residual=dependency_risk, origin="rule",
        observations=_observation(facts, "foreign_vendor_dependency"),
    ))

    training_protected = (
        facts.training_default == "no" or facts.opt_out_confirmed_enabled == "yes"
    )
    training_risk = "F" if training_protected else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=training_risk, origin="rule",
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
        inherent=reuse_risk, residual=reuse_risk, origin="rule",
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
        inherent=authentication_risk, residual=authentication_risk, origin="rule",
        observations=_observation(facts, "authentication_support"),
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=_observation(facts, "encryption_standard"),
    ))

    audit_logging_risk = {
        "prompt_output_accessible": "F",
        "access_logs_only": "M",
    }.get(facts.audit_logging, "E")
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Journalisation et traçabilité",
        inherent=audit_logging_risk, residual=audit_logging_risk, origin="rule",
        observations=_observation(facts, "audit_logging"),
    ))

    opt_out_risk = "F" if training_protected else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=opt_out_risk, origin="rule",
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
        inherent=incident_response_risk, residual=incident_response_risk, origin="rule",
        observations=_observation(facts, "incident_response"),
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=ip_risk, origin="rule",
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
        inherent=acceptable_terms_risk, residual=acceptable_terms_risk, origin="rule",
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
        inherent=license_risk, residual=license_risk, origin="rule",
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
