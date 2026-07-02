from datetime import date
from policybot.llm.fake import FakeLLMProvider
from policybot.contract.fetcher import FetchedTerms
from policybot.contract.arp import extract_contract_facts, build_arp


def _terms():
    return FetchedTerms(text="...", source_url="http://x", fetched_at=date.today())


def test_extract_maps_llm_output_to_contractfacts():
    llm = FakeLLMProvider(json_responses=[{
        "trains_on_input": "yes", "data_retention": "indefinite",
        "data_residency": "us", "sub_processors": "undisclosed",
        "human_review": "no", "extraction_confidence": 0.8,
    }])
    facts = extract_contract_facts(_terms(), llm)
    assert facts.trains_on_input == "yes"
    assert facts.data_residency == "us"
    assert facts.source_url == "http://x"
    assert facts.extraction_confidence == 0.8


def test_build_arp_flags_training_as_high_risk():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(trains_on_input="yes"))
    training = [c for c in arp.criteria if "entraîn" in c.criterion.lower()]
    assert training and training[0].inherent == "E"
    assert all(c.origin == "rule" for c in arp.criteria)
    assert arp.iag_type == "publique"
