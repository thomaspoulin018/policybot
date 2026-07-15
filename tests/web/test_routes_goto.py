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


def test_goto_profil_utilisateurs_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/profil-utilisateurs", data={
        "tool_name": "ChatGPT",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
    })
    assert resp.status_code == 200
    assert "profil" in resp.text.lower()
    assert 'name="nb_utilisateurs_vises" value="25"' in resp.text
    assert 'name="fonctions_roles" value="conseillers pédagogiques"' in resp.text
    assert 'name="niveau_maitrise_ti" value="intermédiaire" checked' in resp.text
    assert 'name="formation_iag_recue" value="partielle" checked' in resp.text
    assert 'name="acces_protege_a_ou_plus" value="non" checked' in resp.text


def test_goto_donnees_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/donnees", data={
        "tool_name": "ChatGPT",
        "data_checked": ["Renseignements personnels", "Documents internes de travail"],
        "data_free_text": "notes de cours",
    })
    assert resp.status_code == 200
    assert "données" in resp.text.lower()
    assert 'name="data_checked" value="Renseignements personnels" checked' in resp.text
    assert 'name="data_checked" value="Documents internes de travail" checked' in resp.text
    assert 'name="data_free_text" value="notes de cours"' in resp.text


def test_goto_usage_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/usage", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "api",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "10",
        "systemes_api_cibles": "CRM interne",
    })
    assert resp.status_code == 200
    assert "usage" in resp.text.lower()
    assert 'name="usage_description" value="Chercher des informations publiques"' in resp.text
    assert 'name="mode" value="api" checked' in resp.text
    assert 'name="frequence_utilisation" value="quelques fois par semaine"' in resp.text
    assert 'name="nb_utilisateurs" value="10"' in resp.text
    assert 'name="systemes_api_cibles" value="CRM interne"' in resp.text


def test_goto_resultats_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/resultats", data={
        "tool_name": "ChatGPT",
        "result_use_checked": ["Publication"],
        "result_use_free_text": "validation humaine avant diffusion",
        "automated_decisions": "true",
    })
    assert resp.status_code == 200
    assert "usage des résultats" in resp.text.lower()
    assert 'name="result_use_checked" value="Publication" checked' in resp.text
    assert 'name="result_use_free_text" value="validation humaine avant diffusion"' in resp.text
    assert 'name="automated_decisions" value="true" checked' in resp.text


def test_goto_outil_renders_main_form_not_tool_type_screen(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/outil", data={
        "tool_name": "Notion AI",
        "demandeur": "Marie Tremblay",
        "unite": "Direction TI",
    })
    assert resp.status_code == 200
    assert "Quel outil d'IA générative" in resp.text
    assert 'value="Notion AI"' in resp.text
    assert 'name="demandeur" value="Marie Tremblay"' in resp.text
    assert 'name="unite" value="Direction TI"' in resp.text


def test_goto_contexte_affaires_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "besoin_affaires": "réduire le temps de traitement",
        "urgence_percue": "élevée",
        "mode_acquisition": "seao",
    })
    assert resp.status_code == 200
    assert "contexte d'affaires" in resp.text.lower()
    assert 'name="besoin_affaires" value="réduire le temps de traitement"' in resp.text
    assert 'name="urgence_percue" value="élevée" checked' in resp.text
    assert 'name="mode_acquisition" value="seao" checked' in resp.text


def test_steps_nav_renders_done_steps_as_clickable_buttons(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/donnees", data={"tool_name": "ChatGPT"})
    assert resp.status_code == 200
    assert 'id="wizard-form"' in resp.text
    assert '<button type="submit" form="wizard-form" formaction="/wizard/goto/outil"' in resp.text
    assert '<button type="submit" form="wizard-form" formaction="/wizard/goto/profil-utilisateurs"' in resp.text
    assert 'formaction="/wizard/goto/usage"' not in resp.text
    assert 'formaction="/wizard/goto/resultats"' not in resp.text


def test_goto_back_then_forward_preserves_later_answers(tmp_path):
    client = _client(tmp_path)
    full_state_at_contexte_affaires = {
        "tool_name": "ChatGPT",
        "demandeur": "Marie Tremblay",
        "unite": "Direction TI",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
        "data_checked": ["Renseignements personnels"],
        "data_free_text": "notes de cours",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "10",
        "result_use_checked": ["Publication"],
    }

    goto_resp = client.post("/wizard/goto/donnees", data=full_state_at_contexte_affaires)
    assert goto_resp.status_code == 200
    assert 'name="data_checked" value="Renseignements personnels" checked' in goto_resp.text
    assert 'name="data_free_text" value="notes de cours"' in goto_resp.text
    assert 'name="usage_description" value="Chercher des informations publiques"' in goto_resp.text
    assert 'name="result_use_checked" value="Publication"' in goto_resp.text

    forward_resp = client.post("/wizard/donnees", data=full_state_at_contexte_affaires)
    assert forward_resp.status_code == 200
    assert 'name="usage_description" value="Chercher des informations publiques"' in forward_resp.text
    assert 'name="mode" value="prompt"' in forward_resp.text
    assert 'name="frequence_utilisation" value="quelques fois par semaine"' in forward_resp.text
    assert 'name="nb_utilisateurs" value="10"' in forward_resp.text
    assert 'name="result_use_checked" value="Publication"' in forward_resp.text
