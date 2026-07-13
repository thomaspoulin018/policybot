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


def test_known_tool_skips_straight_to_profil_utilisateurs_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil", data={
        "tool_name": "ChatGPT", "tool_name_other": "", "version_plan_tarifaire": "Plan Plus",
    })
    assert resp.status_code == 200
    assert "profil" in resp.text.lower()
    assert 'value="ChatGPT"' in resp.text
    assert 'name="version_plan_tarifaire" value="Plan Plus"' in resp.text


def test_unknown_tool_renders_guided_fallback_with_llm_guess_precheck(tmp_path):
    client = _client(tmp_path, json_responses=[{"iag_type_guess": "publique", "confidence": 0.7}])
    resp = client.post("/wizard/outil", data={
        "tool_name": "", "tool_name_other": "Notion AI", "version_plan_tarifaire": "Free",
    })
    assert resp.status_code == 200
    assert "type d" in resp.text.lower()
    checked_marker = 'value="IAG publique" checked'
    assert checked_marker in resp.text
    assert 'name="version_plan_tarifaire" value="Free"' in resp.text


def test_confirming_tool_type_carries_override_to_profil_utilisateurs_step(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil/type", data={
        "tool_name": "Notion AI", "tool_type": "IAG circuit fermé",
    })
    assert resp.status_code == 200
    assert 'value="circuit_ferme"' in resp.text
    assert "profil" in resp.text.lower()

def test_home_page_renders_test_prefill_button(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'action="/wizard/test-prefill"' in resp.text
    assert "Remplir un scénario test" in resp.text


def test_test_prefill_renders_context_step_with_demo_values(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/test-prefill")
    assert resp.status_code == 200
    assert "Contexte d'affaires" in resp.text
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="usage_description" value="Résumer des documents publics' in resp.text
    assert 'name="besoin_affaires" value="réduire le temps' in resp.text
    assert 'name="mode_acquisition" value="achat_direct" checked' in resp.text
    assert resp.text.count('name="besoin_affaires"') == 1

