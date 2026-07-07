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


def test_extract_maps_encryption_and_ip_fields():
    llm = FakeLLMProvider(json_responses=[{
        "trains_on_input": "no", "data_retention": "none",
        "data_residency": "canada", "sub_processors": "disclosed",
        "human_review": "yes", "encryption_standard": "strong",
        "ip_ownership": "customer", "extraction_confidence": 0.9,
    }])
    facts = extract_contract_facts(_terms(), llm)
    assert facts.encryption_standard == "strong"
    assert facts.ip_ownership == "customer"


def test_build_arp_generates_seven_criteria_rows():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(
        trains_on_input="yes", data_retention="indefinite", data_residency="us",
        sub_processors="undisclosed", human_review="no",
        encryption_standard="none", ip_ownership="vendor",
    ))
    assert len(arp.criteria) == 7
    assert all(c.origin == "rule" for c in arp.criteria)
    criteria_names = {c.criterion for c in arp.criteria}
    assert "Garanties contractuelles de non-divulgation" in criteria_names


def test_build_arp_flags_risky_facts_as_high_or_critical():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        data_retention="indefinite", sub_processors="undisclosed",
        human_review="no", encryption_standard="none", ip_ownership="vendor",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent in ("E", "C")
    assert by_criterion["Conservation des données"].inherent in ("E", "C")
    assert by_criterion["Révision humaine par le fournisseur"].inherent in ("E", "C")
    assert by_criterion["Chiffrement des données"].inherent in ("E", "C")
    assert by_criterion["Propriété intellectuelle du contenu généré"].inherent in ("E", "C")


def test_build_arp_flags_safe_facts_as_low_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        data_retention="none", sub_processors="disclosed",
        human_review="yes", encryption_standard="strong", ip_ownership="customer",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "F"
    assert by_criterion["Conservation des données"].inherent == "F"
    assert by_criterion["Révision humaine par le fournisseur"].inherent == "F"
    assert by_criterion["Chiffrement des données"].inherent == "F"
    assert by_criterion["Propriété intellectuelle du contenu généré"].inherent == "F"


def test_build_arp_flags_partial_encryption_as_risky():
    from policybot.models import ContractFacts
    facts = ContractFacts(encryption_standard="partial")
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Chiffrement des données"].inherent == "E"
