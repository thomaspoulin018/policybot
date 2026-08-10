"""Politique déterministe de classement des sources ARP."""
from __future__ import annotations

from typing import Literal

SourceType = Literal[
    "contractual", "dpa", "official_technical", "commercial", "secondary",
]


_SOURCE_TYPE_PATTERNS: tuple[tuple[SourceType, tuple[str, ...]], ...] = (
    ("dpa", ("data-processing", "data_processing", "dpa", "privacy-addendum")),
    ("contractual", ("terms", "agreement", "legal", "policies", "licensing")),
    ("official_technical", ("docs", "learn", "help", "support", "security", "trust", "privacy")),
    ("commercial", ("products", "solutions", "enterprise", "business", "education")),
)


def classify_source(url: str) -> SourceType:
    lowered = url.casefold()
    for source_type, patterns in _SOURCE_TYPE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return source_type
    return "secondary"


def source_sort_key(result: dict, policy: dict | None) -> tuple[int, float, str]:
    """Option A: source type first, then Exa relevance, then a stable URL tie-break."""
    del policy
    url = str(result.get("url") or "")
    type_order = {
        "contractual": 0,
        "dpa": 1,
        "official_technical": 2,
        "commercial": 3,
        "secondary": 4,
    }
    try:
        score = -float(result.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return type_order[classify_source(url)], score, url
