from datetime import date, timedelta
from policybot.models import (
    ArpRecord,
    ContractFacts,
    ContractOfferingIdentity,
    PreApprovedRecord,
)
from policybot.preapproved.store import PreApprovedStore


def _store(tmp_path):
    return PreApprovedStore(str(tmp_path / "pb.db"))


def test_save_and_get_arp(tmp_path):
    store = _store(tmp_path)
    arp = ArpRecord(tool_name="ChatGPT", iag_type="publique", contract_facts=ContractFacts())
    store.save_arp(arp)
    got = store.get_arp("ChatGPT")
    assert got is not None and got.tool_name == "ChatGPT"


def test_arp_cache_is_partitioned_by_contract_offering(tmp_path):
    store = _store(tmp_path)
    consumer = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="Plus",
        deployment_mode="public_saas", contract_type="consumer_terms",
    )
    enterprise = consumer.model_copy(update={
        "plan": "Enterprise", "contract_type": "institutional_agreement",
    })
    store.save_arp(ArpRecord(
        tool_name="ChatGPT", iag_type="publique", offering=consumer,
        contract_facts=ContractFacts(
            training_default="yes", opt_out_available="yes",
            opt_out_confirmed_enabled="unknown",
        ),
    ))
    store.save_arp(ArpRecord(
        tool_name="ChatGPT", iag_type="circuit_ferme", offering=enterprise,
        contract_facts=ContractFacts(training_default="no"),
    ))

    consumer_facts = store.get_arp(consumer).contract_facts
    assert consumer_facts.training_default == "yes"
    assert consumer_facts.opt_out_available == "yes"
    assert consumer_facts.opt_out_confirmed_enabled == "unknown"
    assert store.get_arp(enterprise).contract_facts.training_default == "no"


def test_legacy_cache_migration_never_confirms_an_available_opt_out():
    facts = ContractFacts.model_validate({
        "trains_on_input": "opt_out_available",
        "reentraining_opt_out": "yes",
        "human_review": "yes",
        "institutional_terms": "acceptable",
        "data_residency": "canada",
    })

    assert facts.training_default == "yes"
    assert facts.opt_out_available == "yes"
    assert facts.opt_out_confirmed_enabled == "unknown"
    assert facts.provider_human_access == "yes"
    assert facts.institutional_terms_available == "yes"
    assert facts.dpa_available == "unknown"
    assert facts.institutional_use_restricted == "no"
    assert facts.data_residency == "canada_outside_quebec"


def test_find_decision_matches_current(tmp_path):
    store = _store(tmp_path)
    rec = PreApprovedRecord(
        id="d1", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() + timedelta(days=30),
    )
    store.save_decision(rec)
    found = store.find_decision("Copilot", "Protégé A", "circuit_ferme")
    assert found is not None and found.id == "d1"


def test_find_decision_ignores_expired(tmp_path):
    store = _store(tmp_path)
    rec = PreApprovedRecord(
        id="d2", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() - timedelta(days=1),
    )
    store.save_decision(rec)
    assert store.find_decision("Copilot", "Protégé A", "circuit_ferme") is None


def test_find_decision_prefers_valid_over_expired_for_same_key(tmp_path):
    store = _store(tmp_path)
    # Save an expired decision with id "old"
    old_rec = PreApprovedRecord(
        id="old", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() - timedelta(days=1),
    )
    store.save_decision(old_rec)
    # Save a valid decision with id "new" for the same key
    new_rec = PreApprovedRecord(
        id="new", tool_name="Copilot", data_classification="Protégé A",
        iag_type="circuit_ferme", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() + timedelta(days=30),
    )
    store.save_decision(new_rec)
    # find_decision should return the valid one (new), not None
    found = store.find_decision("Copilot", "Protégé A", "circuit_ferme")
    assert found is not None and found.id == "new"


def test_find_decision_prefers_permanent_over_expired_for_same_key(tmp_path):
    store = _store(tmp_path)
    # Save an expired decision with id "expired-1"
    expired_rec = PreApprovedRecord(
        id="expired-1", tool_name="ChatGPT", data_classification="Protégé A",
        iag_type="publique", verdict="Autoriser", risk_level="Faible",
        expires_at=date.today() - timedelta(days=365),
    )
    store.save_decision(expired_rec)
    # Save a permanent decision (no expiry) with id "permanent-1" for the same key
    permanent_rec = PreApprovedRecord(
        id="permanent-1", tool_name="ChatGPT", data_classification="Protégé A",
        iag_type="publique", verdict="Autoriser", risk_level="Faible",
        expires_at=None,
    )
    store.save_decision(permanent_rec)
    # find_decision should return the permanent one, not None or the expired one
    found = store.find_decision("ChatGPT", "Protégé A", "publique")
    assert found is not None and found.id == "permanent-1"
