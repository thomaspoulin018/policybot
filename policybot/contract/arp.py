from __future__ import annotations

import re
from statistics import mean
from typing import Optional

from pydantic import BaseModel, Field, create_model

from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType, FactEvidence
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import FACT_FAMILIES, FactFamily, FactField
from policybot.llm.provider import LLMProvider
from policybot.criteria import ARP_CRITERIA
from policybot.tracing import trace_step

CURRENT_ARP_SCHEMA_VERSION = 2

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

_SYSTEM = (
    "You extract normalized contract facts for an AI tool. Return only one JSON "
    "object. Use only the allowed values listed in the prompt. Answer unknown "
    "when the evidence does not allow a conclusion. Do not infer guarantees "
    "that are not written in the evidence. For every field, quote verbatim the "
    "sentence from the evidence that supports the value, and give the URL of the "
    "source it came from. If you cannot quote the evidence, answer unknown."
)


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


def _build_family_prompt(family: FactFamily, text: str) -> str:
    lines = [
        "Required JSON keys. Each key maps to an object "
        '{"value": ..., "source_url": ..., "quote": ..., "confidence": 0..1}.',
    ]
    for field in family.fields:
        lines.append(f"- {field.name}: {' | '.join(field.allowed_values)} — {field.hint}")
    lines.append(
        "Include every key even when unknown. `quote` must be copied verbatim from "
        "the evidence; without a quote, answer unknown."
    )
    lines.append("")
    lines.append("Evidence:")
    lines.append(_select_evidence_text(text, family.keywords))
    return "\n".join(lines)


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


def _accept(field: FactField, raw: FieldExtraction, evidence_text: str) -> FactEvidence:
    """Aucune valeur n'entre dans ContractFacts sans citation ancrée dans la preuve."""
    if raw.value not in field.allowed_values:
        # Le LLM a inventé une valeur hors du contrat du champ : distinct d'un
        # "unknown" légitime, ça doit être visible pour l'officier.
        return FactEvidence(
            value="unknown", confidence=0.0,
            note="valeur écartée: valeur hors des valeurs permises",
        )
    value = raw.value
    quote = (raw.quote or "").strip()[:_MAX_QUOTE_CHARS]

    if value == "unknown":
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote or None,
            confidence=raw.confidence,
        )
    if not quote or not raw.source_url:
        return FactEvidence(
            value="unknown", confidence=0.0,
            note="valeur écartée: aucune citation vérifiable",
        )
    if not _quote_is_anchored(quote, evidence_text):
        # La citation n'est pas un extrait de la page : le LLM l'a peut-être
        # inventée en même temps que la valeur. On n'affirme rien sans ancrage.
        return FactEvidence(
            value="unknown", source_url=raw.source_url, quote=quote, confidence=0.0,
            note="citation introuvable dans la preuve",
        )
    return FactEvidence(
        value=value, source_url=raw.source_url, quote=quote, confidence=raw.confidence,
    )


def _unresolved(family: FactFamily, note: str) -> dict[str, FactEvidence]:
    return {
        field.name: FactEvidence(value="unknown", note=note) for field in family.fields
    }


def _extract_family(
    family: FactFamily, evidence: ContractEvidence, llm: LLMProvider,
) -> dict[str, FactEvidence]:
    if family.name in evidence.failed_families:
        return _unresolved(family, "collecte Tavily échouée")
    terms = evidence.by_family.get(family.name)
    if terms is None:
        return _unresolved(family, "aucune évidence collectée")

    with trace_step(None, "arp_family_extraction", family=family.name) as extra:
        try:
            extracted = llm.complete_structured(
                _SYSTEM,
                _build_family_prompt(family, terms.text),
                family_extraction_model(family),
                run_name=f"extract_contract_facts:{family.name}",
                tags=["arp_extraction", family.name],
            )
        except Exception as exc:  # noqa: BLE001 — une famille perdue ne doit pas tuer l'entrevue
            extra["outcome"] = "failed"
            extra["error"] = type(exc).__name__
            return _unresolved(family, "extraction LLM échouée")
        extra["outcome"] = "ok"

    return {
        field.name: _accept(field, getattr(extracted, field.name), terms.text)
        for field in family.fields
    }


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
    fetched_at = min(
        (terms.fetched_at for terms in evidence.by_family.values()), default=None,
    )

    return ContractFacts(
        **values,
        evidence=proofs,
        source_url=primary,
        fetched_at=fetched_at,
        extraction_confidence=round(mean(confidences), 2) if confidences else 0.0,
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
    return " — ".join(parts)


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    """Produce the 8 Partie A criteria PolicyBot can derive automatically."""
    criteria: list[RiskFactor] = []

    residency_risk = "F" if facts.data_residency == "canada" else "M"
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

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=_observation(facts, "trains_on_input"),
    ))

    reuse_risk = "F" if facts.contract_prohibits_reuse == "yes" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Garanties contractuelles de non-divulgation",
        inherent=reuse_risk, residual=reuse_risk, origin="rule",
        observations=_observation(facts, "contract_prohibits_reuse"),
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=_observation(facts, "encryption_standard"),
    ))

    opt_out_risk = "F" if facts.reentraining_opt_out == "yes" else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=opt_out_risk, origin="rule",
        observations=_observation(facts, "reentraining_opt_out"),
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=_observation(facts, "ip_ownership"),
    ))

    assert {factor.criterion for factor in criteria} <= {
        name for _, name, _ in ARP_CRITERIA
    }

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, schema_version=CURRENT_ARP_SCHEMA_VERSION, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
