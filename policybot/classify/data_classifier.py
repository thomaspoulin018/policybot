from __future__ import annotations
from pydantic import BaseModel
from policybot.models import DataClass
from policybot.llm.provider import LLMProvider

_SYSTEM = (
    "Tu analyses la DESCRIPTION de données (jamais les données elles-mêmes) qu'un "
    "employé veut soumettre à un outil d'IA. Réponds uniquement en JSON avec les "
    "clés booléennes: already_public, contains_personal_info, strategic_sensitive, "
    "internal_nonpublic, highly_sensitive_secret, et un flottant confidence (0-1)."
)
_CONFIDENCE_FLOOR = 0.6


class DataClassification(BaseModel):
    data_classification: DataClass
    rens_personnels: bool
    signals: list[str]
    confidence: float
    needs_officer_confirmation: bool


def _decide(sig: dict) -> tuple[DataClass, bool]:
    """Deterministic, conservative decision tree over LLM signals.

    Returns (level, defaulted) where `defaulted` marks an ambiguous fallback.
    """
    if sig.get("highly_sensitive_secret"):
        return "Protégé C", False
    if sig.get("contains_personal_info") or sig.get("strategic_sensitive"):
        return "Protégé B", False
    if sig.get("already_public") and not sig.get("internal_nonpublic"):
        return "Non classifié", False
    if sig.get("internal_nonpublic"):
        return "Protégé A", False
    return "Protégé A", True  # conservative default when signals are inconclusive


def classify_data(description: str, llm: LLMProvider) -> DataClassification:
    sig = llm.complete_json(
        _SYSTEM, description,
        run_name="classify_data_sensitivity", tags=["data_classification"],
    )
    level, defaulted = _decide(sig)
    confidence = float(sig.get("confidence", 0.0))
    signals = [k for k, v in sig.items() if v is True]
    needs_confirm = defaulted or confidence < _CONFIDENCE_FLOOR
    return DataClassification(
        data_classification=level,
        rens_personnels=bool(sig.get("contains_personal_info")),
        signals=signals,
        confidence=confidence,
        needs_officer_confirmation=needs_confirm,
    )
