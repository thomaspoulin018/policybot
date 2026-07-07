# tests/web/test_routes_resultat.py
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


def test_final_submit_renders_report_on_success(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
    ])
    resp = client.post("/wizard/usage", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Rapport de recommandation" in resp.text
    assert "Autoriser" in resp.text


def test_golden_scenario_chatgpt_protege_b_is_refused(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": False, "contains_personal_info": False,
         "strategic_sensitive": True, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "yes", "data_residency": "us", "extraction_confidence": 0.9},
    ])
    resp = client.post("/wizard/usage", data={
        "tool_name": "ChatGPT",
        "data_checked": "Données stratégiques / confidentielles",
        "usage_description": "Analyser des chiffres financiers internes",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Refuser" in resp.text


def test_final_submit_renders_error_screen_when_assess_fails(tmp_path):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    resp = client.post("/wizard/usage", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })
    assert resp.status_code == 502
    assert "bloqué" in resp.text.lower()


def test_final_submit_logs_exception_when_assess_fails(tmp_path, caplog):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    with caplog.at_level("ERROR", logger="policybot.web.routes"):
        resp = client.post("/wizard/usage", data={
            "tool_name": "ChatGPT",
            "data_checked": "Info déjà publique",
            "usage_description": "Chercher de l'info publique",
            "mode": "prompt",
        })
    assert resp.status_code == 502
    assert any("assess failed" in record.message for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)
