import re
from datetime import date
from html import unescape
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET
import pytest
from policybot.models import ContractSource, InterviewState, RequestInfo, Usage, ToolRef, GlobalResult, ContractFacts, QualificationProfile, ContractOfferingIdentity, FactEvidence
from policybot.contract.arp import build_arp
from policybot.grille.engine import evaluate_usage
from policybot.report.renderer import _arp_automated_observations, _auto_observation, _citation_target_url, _reportlab_observation_source_markup, _source_reference_label, _unique_contract_sources, docx_filename, render_docx, render_pdf, pdf_filename, render_html, write_docx, write_pdf

_TIMESTAMP = r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}"


def _state():
    facts = ContractFacts(
        training_default="yes",
        data_residency="us",
        applicable_law="foreign",
        foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no",
        encryption_standard="none",
        opt_out_available="no",
        ip_ownership="vendor",
        authentication_support="sso_mfa",
        audit_logging="prompt_output_accessible",
        institutional_terms_available="yes",
        dpa_available="yes",
        institutional_use_restricted="yes",
        quebec_higher_ed_license="unknown",
        incident_response="documented_with_notice",
        evidence={
            field_name: FactEvidence(
                value=value,
                source_url="https://example.test/contracts",
                quote="The institutional contract explicitly documents this control.",
                confidence=0.9,
                source_collected_at=date(2026, 7, 20),
                source_sha256="should-not-appear-in-observations",
            )
            for field_name, value in {
                "authentication_support": "sso_mfa",
                "audit_logging": "prompt_output_accessible",
                "incident_response": "documented_with_notice",
                "institutional_terms_available": "yes",
                "dpa_available": "yes",
                "institutional_use_restricted": "yes",
                "quebec_higher_ed_license": "unknown",
            }.items()
        },
        sources=[ContractSource(
            url="https://example.test/contracts",
            source_type="conditions d'utilisation",
            collected_at=date(2026, 7, 20),
            sha256="source-hash-must-not-be-rendered",
        )],
    )
    arp = build_arp("ChatGPT", "publique", facts)
    usage = evaluate_usage(
        Usage(description="Résumer des rapports", data_classification="Non classifié"),
        ContractFacts(training_default="no"),
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


def test_render_contains_the_contract_offering_identity():
    state = _state()
    offering = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
        contract_version="2026-07", effective_date=__import__("datetime").date(2026, 7, 1),
    )
    state.tools[0].offering = offering
    state.tools[0].arp.offering = offering

    html = unescape(render_html(state))

    assert "Identité de l’offre contractuelle" in html
    assert "Enterprise" in html
    assert "managed_saas" in html
    assert "institutional_agreement" in html
    assert "2026-07-01" in html


def test_render_flags_an_incomplete_contract_offering_identity():
    state = _state()
    offering = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="",
        deployment_mode="public_saas", contract_type="consumer_terms",
        contract_version="",
    )
    state.tools[0].offering = offering
    state.tools[0].arp.offering = offering

    html = unescape(render_html(state))

    assert "identité de l’offre contractuelle est incomplète" in html
    assert "plan, contract_version" in html


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


def test_render_keeps_residual_risk_cells_empty_and_renders_partie_b_observations():
    html = unescape(render_html(_state()))

    assert "<td></td>" in html
    assert "Aucune règle de la grille déclenchée — risque inhérent de base (Faible)." in html


def test_render_contains_automated_observations_for_manual_arp_criteria():
    html = unescape(render_html(_state()))

    assert "Mécanismes d'authentification" in html
    assert "Journalisation et traçabilité" in html
    assert "Gestion des incidents" in html
    assert "Conditions d'utilisation acceptables" in html
    assert "Compatibilité licence usage gouvernemental" in html
    assert "<strong>SSO/MFA et intégration IdP documentés.</strong>" in html
    assert "<strong>Journaux d'accès et audit prompts/sorties accessibles" in html
    assert "restriction d'usage institutionnel détectée" in html
    assert "<strong>À confirmer; preuve insuffisante sur la compatibilité" in html
    assert "<strong>Plan de réponse aux incidents et notification de brèche" in html
    assert "Constat pré-rempli (à valider)" not in html
    assert "À confirmer par l'agent SI" not in html
    assert "Citation non disponible." not in html
    assert "Source non disponible." not in html
    assert "The institutional contract explicitly documents this control." in html
    assert "Source : <a href=\"https://example.test/contracts#:~:text=" in html
    assert ">example.test</a> — vérifiée le 20 juillet 2026" in html
    assert "Réponse automatisée" not in html
    assert "should-not-appear-in-observations" not in html
    assert "SHA-256" not in html
    assert "source-hash-must-not-be-rendered" not in html


def test_automated_observation_keeps_citations_when_evidence_exists():
    facts = ContractFacts(
        institutional_terms_available="yes",
        dpa_available="yes",
        institutional_use_restricted="no",
        evidence={
            field_name: FactEvidence(
                value="yes",
                source_url="https://example.test/contracts",
                quote="One shared contractual proof.",
                source_collected_at=date(2026, 7, 20),
                source_sha256="not-for-a-human-reader",
            )
            for field_name in (
                "institutional_terms_available",
                "dpa_available",
                "institutional_use_restricted",
            )
        },
    )

    observation = str(_auto_observation("Constat regroupé.", facts, tuple(facts.evidence)))

    assert observation.count("One shared contractual proof.") == 1
    assert observation.count("Source : example.test") == 1
    assert "20 juillet 2026" in observation
    assert "not-for-a-human-reader" not in observation
    assert "institutional_terms_available=yes" not in observation


def test_observation_without_evidence_contains_only_its_value():
    facts = ContractFacts(data_residency="unknown")

    observation = str(_auto_observation(
        "Lieu d'hébergement à confirmer.", facts, "data_residency",
    ))

    assert observation == "Lieu d'hébergement à confirmer."


