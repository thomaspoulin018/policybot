from policybot.contract.evidence import ContractEvidence
from policybot.contract.exa import collect_evidence_from_exa, estimate_search_cost_usd
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
    offering = build_offering_identity("ToolX", "publique", vendor="Vendor")
    return collect_evidence_from_exa(
        "ToolX", "Vendor", offering, FakeExaClient([response]),
        definitions=(definition,), max_workers=1,
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

    offering = build_offering_identity("ToolX", "publique", vendor="Vendor")
    evidence = collect_evidence_from_exa(
        "ToolX", "Vendor", offering, FailingExa(),
        definitions=(_definition(option_d=True),), max_workers=1,
    )

    assert evidence.facts["training_default"].outcome == "collection_failure"
    assert evidence.failed_facts == ("training_default",)


def test_exa_search_cost_is_added_to_the_run_summary():
    definition = _definition(option_d=True)
    quote = "The contractual terms prohibit model training by default."
    with collect_llm_usage("exa-cost") as usage:
        _collect(definition, {"results": [
            _result("https://vendor.test/legal/terms", "no", quote),
        ]})

    assert estimate_search_cost_usd(definition) == 0.012
    assert usage.as_dict()["exa_search_calls"] == 1
    assert usage.as_dict()["exa_estimated_cost_usd"] == 0.012
    assert usage.as_dict()["total_cost_usd"] == 0.012
