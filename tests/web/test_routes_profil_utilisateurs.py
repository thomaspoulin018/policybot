from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")))
    return TestClient(create_app(itv))


def test_profil_utilisateurs_submit_renders_donnees_step_with_hidden_fields(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/profil-utilisateurs", data={
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
    })
    assert resp.status_code == 200
    assert "données" in resp.text.lower()
    assert 'name="tool_name" value="ChatGPT"' in resp.text
    assert 'name="version_plan_tarifaire" value="Plan Plus"' in resp.text
    assert 'name="nb_utilisateurs_vises" value="25"' in resp.text
    assert 'name="fonctions_roles" value="conseillers pédagogiques"' in resp.text
    assert 'name="niveau_maitrise_ti" value="intermédiaire"' in resp.text
    assert 'name="formation_iag_recue" value="partielle"' in resp.text
    assert 'name="acces_protege_a_ou_plus" value="non"' in resp.text
