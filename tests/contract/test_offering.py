from datetime import date

from policybot.models import ContractOfferingIdentity


def test_offering_identity_key_covers_every_contract_dimension():
    base = ContractOfferingIdentity(
        vendor="OpenAI",
        product="ChatGPT",
        plan="Enterprise",
        deployment_mode="managed_saas",
        contract_type="institutional_agreement",
        contract_version="2026-01",
        jurisdiction="Québec",
        effective_date=date(2026, 1, 1),
    )

    assert base.cache_key() == base.model_copy().cache_key()
    for field, replacement in {
        "vendor": "Anthropic",
        "product": "Claude",
        "plan": "Edu",
        "deployment_mode": "public_saas",
        "contract_type": "consumer_terms",
        "contract_version": "2026-02",
        "jurisdiction": "Ontario",
        "effective_date": date(2026, 2, 1),
    }.items():
        assert base.model_copy(update={field: replacement}).cache_key() != base.cache_key()


def test_offering_identity_has_a_human_readable_label():
    offering = ContractOfferingIdentity(
        vendor="Microsoft",
        product="Copilot",
        plan="Microsoft 365 Entreprise",
        deployment_mode="managed_saas",
        contract_type="institutional_agreement",
        contract_version="DPA-2026",
        effective_date=date(2026, 3, 1),
    )

    label = offering.display_label()

    assert "Microsoft" in label
    assert "Copilot" in label
    assert "Microsoft 365 Entreprise" in label
    assert "DPA-2026" in label
    assert "2026-03-01" in label


def test_missing_search_identity_fields_treats_empty_and_unknown_as_incomplete():
    offering = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="",
        deployment_mode="unknown", contract_type="consumer_terms",
        contract_version="",
    )

    assert offering.missing_search_identity_fields() == (
        "plan", "deployment_mode", "contract_version",
    )
