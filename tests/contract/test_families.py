from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import (
    ALL_FACT_FIELDS,
    FACT_FAMILIES,
    family_by_name,
    load_fact_families,
)
from policybot.contract.fetcher import FetchedTerms
from policybot.models import ContractFacts, FactEvidence

CONTRACT_FACT_FIELDS = {
    "trains_on_input", "data_retention", "data_residency", "sub_processors",
    "human_review", "encryption_standard", "ip_ownership", "applicable_law",
    "foreign_vendor_dependency", "contract_prohibits_reuse", "reentraining_opt_out",
    "authentication_support", "audit_logging", "institutional_terms",
    "quebec_higher_ed_license", "incident_response",
}

FACT_FAMILIES_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "fact_families.yaml"
)


def test_repository_fact_families_are_loaded_from_yaml():
    loaded = load_fact_families(FACT_FAMILIES_PATH, env={})

    assert loaded == FACT_FAMILIES
    assert [family.name for family in loaded] == [
        "entrainement_reutilisation",
        "hebergement_retention",
        "securite_technique",
        "legal_pi",
        "termes_institutionnels",
    ]


def test_fact_family_config_rejects_duplicate_fields(tmp_path):
    path = tmp_path / "fact_families.yaml"
    path.write_text(
        """
version: 1
families:
  - name: duplicate
    query: "{tool} {vendor} terms"
    fields:
      - {name: same, allowed_values: [unknown], hint: first}
      - {name: same, allowed_values: [unknown], hint: second}
    keywords: [terms]
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match="globally unique"):
        load_fact_families(path, env={})


def test_families_cover_every_contract_fact_field_exactly_once():
    names = [field.name for family in FACT_FAMILIES for field in family.fields]

    assert len(FACT_FAMILIES) == 5
    assert len(names) == len(set(names)) == 16
    assert set(names) == CONTRACT_FACT_FIELDS
    assert {field.name for field in ALL_FACT_FIELDS} == CONTRACT_FACT_FIELDS


def test_family_allowed_values_match_contract_facts_literals():
    literals = {
        name: set(info.annotation.__args__)
        for name, info in ContractFacts.model_fields.items()
        if name in CONTRACT_FACT_FIELDS
    }

    for field in ALL_FACT_FIELDS:
        assert set(field.allowed_values) == literals[field.name], field.name
        assert "unknown" in field.allowed_values


def test_every_family_has_a_query_template_and_keywords():
    for family in FACT_FAMILIES:
        assert "{tool}" in family.query and "{vendor}" in family.query
        assert family.keywords


def test_family_by_name_returns_none_for_unknown_family():
    assert family_by_name("entrainement_reutilisation") is FACT_FAMILIES[0]
    assert family_by_name("famille_inexistante") is None


def test_contract_evidence_from_single_feeds_every_family():
    terms = FetchedTerms(
        text="CGU complètes", source_url="https://example.test/cgu", fetched_at=date.today(),
    )

    evidence = ContractEvidence.from_single(terms)

    assert set(evidence.by_family) == {family.name for family in FACT_FAMILIES}
    assert evidence.primary_source_url() == "https://example.test/cgu"
    assert evidence.failed_families == ()
    assert not evidence.is_empty()


def test_empty_contract_evidence_is_empty():
    assert ContractEvidence(by_family={}).is_empty()
    assert ContractEvidence(by_family={}).primary_source_url() is None


def test_contract_facts_carries_per_field_evidence():
    facts = ContractFacts(
        trains_on_input="no",
        evidence={"trains_on_input": FactEvidence(
            value="no",
            source_url="https://example.test/cgu",
            quote="We do not train our models on your business data.",
            confidence=0.9,
        )},
    )

    assert facts.evidence["trains_on_input"].quote.startswith("We do not train")
    assert ContractFacts().evidence == {}
