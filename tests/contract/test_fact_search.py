import pytest

from policybot.contract.fact_search import (
    CONTRACT_FACT_NAMES,
    FACT_SEARCHES,
    load_fact_search_configs,
)


def test_repository_has_one_valid_exa_config_for_every_contract_fact():
    assert {config.fact for config in FACT_SEARCHES} == set(CONTRACT_FACT_NAMES)
    assert all(config.selection.strategy == "source_rank" for config in FACT_SEARCHES)
    assert all(config.selection.require_declared_source_url for config in FACT_SEARCHES)


def test_option_d_is_independently_configurable(tmp_path):
    source = next(config for config in FACT_SEARCHES if config.fact == "training_default")
    path = tmp_path / "training_default.yaml"
    payload = source.model_dump(by_alias=True)
    payload["selection"]["require_declared_source_url"] = False
    import yaml
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    loaded = load_fact_search_configs(tmp_path)

    assert loaded[0].selection.require_declared_source_url is False


def test_unknown_fact_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("version: 1\nfact: not_a_fact\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid fact-search config"):
        load_fact_search_configs(tmp_path)
