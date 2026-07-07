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


def test_home_page_renders_outil_step(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PolicyBot" in resp.text
    assert "outil" in resp.text.lower()


def test_static_files_are_served(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    resp = client.get("/static/htmx.min.js")
    assert resp.status_code == 200
