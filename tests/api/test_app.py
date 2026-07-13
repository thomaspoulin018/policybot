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


def test_assess_endpoint_unknown_tool_returns_422_with_question(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/assess", json={
        "request": {"numero": "IAG-2026-007"},
        "tool_name": "OutilInconnu",
        "usage_inputs": [{"description": "info interne", "data_description": "notes internes",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    })
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "unknown_tool"
    assert "question" in body



def test_report_pdf_endpoint_writes_and_returns_pdf(tmp_path, monkeypatch):
    def fake_write_pdf(state):
        path = tmp_path / "policybot-api.pdf"
        path.write_bytes(b"%PDF-1.4 fake policybot pdf")
        return path

    monkeypatch.setattr("policybot.api.app.write_pdf", fake_write_pdf)
    client = _client(tmp_path)
    state = client.post("/assess", json={
        "request": {"numero": "IAG-2026-006"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    }).json()
    resp = client.post("/report/pdf", json=state)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")

def test_report_docx_endpoint_writes_and_returns_docx(tmp_path, monkeypatch):
    def fake_write_docx(state):
        path = tmp_path / "policybot-api.docx"
        path.write_bytes(b"PK fake policybot docx")
        return path

    monkeypatch.setattr("policybot.api.app.write_docx", fake_write_docx)
    client = _client(tmp_path)
    state = client.post("/assess", json={
        "request": {"numero": "IAG-2026-008"},
        "tool_name": "ChatGPT",
        "usage_inputs": [{"description": "info publique", "data_description": "info publique",
                          "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    }).json()
    resp = client.post("/report/docx", json=state)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert resp.content.startswith(b"PK")

