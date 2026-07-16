from datetime import date
from policybot.llm.fake import FakeLLMProvider
from policybot.contract.fetcher import FetchedTerms
from policybot.contract.evidence import ContractEvidence
from policybot.contract.arp import extract_contract_facts, build_arp
from tests.helpers.arp_fixtures import DEFAULT_EVIDENCE, arp_extraction_responses


def _terms():
    return FetchedTerms(text=DEFAULT_EVIDENCE, source_url="http://x", fetched_at=date.today())


def test_extract_maps_llm_output_to_contractfacts():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        "http://x",
        trains_on_input="yes", data_retention="indefinite",
        data_residency="us", sub_processors="undisclosed",
        human_review="no",
    ))
    facts = extract_contract_facts(ContractEvidence.from_single(_terms()), llm)
    assert facts.trains_on_input == "yes"
    assert facts.data_residency == "us"
    assert facts.source_url == "http://x"
    assert facts.extraction_confidence == 0.9


def test_extract_prompt_lists_required_contract_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(trains_on_input="yes"))

    extract_contract_facts(ContractEvidence.from_single(_terms()), llm)

    all_prompts = "\n".join(user_prompt for _, user_prompt in llm.calls)
    assert "Required JSON keys" in all_prompts
    assert "trains_on_input: yes | no | opt_out_available | unknown" in all_prompts
    assert "reentraining_opt_out: yes | no | unknown" in all_prompts
    assert "authentication_support: sso_mfa | partial | none | unknown" in all_prompts
    assert "audit_logging: prompt_output_accessible | access_logs_only | none | unknown" in all_prompts
    assert "quebec_higher_ed_license: yes | no | unknown" in all_prompts
    assert "incident_response: documented_with_notice | documented_no_notice | none | unknown" in all_prompts


def test_extract_prompt_includes_relevant_late_evidence():
    late_terms = FetchedTerms(
        text=(
            "Source extraite Tavily\nURL: https://example.test/first\n"
            + "navigation only " * 1200
            + "\n\n---\n\n"
            + "Source extraite Tavily\nURL: https://example.test/terms\n"
            + "The governing law is the laws of California."
        ),
        source_url="https://example.test/first",
        fetched_at=date.today(),
    )
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(applicable_law="foreign"))

    extract_contract_facts(ContractEvidence.from_single(late_terms), llm)

    assert any(
        "governing law is the laws of California" in user_prompt
        for _, user_prompt in llm.calls
    )


def test_build_arp_flags_training_as_high_risk():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(trains_on_input="yes"))
    training = [c for c in arp.criteria if "entraîn" in c.criterion.lower()]
    assert training and training[0].inherent == "E"
    assert all(c.origin == "rule" for c in arp.criteria)
    assert arp.iag_type == "publique"
    assert arp.schema_version == 2


def test_extract_maps_encryption_and_ip_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        trains_on_input="no", data_retention="none",
        data_residency="canada", sub_processors="disclosed",
        human_review="yes", encryption_standard="strong",
        ip_ownership="customer",
    ))
    facts = extract_contract_facts(ContractEvidence.from_single(_terms()), llm)
    assert facts.encryption_standard == "strong"
    assert facts.ip_ownership == "customer"


def test_extract_maps_new_sovereignty_and_security_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        applicable_law="foreign", foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no", reentraining_opt_out="no",
    ))
    facts = extract_contract_facts(ContractEvidence.from_single(_terms()), llm)
    assert facts.applicable_law == "foreign"
    assert facts.foreign_vendor_dependency == "yes"
    assert facts.contract_prohibits_reuse == "no"
    assert facts.reentraining_opt_out == "no"


def test_extract_maps_institutional_security_fields():
    llm = FakeLLMProvider(json_responses=arp_extraction_responses(
        authentication_support="sso_mfa",
        audit_logging="prompt_output_accessible",
        institutional_terms="acceptable",
        quebec_higher_ed_license="yes",
        incident_response="documented_with_notice",
    ))

    facts = extract_contract_facts(ContractEvidence.from_single(_terms()), llm)

    assert facts.authentication_support == "sso_mfa"
    assert facts.audit_logging == "prompt_output_accessible"
    assert facts.institutional_terms == "acceptable"
    assert facts.quebec_higher_ed_license == "yes"
    assert facts.incident_response == "documented_with_notice"

def test_build_arp_generates_eight_criteria_rows():
    from policybot.models import ContractFacts
    arp = build_arp("ChatGPT", "publique", ContractFacts(
        trains_on_input="yes", data_residency="us",
        applicable_law="foreign", foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no", encryption_standard="none",
        reentraining_opt_out="no", ip_ownership="vendor",
    ))
    assert len(arp.criteria) == 8
    assert all(c.origin == "rule" for c in arp.criteria)
    criteria_names = {c.criterion for c in arp.criteria}
    assert criteria_names == {
        "Localisation des serveurs", "Juridiction applicable",
        "Dépendance technologique",
        "Données soumises utilisées pour entraînement du modèle",
        "Garanties contractuelles de non-divulgation",
        "Chiffrement des données", "Utilisation des entrées et des sorties",
        "Propriété intellectuelle",
    }


def test_build_arp_flags_risky_facts_as_high_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        applicable_law="foreign", foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no", encryption_standard="none",
        reentraining_opt_out="no", ip_ownership="vendor",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "E"
    assert by_criterion["Dépendance technologique"].inherent == "E"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "E"
    assert by_criterion["Chiffrement des données"].inherent == "E"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "E"
    assert by_criterion["Propriété intellectuelle"].inherent == "E"


def test_build_arp_flags_safe_facts_as_low_risk():
    from policybot.models import ContractFacts
    facts = ContractFacts(
        applicable_law="quebec_canada", foreign_vendor_dependency="no",
        contract_prohibits_reuse="yes", encryption_standard="strong",
        reentraining_opt_out="yes", ip_ownership="customer",
    )
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "F"
    assert by_criterion["Dépendance technologique"].inherent == "F"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "F"
    assert by_criterion["Chiffrement des données"].inherent == "F"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "F"
    assert by_criterion["Propriété intellectuelle"].inherent == "F"


def test_build_arp_defaults_to_conservative_risk_on_unknown():
    from policybot.models import ContractFacts
    arp = build_arp("ToolX", "publique", ContractFacts())
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "E"
    assert by_criterion["Dépendance technologique"].inherent == "E"
    assert by_criterion["Garanties contractuelles de non-divulgation"].inherent == "E"
    assert by_criterion["Utilisation des entrées et des sorties"].inherent == "E"


def test_build_arp_flags_partial_encryption_as_risky():
    from policybot.models import ContractFacts
    facts = ContractFacts(encryption_standard="partial")
    arp = build_arp("ToolX", "publique", facts)
    by_criterion = {c.criterion: c for c in arp.criteria}
    assert by_criterion["Chiffrement des données"].inherent == "E"
