from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_mode_guess_returns_fragment_with_guessed_mode_checked(tmp_path):
    client = _client(tmp_path, json_responses=[{"mode_guess": "api", "confidence": 0.8}])
    resp = client.post("/wizard/mode-guess", data={"usage_description": "Intégré à notre CRM"})
    assert resp.status_code == 200
    assert 'value="api" checked' in resp.text
    assert "<!DOCTYPE" not in resp.text


def test_mode_guess_with_empty_description_defaults_to_prompt(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/mode-guess", data={"usage_description": ""})
    assert resp.status_code == 200
    assert 'value="prompt" checked' in resp.text


def test_suggest_usage_returns_fragment_with_new_checkboxes(tmp_path):
    client = _client(tmp_path, json_responses=[{"options": [
        {"label": "Analyse statistique interne", "description": ""},
    ]}])
    resp = client.post("/wizard/suggest/usage", data={"result_use_free_text": "pour des stats internes"})
    assert resp.status_code == 200
    assert "Analyse statistique interne" in resp.text
