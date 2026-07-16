from datetime import date

import pytest

from policybot.contract.arp import extract_contract_facts, family_extraction_model
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.fake import FakeLLMProvider

from tests.helpers.arp_fixtures import (
    DEFAULT_EVIDENCE,
    DEFAULT_QUOTE,
    DEFAULT_URL,
    arp_extraction_responses,
)


def _evidence(text: str = DEFAULT_EVIDENCE) -> ContractEvidence:
    """Preuve par défaut : celle dont `arp_extraction_responses` tire sa citation.

    L'extraction refuse toute valeur dont la citation n'est pas ancrée dans la
    preuve, donc un test qui vérifie des valeurs doit fournir cette preuve-là.
    """
    return ContractEvidence.from_single(FetchedTerms(
        text=text, source_url=DEFAULT_URL, fetched_at=date(2026, 7, 14),
    ))


def test_family_extraction_model_declares_only_its_own_fields():
    model = family_extraction_model(FACT_FAMILIES[0])

    assert set(model.model_fields) == {
        field.name for field in FACT_FAMILIES[0].fields
    }


def test_one_llm_call_per_family_each_prompt_scoped_to_its_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        training_default="no", data_residency="quebec", encryption_standard="strong",
    ))

    facts = extract_contract_facts(_evidence(), llm)

    assert len(llm.calls) == len(FACT_FAMILIES)
    assert facts.training_default == "no"
    assert facts.data_residency == "quebec"
    assert facts.encryption_standard == "strong"

    training_prompt = llm.calls[0][1]
    assert "training_default" in training_prompt
    assert "encryption_standard" not in training_prompt


def test_each_fact_carries_its_url_and_verbatim_quote():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(training_default="yes"))

    facts = extract_contract_facts(_evidence(), llm)

    proof = facts.evidence["training_default"]
    assert proof.value == "yes"
    assert proof.source_url == DEFAULT_URL
    assert proof.quote == DEFAULT_QUOTE
    assert proof.quote in DEFAULT_EVIDENCE
    assert proof.confidence == 0.9


def test_a_value_without_a_quote_is_demoted_to_unknown():
    responses = arp_extraction_responses(training_default="no")
    responses[0]["training_default"]["quote"] = ""

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "valeur écartée: aucune citation vérifiable"


def test_a_value_outside_the_allowed_set_is_demoted_to_unknown():
    responses = arp_extraction_responses(training_default="no")
    responses[0]["training_default"]["value"] = "peut-être"

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    proof = facts.evidence["training_default"]
    assert proof.note == "valeur écartée: valeur hors des valeurs permises"
    assert proof.confidence == 0.0


def test_a_legitimate_llm_unknown_keeps_its_quote_and_confidence_without_a_note():
    responses = arp_extraction_responses()
    responses[0]["training_default"] = {
        "value": "unknown",
        "source_url": DEFAULT_URL,
        "quote": "Le contrat ne précise pas ce point.",
        "confidence": 0.4,
    }

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    proof = facts.evidence["training_default"]
    assert proof.value == "unknown"
    assert proof.note is None
    assert proof.quote == "Le contrat ne précise pas ce point."
    assert proof.confidence == 0.4


def test_a_whitespace_only_quote_is_demoted_to_unknown():
    responses = arp_extraction_responses(training_default="no")
    responses[0]["training_default"]["quote"] = "   "

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "valeur écartée: aucune citation vérifiable"


