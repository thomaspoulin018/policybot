"""Évidence contractuelle structurée par famille puis par URL."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import hashlib
from typing import Literal

from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms

SourceType = Literal[
    "contractual", "dpa", "official_technical", "commercial", "secondary",
]
CollectionMethod = Literal["direct", "search", "extract"]


@dataclass(frozen=True)
class EvidenceDocument:
    """Un document auditable; son URL ne peut jamais être dissociée de son texte."""

    url: str
    content: str
    title: str = ""
    source_type: SourceType = "secondary"
    collection_method: CollectionMethod = "direct"
    effective_date: date | None = None
    collected_at: date = field(default_factory=date.today)
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.sha256:
            digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
            object.__setattr__(self, "sha256", digest)

    @classmethod
    def from_terms(cls, terms: FetchedTerms) -> "EvidenceDocument":
        return cls(
            url=terms.source_url,
            content=terms.text,
            source_type="contractual",
            collection_method="direct",
            collected_at=terms.fetched_at,
        )


@dataclass
class ContractEvidence:
    documents_by_family: dict[str, list[EvidenceDocument]] = field(default_factory=dict)
    failed_families: tuple[str, ...] = field(default=())
    # Compatibilité de lecture pendant la migration. L'extraction n'utilise plus
    # ces blobs; elle consomme exclusivement `documents_by_family`.
    by_family: dict[str, FetchedTerms] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.by_family and not self.documents_by_family:
            self.documents_by_family = {
                name: [EvidenceDocument.from_terms(terms)]
                for name, terms in self.by_family.items()
            }
        elif self.documents_by_family and not self.by_family:
            self.by_family = {
                name: self._legacy_terms(documents)
                for name, documents in self.documents_by_family.items()
                if documents
            }

    @staticmethod
    def _legacy_terms(documents: list[EvidenceDocument]) -> FetchedTerms:
        text = "\n\n---\n\n".join(
            f"{'Source extraite Tavily' if document.collection_method == 'extract' else 'Source recherche Tavily' if document.collection_method == 'search' else 'Source directe'}\n"
            f"URL: {document.url}\n{document.content}"
            for document in documents
        )
        return FetchedTerms(
            text=text,
            source_url=documents[0].url,
            fetched_at=min(document.collected_at for document in documents),
        )

    @classmethod
    def from_single(cls, terms: FetchedTerms) -> "ContractEvidence":
        """Chemin de repli `fetch_terms` : une seule page nourrit toutes les familles."""
        document = EvidenceDocument.from_terms(terms)
        return cls(documents_by_family={
            family.name: [document] for family in FACT_FAMILIES
        })

    @classmethod
    def from_terms(cls, terms: list[FetchedTerms]) -> "ContractEvidence":
        documents = [EvidenceDocument.from_terms(item) for item in terms]
        return cls(documents_by_family={
            family.name: list(documents) for family in FACT_FAMILIES
        })

    def documents_for_family(self, family_name: str) -> list[EvidenceDocument]:
        # Si un ancien appelant a supprimé la vue `by_family`, respecter cette
        # suppression afin de garder la dégradation par famille prévisible.
        if self.by_family and family_name not in self.by_family:
            return []
        return list(self.documents_by_family.get(family_name, ()))

    def primary_source_url(self) -> str | None:
        for family in FACT_FAMILIES:
            documents = self.documents_for_family(family.name)
            if documents:
                return documents[0].url
        return None

    def is_empty(self) -> bool:
        return not any(self.documents_for_family(name) for name in self.documents_by_family)
