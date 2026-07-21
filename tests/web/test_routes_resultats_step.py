from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")))
    return TestClient(create_app(itv))


def test_resultats_submit_renders_contexte_affaires_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/resultats", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "result_use_checked": "Publication",
    })
    assert resp.status_code == 200
    assert "contexte d'affaires" in resp.text.lower()
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="result_use_checked" value="Publication"' in resp.text


def test_resultats_submit_can_loop_back_to_add_another_usage(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/resultats", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info publique",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "result_use_checked": "Publication",
        "usage_action": "add_usage",
    })

    assert resp.status_code == 200
    assert "Tes donn" in resp.text
    assert "Usage 2" in resp.text
    assert 'name="saved_usages_json"' in resp.text
    assert 'name="usage_description" value="Chercher des informations publiques"' not in resp.text
