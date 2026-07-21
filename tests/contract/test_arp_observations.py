from datetime import date

from policybot.contract.arp import build_arp
from policybot.models import ContractFacts, FactEvidence


def _facts(**overrides) -> ContractFacts:
    return ContractFacts(
        training_default="no",
        evidence={"training_default": FactEvidence(
            value="no",
            source_url="https://example.test/terms",
            quote="We do not train our models on your business data.",
            confidence=0.9,
        )},
        source_url="https://example.test/terms",
        fetched_at=date(2026, 7, 14),
        **overrides,
    )


def _criterion(arp, name):
    return next(factor for factor in arp.criteria if factor.criterion == name)


def test_observations_cite_the_url_and_the_quote():
    arp = build_arp("ChatGPT", "publique", _facts())

    observations = _criterion(
        arp, "Données soumises utilisées pour entraînement du modèle",
    ).observations

    assert observations.startswith("training_default=no")
    assert "https://example.test/terms" in observations
    assert "We do not train our models" in observations


def test_a_fact_without_evidence_keeps_the_bare_observation():
    arp = build_arp("ChatGPT", "publique", _facts())

    observations = _criterion(arp, "Juridiction applicable").observations

    assert observations == "applicable_law=unknown"


def test_an_annotated_unknown_explains_itself_to_the_officer():
    facts = ContractFacts(evidence={"applicable_law": FactEvidence(
        value="unknown", note="collecte Exa échouée",
    )})

    arp = build_arp("ChatGPT", "publique", facts)

    observations = _criterion(arp, "Juridiction applicable").observations
    assert observations == "applicable_law=unknown — collecte Exa échouée"
