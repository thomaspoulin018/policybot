from fastapi.testclient import TestClient

from policybot.api.app import create_app
from policybot.interview.orchestrator import Interview
from policybot.llm.fake import FakeLLMProvider
from policybot.models import CriterionCitation, CriterionFinding
from policybot.preapproved.store import PreApprovedStore


def _classification():
    return {
        "already_public": True,
        "contains_personal_info": False,
        "strategic_sensitive": False,
        "internal_nonpublic": False,
        "highly_sensitive_secret": False,
        "confidence": 0.9,
    }


def _finding():
    return CriterionFinding(
        id="A01", partie="A", category="Catégorie", criterion="Localisation",
        question="Où ?", answer="Au Canada.", inherent_risk="M",
        justification="À confirmer.", cost_dollars=0.02,
        citations=[CriterionCitation(
            url="https://vendor.test/data",
            text="Data is hosted in Canada.",
            anchored=True,
            deep_link="https://vendor.test/data#:~:text=Data%20is%20hosted%20in%20Canada.",
        )],
    )


def _client(tmp_path, responses=None):
    interview = Interview(
        llm=FakeLLMProvider(json_responses=responses or []),
        store=PreApprovedStore(str(tmp_path / "pb.db")),
        exa_search=lambda tool_name, offering: [_finding()],
    )
    return TestClient(create_app(interview))


def test_final_submit_renders_sourced_findings_without_automatic_authorization(tmp_path):
    client = _client(tmp_path, [_classification()])
    response = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'information publique",
        "mode": "prompt",
    })
    assert response.status_code == 200
    assert "Constats sourcés par critère" in response.text
    assert "Data is hosted in Canada." in response.text
    assert "0.0200" in response.text
    assert "ne calcule aucune autorisation" in response.text


def test_final_submit_renders_error_screen_when_classification_fails(tmp_path):
    response = _client(tmp_path).post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher",
        "mode": "prompt",
    })
    assert response.status_code == 502
