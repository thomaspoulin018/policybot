# tests/web/test_routes_resultat.py
from html import unescape
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app
from tests.helpers.arp_fixtures import arp_extraction_responses


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
        *arp_extraction_responses(training_default="no", data_residency="quebec"),
    ])
    resp = client.post("/wizard/contexte-affaires", data={
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
        *arp_extraction_responses(training_default="yes", data_residency="us"),
    ])
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Données stratégiques / confidentielles",
        "usage_description": "Analyser des chiffres financiers internes",
        "mode": "prompt",
    })
    assert resp.status_code == 200
    assert "Refuser" in resp.text


def test_final_submit_renders_error_screen_when_assess_fails(tmp_path):
    client = _client(tmp_path, json_responses=[])  # empty queue -> classify_data raises IndexError
    resp = client.post("/wizard/contexte-affaires", data={
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
        resp = client.post("/wizard/contexte-affaires", data={
            "tool_name": "ChatGPT",
            "data_checked": "Info déjà publique",
            "usage_description": "Chercher de l'info publique",
            "mode": "prompt",
        })
    assert resp.status_code == 502
    assert any("assess failed" in record.message for record in caplog.records)
    assert any(record.exc_info for record in caplog.records)


def test_final_submit_passes_qualification_fields_into_assess(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(training_default="no", data_residency="quebec"),
    ])
    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "data_checked": "Info déjà publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
        "frequence_utilisation": "quotidienne",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers",
        "besoin_affaires": "gagner du temps",
        "mode_acquisition": "seao",
    })
    assert resp.status_code == 200
    assert "Rapport de recommandation" in resp.text



def test_final_submit_writes_pdf_and_exposes_download(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "pdf"

    def fake_write_pdf(state):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "policybot-test.pdf"
        path.write_bytes(b"%PDF-1.4 fake policybot pdf")
        return path

    monkeypatch.setenv("POLICYBOT_PDF_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr("policybot.web.routes.write_pdf", fake_write_pdf)
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(training_default="no", data_residency="quebec"),
    ])

    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info deja publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })

    assert resp.status_code == 200
    assert "Telecharger le PDF" in resp.text
    assert "output/pdf/policybot-test.pdf" in resp.text
    download = client.get("/output/pdf/policybot-test.pdf")
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")

def test_final_submit_writes_docx_and_exposes_download(tmp_path, monkeypatch):
    output_dir = tmp_path / "output" / "docx"

    def fake_write_docx(state):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "policybot-test-fiche.docx"
        path.write_bytes(b"PK fake policybot docx")
        return path

    monkeypatch.setenv("POLICYBOT_DOCX_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr("policybot.web.routes.write_docx", fake_write_docx)
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(training_default="no", data_residency="quebec"),
    ])

    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info deja publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
    })

    assert resp.status_code == 200
    assert "Telecharger la fiche Word" in resp.text
    assert "output/docx/policybot-test-fiche.docx" in resp.text
    download = client.get("/output/docx/policybot-test-fiche.docx")
    assert download.status_code == 200
    assert download.content.startswith(b"PK")



def test_final_submit_accepts_saved_and_current_usages(tmp_path):
    client = _client(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"already_public": False, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(training_default="no", data_residency="quebec"),
    ])
    first = client.post("/wizard/resultats", data={
        "tool_name": "ChatGPT",
        "data_checked": "Info deja publique",
        "usage_description": "Chercher de l'info publique",
        "mode": "prompt",
        "result_use_checked": "Publication",
        "usage_action": "add_usage",
    })
    saved_json = unescape(first.text.split('name="saved_usages_json" value="', 1)[1].split('"', 1)[0])

    resp = client.post("/wizard/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "saved_usages_json": saved_json,
        "data_checked": "Documents internes",
        "usage_description": "Resumer des notes internes",
        "mode": "prompt",
        "result_use_checked": "Aide a la redaction",
    })

    assert resp.status_code == 200
    assert "Usage 1" in resp.text
    assert "Usage 2" in resp.text
    rendered = unescape(resp.text)
    assert "Chercher de l'info publique" in rendered
    assert "Resumer des notes internes" in rendered
