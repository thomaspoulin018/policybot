from policybot.contract.offering import build_offering_identity
from policybot.models import ArpRecord, CriterionFinding
from policybot.contract.cache import ArpCache


def test_arp_v2_round_trip_is_keyed_by_offering(tmp_path):
    store = ArpCache(str(tmp_path / "cache.db"))
    offering = build_offering_identity(
        "ToolX", "publique", vendor="Vendor", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
    )
    record = ArpRecord(
        tool_name="ToolX",
        iag_type="publique",
        offering=offering,
        findings=[CriterionFinding(
            id="A01", partie="A", category="Catégorie", criterion="Critère",
            question="Question ?", answer="Réponse.",
        )],
        schema_version=2,
    )
    store.save_arp(record)
    loaded = store.get_arp(offering)
    assert loaded is not None
    assert loaded.schema_version == 2
    assert loaded.findings[0].answer == "Réponse."


def test_legacy_cache_payload_is_ignored(tmp_path):
    store = ArpCache(str(tmp_path / "cache.db"))
    offering = build_offering_identity(
        "ToolX", "publique", vendor="Vendor", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
    )
    store._db.execute(
        "INSERT INTO arp_offering VALUES (?, ?, ?)",
        (offering.cache_key(), "toolx", '{"tool_name":"ToolX","schema_version":1}'),
    )
    store._db.commit()
    assert store.get_arp(offering) is None
