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
