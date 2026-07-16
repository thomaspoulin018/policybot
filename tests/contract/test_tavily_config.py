import yaml
from policybot.models import ContractOfferingIdentity

from policybot.contract.families import FACT_FAMILIES
from policybot.contract.tavily import (
    CONFIG_SCHEMA_VERSION,
    build_contract_search_config,
    ensure_contract_search_config,
    load_contract_search_config,
)


def test_config_declares_one_entry_per_family():
    config = build_contract_search_config("ChatGPT")

    assert config["schema_version"] == CONFIG_SCHEMA_VERSION
    assert config["tool"]["vendor"] == "OpenAI"
    assert config["search_defaults"]["include_domains"] == ["openai.com"]
    assert [family["name"] for family in config["families"]] == [
        family.name for family in FACT_FAMILIES
    ]
    assert all("ChatGPT" in family["query"] for family in config["families"])
    assert all("OpenAI" in family["query"] for family in config["families"])

    fields = [f for family in config["families"] for f in family["fields"]]
    assert len(fields) == 16
    trains = next(f for f in fields if f["name"] == "trains_on_input")
    assert trains["allowed_values"] == ["yes", "no", "opt_out_available", "unknown"]


def test_unknown_tool_falls_back_to_its_own_name_as_vendor():
    config = build_contract_search_config("OutilInconnu")

    assert config["tool"]["vendor"] == ""
    assert config["search_defaults"]["include_domains"] == []
    assert all("OutilInconnu" in family["query"] for family in config["families"])


def test_offering_identity_scopes_queries_policy_and_config_filename(tmp_path):
    offering = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
        contract_version="2026-07",
    )

    config = build_contract_search_config("ChatGPT", offering)
    path = ensure_contract_search_config(
        "ChatGPT", config_dir=tmp_path, offering=offering,
    )

    assert config["offering"]["plan"] == "Enterprise"
    assert all("Enterprise" in family["query"] for family in config["families"])
    assert "https://openai.com/policies/business-terms" in (
        config["source_policy"]["priority_urls"]
    )
    assert "https://openai.com/policies/terms-of-use" not in (
        config["source_policy"]["priority_urls"]
    )
    assert "community" in " ".join(config["source_policy"]["excluded_path_patterns"])
    assert path.name.startswith("chatgpt-")
    assert path.name != "chatgpt.yaml"


def test_ensure_config_writes_once_then_reuses(tmp_path):
    path = ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path)

    assert path.name == "chatgpt-pro.yaml"
    loaded = load_contract_search_config(path)
    assert len(loaded["families"]) == len(FACT_FAMILIES)

    path.write_text(
        yaml.safe_dump({"schema_version": CONFIG_SCHEMA_VERSION, "families": []}),
        encoding="utf-8",
    )
    assert ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path) == path
    assert load_contract_search_config(path)["families"] == []


def test_ensure_config_regenerates_a_stale_schema(tmp_path):
    path = tmp_path / "chatgpt.yaml"
    path.write_text(
        yaml.safe_dump({"tool": {"name": "ChatGPT"}, "fields": [{"name": "trains_on_input"}]}),
        encoding="utf-8",
    )

    ensure_contract_search_config("ChatGPT", config_dir=tmp_path)
    regenerated = load_contract_search_config(path)

    assert regenerated["schema_version"] == CONFIG_SCHEMA_VERSION
    assert len(regenerated["families"]) == len(FACT_FAMILIES)
    assert "fields" not in regenerated


def test_load_config_rejects_a_config_without_families(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("tool:\n  name: X\n", encoding="utf-8")

    try:
        load_contract_search_config(path)
    except ValueError as exc:
        assert "families" in str(exc)
    else:
        raise AssertionError("load_contract_search_config should reject a config without families")
