import policybot.contract.exa as exa_module
from policybot.contract.evidence import ContractEvidence
from policybot.contract.exa import (
    collect_evidence_from_exa,
    estimate_search_cost_usd,
    search_contract_facts_with_exa,
)
from policybot.contract.fact_search import FACT_SEARCH_BY_NAME, FactSelectionConfig
from policybot.contract.offering import build_offering_identity
from policybot.tracing import collect_llm_usage


class FakeExaClient:
    """Small deterministic Exa fake; responses are served in call order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return self.responses.pop(0)


def _definition(*, option_d: bool):
    base = FACT_SEARCH_BY_NAME["training_default"]
    return base.model_copy(update={
        "selection": FactSelectionConfig(
            strategy="source_rank", require_declared_source_url=option_d,
        ),
    })


def _result(url, value, quote, *, declared_url=None, score=0.5):
    return {
        "url": url,
        "score": score,
        "text": quote,
        "summary": {
            "value": value,
            "quote": quote,
            "source_url": declared_url or url,
        },
    }


def _collect(definition, response):
    offering = _complete_offering()
    return collect_evidence_from_exa(
        "ToolX", "Vendor", offering, FakeExaClient([response]),
        definitions=(definition,), max_workers=1,
    )


def _complete_offering(*, jurisdiction="Québec"):
    return build_offering_identity(
        "ToolX", "publique", vendor="Vendor", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
        contract_version="DPA-2026", jurisdiction=jurisdiction,
    )


def test_option_a_prefers_contractual_source_before_exa_relevance():
    contractual_quote = "The contractual terms prohibit model training by default."
    technical_quote = "The technical page says training is enabled by default."
    evidence = _collect(_definition(option_d=True), {"results": [
        _result("https://vendor.test/docs/security", "yes", technical_quote, score=0.99),
        _result("https://vendor.test/legal/terms", "no", contractual_quote, score=0.01),
    ]})

    proof = evidence.facts["training_default"]
    assert proof.value == "no"
    assert proof.source_url == "https://vendor.test/legal/terms"
    assert proof.outcome == "accepted"


def test_option_d_rejects_declared_url_that_differs_from_processed_result():
    quote = "The contractual terms prohibit model training by default."
    evidence = _collect(_definition(option_d=True), {"results": [
        _result(
            "https://vendor.test/legal/terms", "no", quote,
            declared_url="https://elsewhere.test/other",
        ),
    ]})

    proof = evidence.facts["training_default"]
    assert proof.value == "unknown"
    assert proof.outcome == "declared_source_url_rejected"


def test_option_d_can_be_disabled_in_the_fact_yaml_policy():
    quote = "The contractual terms prohibit model training by default."
    evidence = _collect(_definition(option_d=False), {"results": [
        _result(
            "https://vendor.test/legal/terms", "no", quote,
            declared_url="https://elsewhere.test/other",
        ),
    ]})

    proof = evidence.facts["training_default"]
    assert proof.value == "no"
    assert proof.source_url == "https://vendor.test/legal/terms"
    assert proof.declared_source_url == "https://elsewhere.test/other"


def test_each_fact_collection_failure_is_isolated():
    class FailingExa:
        def search(self, query, **kwargs):
            raise RuntimeError("quota")

    offering = _complete_offering()
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", offering, FailingExa(),
        definitions=(_definition(option_d=True),), max_workers=1,
    )

    assert evidence.facts["training_default"].outcome == "collection_failure"
    assert evidence.failed_facts == ("training_default",)


class _FlakyExa:
    """Raises the queued errors in order, then serves ``response``."""

    def __init__(self, errors, response):
        self.errors = list(errors)
        self.response = response
        self.calls = 0

    def search(self, query, **kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.response


def _good_response():
    return {"results": [_result(
        "https://vendor.test/legal/terms", "no",
        "The contractual terms prohibit model training by default.",
    )]}


def test_transient_search_error_is_retried_until_it_succeeds(monkeypatch):
    monkeypatch.setattr(exa_module, "_sleep_before_retry", lambda attempt: None)
    # ConnectionResetError is the exact failure seen under concurrent load.
    client = _FlakyExa(
        [ConnectionResetError(10054, "forcibly closed"), OSError("SSL EOF")],
        _good_response(),
    )
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", _complete_offering(), client,
        definitions=(_definition(option_d=True),), max_workers=1, max_attempts=3,
    )

    assert client.calls == 3
    assert evidence.failed_facts == ()
    assert evidence.facts["training_default"].value == "no"


def test_retries_are_bounded_then_the_fact_degrades_alone(monkeypatch):
    monkeypatch.setattr(exa_module, "_sleep_before_retry", lambda attempt: None)
    client = _FlakyExa(
        [ConnectionResetError(10054, "forcibly closed")] * 5, _good_response(),
    )
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", _complete_offering(), client,
        definitions=(_definition(option_d=True),), max_workers=1, max_attempts=3,
    )

    assert client.calls == 3
    assert evidence.facts["training_default"].outcome == "collection_failure"
    assert evidence.failed_facts == ("training_default",)


def test_permanent_http_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(exa_module, "_sleep_before_retry", lambda attempt: None)
    # exa_py wraps a non-2xx response as ValueError; a 400 will never recover.
    client = _FlakyExa(
        [ValueError("Request failed with status code 400: bad request")] * 5,
        _good_response(),
    )
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", _complete_offering(), client,
        definitions=(_definition(option_d=True),), max_workers=1, max_attempts=3,
    )

    assert client.calls == 1
    assert evidence.facts["training_default"].outcome == "collection_failure"


def test_rate_limited_http_error_is_retried(monkeypatch):
    monkeypatch.setattr(exa_module, "_sleep_before_retry", lambda attempt: None)
    client = _FlakyExa(
        [ValueError("Request failed with status code 429: slow down")],
        _good_response(),
    )
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", _complete_offering(), client,
        definitions=(_definition(option_d=True),), max_workers=1, max_attempts=3,
    )

    assert client.calls == 2
    assert evidence.facts["training_default"].value == "no"


def test_incomplete_offering_identity_is_rendered_as_unknown_and_searched():
    quote = "The contractual terms prohibit model training by default."
    client = FakeExaClient([{"results": [
        _result("https://vendor.test/legal/terms", "no", quote),
    ]}])
    offering = build_offering_identity(
        "ToolX", "publique", vendor="Vendor", plan="Enterprise",
        contract_version="",
    )

    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", offering, client,
        definitions=(_definition(option_d=True),), max_workers=1,
    )

    proof = evidence.facts["training_default"]
    assert len(client.calls) == 1
    assert "unknown" in client.calls[0][0]
    assert proof.value == "no"


def test_missing_jurisdiction_is_rendered_as_unknown_without_skipping_its_fact():
    client = FakeExaClient([
        {"results": [_result(
            "https://vendor.test/legal/terms", "no",
            "The contractual terms prohibit model training by default.",
        )]},
        {"results": [_result(
            "https://vendor.test/legal/terms", "quebec_canada",
            "The governing law is Quebec.",
        )]},
    ])
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", _complete_offering(jurisdiction=""), client,
        definitions=(
            FACT_SEARCH_BY_NAME["training_default"],
            FACT_SEARCH_BY_NAME["applicable_law"],
        ),
        max_workers=1,
    )

    assert len(client.calls) == 2
    assert client.calls[1][0].startswith("unknown Enterprise")
    assert evidence.facts["training_default"].value == "no"
    assert evidence.facts["applicable_law"].value == "quebec_canada"


def test_exa_search_cost_is_added_to_the_run_summary():
    definition = _definition(option_d=True)
    quote = "The contractual terms prohibit model training by default."
    with collect_llm_usage("exa-cost") as usage:
        _collect(definition, {"results": [
            _result("https://vendor.test/legal/terms", "no", quote),
        ]})

    assert estimate_search_cost_usd(definition) == 0.012
    assert usage.as_dict()["exa_search_calls"] == 1
    # No costDollars in the stub response ⇒ public-rate estimate fallback.
    assert usage.as_dict()["exa_reported_search_calls"] == 0
    assert usage.as_dict()["exa_estimated_cost_usd"] == 0.012
    assert usage.as_dict()["total_cost_usd"] == 0.012


class _CostDollars:
    """Mimics exa_py's SearchResponse.cost_dollars dataclass."""

    def __init__(self, total):
        self.total = total


