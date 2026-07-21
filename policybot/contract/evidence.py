"""Structured contract evidence, indexed by contract fact."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import hashlib
from typing import Literal

from policybot.models import FactEvidence


SourceType = Literal[
    "contractual", "dpa", "official_technical", "commercial", "secondary",
]
CollectionMethod = Literal["exa_search"]


@dataclass(frozen=True)
class EvidenceDocument:
    """An auditable Exa result whose URL is inseparable from its retrieved text."""

    url: str
    content: str
    title: str = ""
    source_type: SourceType = "secondary"
    collection_method: CollectionMethod = "exa_search"
    effective_date: date | None = None
    collected_at: date = field(default_factory=date.today)
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.sha256:
            digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
            object.__setattr__(self, "sha256", digest)


@dataclass
class ContractEvidence:
    """All candidate documents and the selected, anchored proof for each fact."""

    documents_by_fact: dict[str, list[EvidenceDocument]] = field(default_factory=dict)
    facts: dict[str, FactEvidence] = field(default_factory=dict)
    failed_facts: tuple[str, ...] = field(default=())

    def documents_for_fact(self, fact: str) -> list[EvidenceDocument]:
        return list(self.documents_by_fact.get(fact, ()))

    def primary_source_url(self) -> str | None:
        for proof in self.facts.values():
            if proof.outcome == "accepted" and proof.source_url:
                return proof.source_url
        for documents in self.documents_by_fact.values():
            if documents:
                return documents[0].url
        return None

    def is_empty(self) -> bool:
        return not self.documents_by_fact and not self.facts
