from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_residency": "canada", "extraction_confidence": 0.9},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_assess_endpoint_returns_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/assess", json={
        "request": {"numero": "IAG-2026-004"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_global"]["recommendation"] == "Autoriser"


def test_report_endpoint_returns_html(tmp_path):
    client = _client(tmp_path)
    state = client.post("/assess", json={
        "request": {"numero": "IAG-2026-005"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    }).json()
    resp = client.post("/report", json=state)
    assert resp.status_code == 200
    assert "PolicyBot" in resp.text
    assert "IAG-2026-005" in resp.text
