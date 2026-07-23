import pytest

from policybot.contract.fact_search import (
    CONTRACT_FACT_NAMES,
    FACT_SEARCHES,
    load_fact_search_configs,
)


def test_repository_has_one_valid_exa_config_for_every_contract_fact():
    assert {config.fact for config in FACT_SEARCHES} == set(CONTRACT_FACT_NAMES)
    assert all(config.selection.strategy == "source_rank" for config in FACT_SEARCHES)
    assert all(not config.selection.require_declared_source_url for config in FACT_SEARCHES)


def test_repository_queries_begin_with_the_assessed_offering_identity():
    offer_prefix = "{plan} {deployment_mode} {contract_type} {contract_version}"
    for config in FACT_SEARCHES:
        expected = (
            "{jurisdiction} " + offer_prefix
            if config.fact == "applicable_law" else offer_prefix
        )
        assert config.exa.query.startswith(expected)


def test_summary_queries_require_a_verbatim_continuous_quote_without_ellipsis():
    instruction = (
        "Return a short, verbatim, continuous quote copied exactly from the "
        "returned page text; do not use ellipses."
    )
    assert all(instruction in config.exa.contents.summary.query for config in FACT_SEARCHES)


def test_only_legal_page_searches_request_the_larger_page_text_budget():
    legal_page_facts = {
        "applicable_law",
        "contract_prohibits_reuse",
        "data_residency",
        "data_retention",
        "dpa_available",
        "incident_response",
        "institutional_terms_available",
        "institutional_use_restricted",
        "ip_ownership",
        "opt_out_available",
        "opt_out_confirmed_enabled",
        "provider_human_access",
        "quebec_higher_ed_license",
        "sub_processors",
        "training_default",
    }
    for config in FACT_SEARCHES:
        expected = 24_000 if config.fact in legal_page_facts else 8_000
        assert config.exa.contents.text.max_characters == expected


def test_option_d_is_independently_configurable(tmp_path):
    source = next(config for config in FACT_SEARCHES if config.fact == "training_default")
    path = tmp_path / "training_default.yaml"
    payload = source.model_dump(by_alias=True)
    payload["selection"]["require_declared_source_url"] = False
    import yaml
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    loaded = load_fact_search_configs(tmp_path)

    assert loaded[0].selection.require_declared_source_url is False


def test_deep_exa_search_type_is_accepted(tmp_path):
    source = next(config for config in FACT_SEARCHES if config.fact == "training_default")
    payload = source.model_dump(by_alias=True)
    payload["exa"]["type"] = "deep"
    import yaml
    path = tmp_path / "training_default.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")

    loaded = load_fact_search_configs(tmp_path)

    assert loaded[0].exa.type == "deep"


def test_unknown_fact_is_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("version: 1\nfact: not_a_fact\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid fact-search config"):
        load_fact_search_configs(tmp_path)


def test_query_renders_complete_offering_identity_at_its_start():
    config = next(item for item in FACT_SEARCHES if item.fact == "training_default")

    rendered = config.render(
        tool="ChatGPT", vendor="OpenAI", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
        contract_version="DPA-2026", jurisdiction="Québec",
    )

    assert rendered.query.startswith(
        "Enterprise managed_saas institutional_agreement DPA-2026 ChatGPT OpenAI"
    )


def test_jurisdiction_placeholder_is_available_for_applicable_law():
    config = next(item for item in FACT_SEARCHES if item.fact == "applicable_law")
    rendered = config.render(
        tool="ChatGPT", vendor="OpenAI", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
        contract_version="DPA-2026", jurisdiction="Québec",
    )

    assert rendered.query.startswith("Québec Enterprise managed_saas")


def test_unknown_query_placeholder_is_rejected_when_loading_config(tmp_path):
    source = next(config for config in FACT_SEARCHES if config.fact == "training_default")
    payload = source.model_dump(by_alias=True)
    payload["exa"]["query"] = "{tool} {vendor} {plan} {deployment_mode} {contract_type} {contract_version} {region} terms"
    import yaml
    (tmp_path / "training_default.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unsupported placeholder"):
        load_fact_search_configs(tmp_path)
