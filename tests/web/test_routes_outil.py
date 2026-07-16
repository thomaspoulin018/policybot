from fastapi.testclient import TestClient
import pytest

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
        "tool_name": "ChatGPT", "tool_name_other": "", "demandeur": "Marie Tremblay", "unite": "Direction TI", "version_plan_tarifaire": "Plan Plus",
    })
    assert resp.status_code == 200
    assert "profil" in resp.text.lower()
    assert 'value="ChatGPT"' in resp.text
    assert 'name="version_plan_tarifaire" value="Plan Plus"' in resp.text


def test_outil_requires_demandeur_and_unite_with_field_errors(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/outil", data={"tool_name": "ChatGPT"})

    assert resp.status_code == 422
    assert "Indiquez le nom du demandeur." in resp.text
    assert "Indiquez l'unite administrative du demandeur." in resp.text


def test_unknown_tool_renders_guided_fallback_with_llm_guess_precheck(tmp_path):
    client = _client(tmp_path, json_responses=[{"iag_type_guess": "publique", "confidence": 0.7}])
    resp = client.post("/wizard/outil", data={
        "tool_name": "", "tool_name_other": "Notion AI", "demandeur": "Marie Tremblay", "unite": "Direction TI", "version_plan_tarifaire": "Free",
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

def test_home_page_renders_test_prefill_scenarios(tmp_path):
    client = _client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Préremplir un scénario de test" in resp.text
    assert resp.text.count('action="/wizard/test-prefill"') == 6
    assert 'value="mcn_blocked"' in resp.text
    assert 'value="arp_closed_circuit"' in resp.text
    assert 'value="protege_c_governmental"' in resp.text
    assert 'value="automated_decision"' in resp.text
    assert 'value="multiple_usages"' in resp.text


def test_test_prefill_renders_context_step_with_demo_values(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/test-prefill", data={"scenario_id": "public_permitted"})
    assert resp.status_code == 200
    assert "Contexte d'affaires" in resp.text
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="usage_description" value="Préparer une veille' in resp.text
    assert 'name="besoin_affaires" value="réduire le temps' in resp.text
    assert 'name="mode_acquisition" value="achat_direct" checked' in resp.text
    assert resp.text.count('name="besoin_affaires"') == 1


@pytest.mark.parametrize(
    ("scenario_id", "expected_tool", "expected_description"),
    [
        ("mcn_blocked", "ChatGPT", "rapports financiers stratégiques"),
        ("arp_closed_circuit", "Microsoft Copilot Entreprise", "procédures administratives"),
        ("protege_c_governmental", "Assistant gouvernemental sécurisé", "dossier de sécurité"),
        ("automated_decision", "ChatGPT", "Classer automatiquement"),
        ("multiple_usages", "ChatGPT", "prévisions budgétaires stratégiques"),
    ],
)
def test_each_test_scenario_prefills_its_expected_form_values(
    tmp_path, scenario_id, expected_tool, expected_description,
):
    client = _client(tmp_path)

    resp = client.post("/wizard/test-prefill", data={"scenario_id": scenario_id})

    assert resp.status_code == 200
    assert f'name="tool_name" value="{expected_tool}"' in resp.text
    assert expected_description in resp.text


def test_mcn_blocked_prefill_contains_the_data_that_should_trigger_the_gate(tmp_path):
    client = _client(tmp_path)

    resp = client.post("/wizard/test-prefill", data={"scenario_id": "mcn_blocked"})

    assert 'name="data_checked" value="Renseignements personnels"' in resp.text
    assert 'name="data_checked" value="Données stratégiques / confidentielles"' in resp.text
    assert 'name="tool_type_override"' not in resp.text


def test_governmental_prefill_carries_the_required_tool_type_override(tmp_path):
    client = _client(tmp_path)

    resp = client.post(
        "/wizard/test-prefill", data={"scenario_id": "protege_c_governmental"}
    )

    assert 'name="tool_type_override" value="gouvernementale"' in resp.text
    assert "secrets de sécurité hautement sensibles" in resp.text


def test_multiple_usages_prefill_serializes_the_first_usage(tmp_path):
    client = _client(tmp_path)

    resp = client.post("/wizard/test-prefill", data={"scenario_id": "multiple_usages"})

    assert 'name="saved_usages_json"' in resp.text
    assert "Préparer une veille à partir de sources publiques" in resp.text
    assert "Résumer les prévisions budgétaires stratégiques" in resp.text


def test_unknown_test_scenario_returns_404(tmp_path):
    client = _client(tmp_path)

    resp = client.post("/wizard/test-prefill", data={"scenario_id": "inconnu"})

    assert resp.status_code == 404