def test_non_disclosure_observation_is_formatted_without_hash_or_technical_fields():
    facts = ContractFacts(
        contract_prohibits_reuse="unknown",
        provider_human_access="no",
        evidence={
            "contract_prohibits_reuse": FactEvidence(
                value="unknown",
                source_url="https://learn.microsoft.com/en-us/microsoft-365/copilot/privacy",
                quote="Prompts and responses are not used to train the foundation model.",
                source_collected_at=date(2026, 7, 21),
                source_sha256="3c8671da6a7e329048ecf451b8c37316b3ef9122225f8f4cf2bb1db27fdbcaf2",
            ),
            "provider_human_access": FactEvidence(
                value="no",
                source_url="https://learn.microsoft.com/en-us/microsoft-365/copilot/privacy",
                quote="The service has opted out of human content review.",
                source_collected_at=date(2026, 7, 21),
                source_sha256="3c8671da6a7e329048ecf451b8c37316b3ef9122225f8f4cf2bb1db27fdbcaf2",
            ),
        },
    )

    observation = str(_arp_automated_observations(facts)[
        "Garanties contractuelles de non-divulgation"
    ])

    assert "Interdiction contractuelle de réutilisation à confirmer." in observation
    assert "Aucun accès humain du fournisseur n'est documenté." in observation
    assert "contract_prohibits_reuse=unknown" not in observation
    assert "provider_human_access=no" not in observation
    assert "3c8671da6a7e329048ecf451b8c37316b3ef9122225f8f4cf2bb1db27fdbcaf2" not in observation
    assert observation.count("Source : learn.microsoft.com") == 1


def test_source_register_uses_compact_links_and_deduplicates_urls():
    state = _state()
    state.tools.append(ToolRef(
        name="ChatGPT duplicata", iag_type="publique", arp=state.tools[0].arp,
    ))

    sources = _unique_contract_sources(state)

    assert len(sources) == 1
    assert _source_reference_label(sources[0].url) == "example.test / contracts"


def test_partie_a_source_markup_links_to_the_full_url():
    markup = _reportlab_observation_source_markup(
        "https://example.test/contracts",
        date(2026, 7, 20),
    )

    assert '<link href="https://example.test/contracts">' in markup
    assert "<u>example.test</u>" in markup
    assert "vérifiée le 20 juillet 2026" in markup


def test_citation_link_targets_the_verbatim_quote_and_preserves_page_anchor():
    target = _citation_target_url(
        "https://fr.wikipedia.org/wiki/Intelligence_artificielle#Définition",
        "Elle vise à résoudre des problèmes à forte complexité logique ou algorithmique.",
    )

    assert target == (
        "https://fr.wikipedia.org/wiki/Intelligence_artificielle#Définition"
        ":~:text=Elle%20vise%20%C3%A0%20r%C3%A9soudre%20des%20probl%C3%A8mes"
        "%20%C3%A0%20forte%20complexit%C3%A9%20logique%20ou%20algorithmique."
    )


def test_partie_a_observations_render_citations_and_source_links_when_available():
    quote = "The institutional contract explicitly documents this control."
    html = unescape(render_html(_state()))

    expected_target = (
        "https://example.test/contracts#:~:text="
        "The%20institutional%20contract%20explicitly%20documents%20this%20control."
    )
    assert quote in html
    assert expected_target in html


def test_pdf_observations_embed_a_link_to_cited_text_when_available():
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")

    reader = pypdf.PdfReader(BytesIO(render_pdf(_state())))
    targets = []
    for page in reader.pages:
        for annotation_ref in page.get("/Annots", []):
            annotation = annotation_ref.get_object()
            action = annotation.get("/A")
            if action and action.get("/URI"):
                targets.append(str(action["/URI"]))

    assert (
        "https://example.test/contracts#:~:text="
        "The%20institutional%20contract%20explicitly%20documents%20this%20control."
    ) in targets


def test_pdf_splits_an_oversized_risk_row_across_pages():
    pytest.importorskip("reportlab")
    state = _state()
    state.tools[0].arp.contract_facts.evidence["authentication_support"] = FactEvidence(
        value="sso_mfa",
        source_url="https://example.test/contracts",
        quote="This continuous contractual quotation is intentionally long. " * 180,
        confidence=0.9,
        source_collected_at=date(2026, 7, 20),
    )

    pdf = render_pdf(state)

    assert pdf.startswith(b"%PDF")


def test_render_contains_partie_c_conditions():
    state = _state()
    state.result_global.conditions = ["Vérifier l'hébergement des données au Québec."]
    html = unescape(render_html(state))
    assert "Vérifier l'hébergement des données au Québec." in html



def test_pdf_filename_is_timestamped():
    state = _state()
    state.request.numero = "IAG/2026 001"
    assert re.fullmatch(rf"policybot-{_TIMESTAMP}\.pdf", pdf_filename(state))


def test_write_pdf_creates_output_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "policybot.report.renderer.render_pdf",
        lambda state: b"%PDF-1.4 fake policybot pdf",
    )
    path = write_pdf(_state(), output_dir=tmp_path)
    assert re.fullmatch(rf"policybot-{_TIMESTAMP}\.pdf", path.name)
    assert path.read_bytes().startswith(b"%PDF")

def test_docx_filename_is_timestamped():
    state = _state()
    state.request.numero = "IAG/2026 001"
    assert re.fullmatch(rf"policybot-{_TIMESTAMP}-fiche\.docx", docx_filename(state))


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
    assert re.fullmatch(rf"policybot-{_TIMESTAMP}-fiche\.docx", path.name)
    assert path.read_bytes().startswith(b"PK")
