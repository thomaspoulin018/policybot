"""Offline Exa evidence fixtures shared by ARP-facing tests."""
from __future__ import annotations

from datetime import date

from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.contract.fact_search import CONTRACT_FACT_NAMES
from policybot.models import FactEvidence


DEFAULT_URL = "https://openai.com/policies/terms-of-use"
DEFAULT_EVIDENCE = (
    "The vendor's terms of service and privacy policy describe this fact "
    "explicitly for institutional customers such as universities."
)
DEFAULT_QUOTE = "The vendor's terms of service and privacy policy describe this fact"


def exa_evidence(_url: str = DEFAULT_URL, *, evidence: str = DEFAULT_EVIDENCE,
                 **values: str) -> ContractEvidence:
    """Build already-anchored Exa observations without an LLM or network call."""
    unknown_fields = set(values) - set(CONTRACT_FACT_NAMES)
    if unknown_fields:
        raise AssertionError(f"champs inconnus dans la fixture ARP: {sorted(unknown_fields)}")
    document = EvidenceDocument(
        url=_url, content=evidence, source_type="contractual", collected_at=date.today(),
    )
    facts: dict[str, FactEvidence] = {}
    documents: dict[str, list[EvidenceDocument]] = {}
    for name in CONTRACT_FACT_NAMES:
        value = values.get(name, "unknown")
        if value == "unknown":
            facts[name] = FactEvidence(value="unknown", outcome="model_abstention")
        else:
            facts[name] = FactEvidence(
                value=value, source_url=_url, declared_source_url=_url,
                quote=DEFAULT_QUOTE, confidence=1.0, outcome="accepted",
                source_type="contractual", source_collected_at=document.collected_at,
                source_sha256=document.sha256,
            )
            documents[name] = [document]
    return ContractEvidence(documents_by_fact=documents, facts=facts)


def arp_extraction_responses(*args, **kwargs) -> list[dict]:
    """Legacy test helper: contract extraction no longer consumes LLM responses."""
    return []
