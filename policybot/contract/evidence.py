"""L'évidence contractuelle collectée, indexée par famille de critères."""
from __future__ import annotations

from dataclasses import dataclass, field

from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms


@dataclass
class ContractEvidence:
    by_family: dict[str, FetchedTerms]
    failed_families: tuple[str, ...] = field(default=())

    @classmethod
    def from_single(cls, terms: FetchedTerms) -> "ContractEvidence":
        """Chemin de repli `fetch_terms` : une seule page nourrit toutes les familles."""
        return cls(by_family={family.name: terms for family in FACT_FAMILIES})

    def primary_source_url(self) -> str | None:
        for family in FACT_FAMILIES:
            terms = self.by_family.get(family.name)
            if terms is not None:
                return terms.source_url
        return None

    def is_empty(self) -> bool:
        return not self.by_family
