from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")))
    return TestClient(create_app(itv))


def test_donnees_submit_renders_usage_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/donnees", data={
        "tool_name": "ChatGPT",
        "data_checked": ["Renseignements personnels", "Documents internes de travail"],
        "data_free_text": "notes de cours",
    })
    assert resp.status_code == 200
    assert "usage" in resp.text.lower()
    assert 'name="data_checked" value="Renseignements personnels"' in resp.text
    assert 'name="data_free_text" value="notes de cours"' in resp.text


def test_suggest_donnees_returns_fragment_with_new_checkboxes(tmp_path):
    client = _client(tmp_path, json_responses=[{"options": [
        {"label": "Renseignements personnels d'étudiants", "description": "Courriels, notes"},
    ]}])
    resp = client.post("/wizard/suggest/donnees", data={"data_free_text": "des courriels d'étudiants"})
    assert resp.status_code == 200
    assert "Renseignements personnels d'étudiants" in resp.text
    assert "<!DOCTYPE" not in resp.text


def test_suggest_donnees_with_empty_free_text_returns_no_options(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/suggest/donnees", data={"data_free_text": ""})
    assert resp.status_code == 200
    assert resp.text.strip() == ""
