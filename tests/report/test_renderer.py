from html import unescape
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET
from policybot.models import InterviewState, RequestInfo, Usage, ToolRef, GlobalResult, ContractFacts, QualificationProfile
from policybot.contract.arp import build_arp
from policybot.grille.engine import evaluate_usage
from policybot.report.renderer import docx_filename, render_docx, pdf_filename, render_html, write_docx, write_pdf


def _state():
    facts = ContractFacts(
        trains_on_input="yes",
        data_residency="us",
        applicable_law="foreign",
        foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no",
        encryption_standard="none",
        reentraining_opt_out="no",
        ip_ownership="vendor",
        authentication_support="sso_mfa",
        audit_logging="prompt_output_accessible",
        institutional_terms="problematic",
        quebec_higher_ed_license="unknown",
        incident_response="documented_with_notice",
    )
    arp = build_arp("ChatGPT", "publique", facts)
    usage = evaluate_usage(
        Usage(description="Résumer des rapports", data_classification="Non classifié"),
        ContractFacts(trains_on_input="no"),
        iag_type="publique",
    )
    return InterviewState(
        interview_id="i1",
        request=RequestInfo(numero="IAG-2026-001", demandeur="Jean Test", unite="VRAF"),
        tools=[ToolRef(name="ChatGPT", iag_type="publique", arp=arp)],
        usages=[usage],
        result_global=GlobalResult(risk_level="Critique", recommendation="Refuser",
                                   efvpr_required=False),
    )


def _docx_text(blob: bytes) -> str:
    with zipfile.ZipFile(BytesIO(blob)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return " ".join(text.text or "" for text in root.findall(".//w:t", ns))


def test_render_contains_request_and_verdict():
    html = unescape(render_html(_state()))
    assert "IAG-2026-001" in html
    assert "ChatGPT" in html
    assert "Refuser" in html
    assert "Non classifié" in html


def test_render_contains_disclaimer_footer():
    html = unescape(render_html(_state()))
    assert "requiert validation et autorisation par l'autorité désignée" in html


def test_render_contains_identification_section():
    html = unescape(render_html(_state()))
    assert "Identification" in html
    assert "Numéro demande" in html


def test_render_contains_all_thirteen_arp_criteria():
    from policybot.criteria import ARP_CRITERIA
    html = unescape(render_html(_state()))
    for _, criterion, _ in ARP_CRITERIA:
        assert criterion in html, f"missing ARP criterion: {criterion}"


def test_render_contains_all_eleven_usage_criteria():
    from policybot.criteria import USAGE_CRITERIA
    html = unescape(render_html(_state()))
    for _, criterion, _ in USAGE_CRITERIA:
        assert criterion in html, f"missing usage criterion: {criterion}"


def test_render_contains_automated_observations_for_manual_arp_criteria():
    html = unescape(render_html(_state()))

    assert "Mécanismes d'authentification" in html
    assert "Journalisation et traçabilité" in html
    assert "Gestion des incidents" in html
    assert "Conditions d'utilisation acceptables" in html
    assert "Compatibilité licence usage gouvernemental" in html
    assert "Réponse automatisée: SSO/MFA et intégration IdP documentés." in html
    assert "Réponse automatisée: Journaux d'accès et audit prompts/sorties accessibles" in html
    assert "Réponse automatisée: Clauses potentiellement problématiques détectées" in html
    assert "Réponse automatisée: À confirmer; preuve insuffisante sur la compatibilité" in html
    assert "Réponse automatisée: Plan de réponse aux incidents et notification de brèche" in html

def test_render_contains_partie_c_conditions():
    state = _state()
    state.result_global.conditions = ["Vérifier l'hébergement des données au Québec."]
    html = unescape(render_html(state))
    assert "Vérifier l'hébergement des données au Québec." in html



def test_pdf_filename_is_stable_and_safe():
    state = _state()
    state.request.numero = "IAG/2026 001"
    assert pdf_filename(state) == "policybot-IAG-2026-001.pdf"


def test_write_pdf_creates_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "policybot.report.renderer.render_pdf",
        lambda state: b"%PDF-1.4 fake policybot pdf",
    )
    path = write_pdf(_state(), output_dir=tmp_path)
    assert path.name == "policybot-IAG-2026-001.pdf"
    assert path.read_bytes().startswith(b"%PDF")

def test_docx_filename_is_stable_and_safe():
    state = _state()
    state.request.numero = "IAG/2026 001"
    assert docx_filename(state) == "policybot-IAG-2026-001-fiche.docx"


def test_render_docx_fills_fiche_template():
    state = _state()
    state.tools[0].version_plan_tarifaire = "Plan Plus"
    state.qualification = QualificationProfile(
        nb_utilisateurs_vises=25,
        fonctions_roles="conseillers",
        besoin_affaires="gagner du temps",
    )
    state.usages[0].raw_answers["data_description"] = "rapports publics"
    blob = render_docx(state)
    assert blob.startswith(b"PK")
    text = _docx_text(blob)
    assert "IAG-2026-001" in text
    assert "ChatGPT" in text
    assert "Plan Plus" in text
    assert "rapports publics" in text
    assert "gagner du temps" in text
    assert "Refuser" in text


def test_write_docx_creates_output_file(tmp_path):
    path = write_docx(_state(), output_dir=tmp_path)
    assert path.name == "policybot-IAG-2026-001-fiche.docx"
    assert path.read_bytes().startswith(b"PK")