def test_exa_reported_cost_from_object_is_used_instead_of_estimate():
    definition = _definition(option_d=True)
    quote = "The contractual terms prohibit model training by default."
    response = {"results": [_result("https://vendor.test/legal/terms", "no", quote)]}
    # A SearchResponse object exposes cost_dollars; our fake reuses a mapping
    # plus the attribute the real client would carry.
    response["cost_dollars"] = _CostDollars(total=0.0031)
    with collect_llm_usage("exa-reported-cost") as usage:
        _collect(definition, response)

    assert usage.as_dict()["exa_reported_search_calls"] == 1
    assert usage.as_dict()["exa_priced_search_calls"] == 1
    # Exa's reported total wins over the 0.012 public-rate estimate.
    assert usage.as_dict()["exa_estimated_cost_usd"] == 0.0031
    assert usage.as_dict()["total_cost_usd"] == 0.0031


def test_exa_reported_cost_from_raw_costdollars_mapping_is_used():
    definition = _definition(option_d=True)
    quote = "The contractual terms prohibit model training by default."
    response = {
        "results": [_result("https://vendor.test/legal/terms", "no", quote)],
        "costDollars": {"total": 0.0042, "search": {"neural": 0.004}},
    }
    with collect_llm_usage("exa-reported-cost-dict") as usage:
        _collect(definition, response)

    assert usage.as_dict()["exa_reported_search_calls"] == 1
    assert usage.as_dict()["exa_estimated_cost_usd"] == 0.0042


def test_deep_search_mode_can_be_selected_with_an_environment_option(monkeypatch):
    definition = _definition(option_d=True)
    quote = "The contractual terms prohibit model training by default."
    client = FakeExaClient([{"results": [
        _result("https://vendor.test/legal/terms", "no", quote),
    ]}])
    monkeypatch.setenv("POLICYBOT_EXA_SEARCH_TYPE", "deep")

    evidence = search_contract_facts_with_exa(
        "ToolX",
        offering=_complete_offering(),
        client=client,
        definitions=(definition,),
        max_workers=1,
    )

    assert evidence is not None
    assert evidence.facts["training_default"].value == "no"
    assert client.calls[0][1]["type"] == "deep"
    assert estimate_search_cost_usd(definition, search_type="deep") == 0.017
