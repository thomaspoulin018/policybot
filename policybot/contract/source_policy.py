"""Politique déterministe de classement des sources ARP : officielle ou autre.

Une seule distinction est défendable devant un lecteur : la page appartient-elle
au fournisseur (conditions, addenda, documentation, portail de confiance) ou
non. La taxonomie à cinq rangs qui précédait reposait sur des sous-chaînes
d'URL dont l'ordre décidait du classement, sans que rien ne rende ce classement
vérifiable.
"""
from __future__ import annotations

from typing import Literal

SourceType = Literal["official", "other"]


_OFFICIAL_MARKERS: tuple[str, ...] = (
    "terms", "agreement", "legal", "policies", "licensing",
    "data-processing", "data_processing", "dpa", "privacy-addendum",
    "docs", "learn", "help", "support", "security", "trust", "privacy",
)


def classify_source(url: str) -> SourceType:
    lowered = url.casefold()
    if any(marker in lowered for marker in _OFFICIAL_MARKERS):
        return "official"
    return "other"


def source_sort_key(result: dict) -> tuple[int, float, str]:
    """Source officielle d'abord, puis pertinence Exa, puis l'URL en départage."""
    url = str(result.get("url") or "")
    try:
        score = -float(result.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return (0 if classify_source(url) == "official" else 1), score, url
