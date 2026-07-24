from policybot.contract.criteres import CRITERIA_SEARCH_BY_ID
from policybot.contract.exa import collect_criteria_from_exa
from policybot.contract.offering import build_offering_identity


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if self.error:
            raise self.error
        return self.response


def _response(risk="M"):
    page = "Customer content is encrypted at rest and in transit."
    quote = "encrypted at rest and in transit"
    return {
        "output": {
            "content": {
                "answer": "Les données sont chiffrées en transit et au repos.",
                "inherent_risk": risk,
                "justification": "Le fournisseur publie des garanties techniques.",
            }
        },
        "costDollars": {"total": 0.031},
        "results": [{
            "url": "https://vendor.test/security",
            "title": "Security",
            "text": page,
            "summary": {
                "answer": "Oui.",
                "citation": quote,
                "begin": page.index(quote),
                "end": page.index(quote) + len(quote),
            },
        }],
    }


def _offering():
    return build_offering_identity(
        "ToolX", "publique", vendor="Vendor", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
    )


def test_structured_output_citation_and_cost_are_parsed():
    definition = CRITERIA_SEARCH_BY_ID["A07"]
    client = FakeClient(_response())
    findings = collect_criteria_from_exa(
        "ToolX", _offering(), client, definitions=[definition], max_workers=1,
    )
    finding = findings[0]
    assert finding.inherent_risk == "M"
    assert finding.cost_dollars == 0.031
    assert finding.citations[0].anchored is True
    assert client.calls[0][1]["output_schema"]["type"] == "object"
    assert "summary" in client.calls[0][1]["contents"]
    assert "Question" in client.calls[0][0]


def test_invalid_risk_is_not_invented():
    finding = collect_criteria_from_exa(
        "ToolX", _offering(), FakeClient(_response("Critique")),
        definitions=[CRITERIA_SEARCH_BY_ID["A07"]], max_workers=1,
    )[0]
    assert finding.inherent_risk is None


def test_failure_is_isolated_to_its_criterion():
    definition = CRITERIA_SEARCH_BY_ID["A07"]
    finding = collect_criteria_from_exa(
        "ToolX", _offering(), FakeClient(error=RuntimeError("offline")),
        definitions=[definition], max_workers=1,
    )[0]
    assert finding.id == "A07"
    assert finding.outcome == "search_failed"
