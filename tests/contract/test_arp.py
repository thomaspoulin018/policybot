from policybot.contract.arp import build_arp, extract_contract_facts
from policybot.contract.evidence import ContractEvidence
from policybot.models import ContractFacts, FactEvidence
from tests.helpers.arp_fixtures import exa_evidence


def test_extract_assembles_anchored_exa_facts_without_an_llm():
    facts = extract_contract_facts(exa_evidence(
        training_default="no", data_residency="quebec", encryption_standard="strong",
    ))

    assert facts.training_default == "no"
    assert facts.data_residency == "quebec"
    assert facts.evidence["training_default"].outcome == "accepted"
    assert facts.extraction_confidence == 0.16


def test_extract_keeps_missing_facts_conservatively_unknown():
    facts = extract_contract_facts(ContractEvidence(facts={
        "training_default": FactEvidence(value="no", outcome="accepted"),
    }))

    assert facts.training_default == "no"
    assert facts.data_residency == "unknown"
    assert facts.evidence["data_residency"].outcome == "evidence_missing"


def test_build_arp_generates_thirteen_deterministic_criteria():
    arp = build_arp("ChatGPT", "publique", ContractFacts(
        training_default="no", data_residency="quebec", applicable_law="quebec_canada",
        foreign_vendor_dependency="no", contract_prohibits_reuse="yes",
        encryption_standard="strong", authentication_support="sso_mfa",
        audit_logging="prompt_output_accessible", incident_response="documented_with_notice",
        ip_ownership="customer", institutional_terms_available="yes", dpa_available="yes",
        quebec_higher_ed_license="yes",
    ))

    assert arp.schema_version == 4
    assert len(arp.criteria) == 13
    assert all(factor.origin == "rule" for factor in arp.criteria)
    assert all(factor.residual is None for factor in arp.criteria)


def test_build_arp_defaults_to_conservative_risk_on_unknown():
    arp = build_arp("ToolX", "publique", ContractFacts())
    by_criterion = {criterion.criterion: criterion for criterion in arp.criteria}
    assert by_criterion["Juridiction applicable"].inherent == "E"
    assert by_criterion["Chiffrement des données"].inherent == "E"
