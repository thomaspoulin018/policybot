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