def test_an_empty_source_url_is_demoted_to_unknown():
    responses = arp_extraction_responses(training_default="no")
    responses[0]["training_default"]["source_url"] = ""

    facts = extract_contract_facts(_evidence(), FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "valeur écartée: aucune citation vérifiable"


def test_quote_must_belong_to_the_exact_document_named_by_source_url():
    from policybot.contract.evidence import EvidenceDocument

    evidence = ContractEvidence(documents_by_family={
        family.name: [
            EvidenceDocument(
                url="https://example.test/a",
                title="A",
                content=DEFAULT_QUOTE + " Document A only.",
                source_type="contractual",
                collected_at=date(2026, 7, 14),
            ),
            EvidenceDocument(
                url="https://example.test/b",
                title="B",
                content="Document B has unrelated contractual content.",
                source_type="contractual",
                collected_at=date(2026, 7, 14),
            ),
        ]
        for family in FACT_FAMILIES
    })
    responses = arp_extraction_responses(training_default="no")
    responses[0]["training_default"]["source_url"] = "https://example.test/b"
    responses[0]["training_default"]["quote"] = DEFAULT_QUOTE

    facts = extract_contract_facts(evidence, FakeLLMProvider(json_responses=responses))

    proof = facts.evidence["training_default"]
    assert proof.value == "unknown"
    assert proof.outcome == "citation_rejected"
    assert proof.note == "citation introuvable dans la source indiquée"


def test_a_failed_family_leaves_its_fields_unknown_and_annotated():
    evidence = _evidence()
    del evidence.by_family["entrainement_reutilisation"]
    evidence.failed_families = ("entrainement_reutilisation",)
    responses = arp_extraction_responses(data_residency="quebec")[1:]

    facts = extract_contract_facts(evidence, FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "collecte Tavily échouée"
    assert facts.data_residency == "quebec"


def test_a_family_absent_without_being_marked_failed_is_annotated_no_evidence_collected():
    evidence = _evidence()
    del evidence.by_family["entrainement_reutilisation"]
    # Contrairement au test précédent, `failed_families` reste vide : cette
    # famille est simplement absente de l'évidence collectée.
    responses = arp_extraction_responses(data_residency="quebec")[1:]

    facts = extract_contract_facts(evidence, FakeLLMProvider(json_responses=responses))

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "aucune évidence collectée"
    assert facts.data_residency == "quebec"


def test_a_family_llm_failure_degrades_only_that_family():
    class HalfBrokenLLM(FakeLLMProvider):
        def complete_structured(self, system, user, schema, **kwargs):
            if "training_default" in user:
                raise RuntimeError("le modèle a renvoyé du JSON invalide")
            return super().complete_structured(system, user, schema, **kwargs)

    llm = HalfBrokenLLM(json_responses=arp_extraction_responses(data_residency="quebec")[1:])

    facts = extract_contract_facts(_evidence(), llm)

    assert facts.training_default == "unknown"
    assert facts.evidence["training_default"].note == "extraction LLM échouée"
    assert facts.data_residency == "quebec"


def test_oversized_family_evidence_is_trimmed_with_that_family_s_keywords():
    filler = "Texte non pertinent. " * 3000
    text = (
        filler
        + " We do not use your business data to train our models. "
        + filler
        + " Data is encrypted at rest and in transit. "
        + filler
    )
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(training_default="no"))

    extract_contract_facts(_evidence(text), llm)

    training_prompt = llm.calls[0][1]
    assert "train our models" in training_prompt
    assert "encrypted at rest" not in training_prompt
    assert len(training_prompt) < len(text)


def test_source_url_and_fetched_at_come_from_the_evidence():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses())

    facts = extract_contract_facts(_evidence(), llm)

    assert facts.source_url == DEFAULT_URL
    assert facts.fetched_at == date(2026, 7, 14)


def test_fetched_at_is_the_oldest_date_across_families_not_the_first_in_dict_order():
    # `by_family` insertion order (a, b, c) differs deliberately from
    # `FACT_FAMILIES` order used by `primary_source_url()`, so this proves
    # `fetched_at` doesn't just tag along with whichever URL is primary.
    evidence = ContractEvidence(by_family={
        "hebergement_retention": FetchedTerms(
            text="t-b", source_url="https://example.test/b", fetched_at=date(2026, 7, 12),
        ),
        "entrainement_reutilisation": FetchedTerms(
            text="t-a", source_url="https://example.test/a", fetched_at=date(2026, 5, 1),
        ),
        "securite_technique": FetchedTerms(
            text="t-c", source_url="https://example.test/c", fetched_at=date(2026, 7, 13),
        ),
    })
    responses = arp_extraction_responses()[:3]

    facts = extract_contract_facts(evidence, FakeLLMProvider(json_responses=responses))

    assert facts.fetched_at == date(2026, 5, 1)


def test_evidence_dict_contains_all_nineteen_fact_keys():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses())

    facts = extract_contract_facts(_evidence(), llm)

    expected_keys = {field.name for family in FACT_FAMILIES for field in family.fields}
    assert set(facts.evidence) == expected_keys
    assert len(facts.evidence) == 19


def test_empty_evidence_yields_all_unknown_without_calling_the_llm():
    llm = FakeLLMProvider(json_responses=[])

    facts = extract_contract_facts(ContractEvidence(by_family={}), llm)

    assert llm.calls == []
    assert facts.training_default == "unknown"
    assert facts.extraction_confidence == 0.0
