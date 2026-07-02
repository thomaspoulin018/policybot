from datetime import date, timedelta
from policybot.models import ArpRecord, ContractFacts, PreApprovedRecord
from policybot.preapproved.store import PreApprovedStore


def _store(tmp_path):
    return PreApprovedStore(str(tmp_path / "pb.db"))


def test_save_and_get_arp(tmp_path):
    store = _store(tmp_path)
    arp = ArpRecord(tool_name="ChatGPT", iag_type="publique", contract_facts=ContractFacts())
    store.save_arp(arp)
    got = store.get_arp("ChatGPT")
    assert got is not None and got.tool_name == "ChatGPT"


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
