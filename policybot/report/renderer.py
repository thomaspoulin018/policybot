from __future__ import annotations
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from itertools import groupby
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from policybot.models import ContractFacts, InterviewState, RiskFactor
from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_DEFAULT_PDF_OUTPUT_DIR = Path("output") / "pdf"
_DEFAULT_DOCX_OUTPUT_DIR = Path("output") / "docx"
_DEFAULT_FICHE_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "documents_reference"
    / "SI_-_Fiche_de_qualification.docx"
)
_FILENAME_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
ET.register_namespace("w", _WORD_NS)
_PDF_CSS = """
@page {
  size: Letter;
  margin: 18mm 14mm 16mm;
  @bottom-center {
    content: "PolicyBot - page " counter(page) " / " counter(pages);
    color: #667085;
    font-size: 8pt;
  }
}
html {
  color: #111827;
  font-family: "Inter", "Segoe UI", Arial, sans-serif;
  font-size: 9pt;
  line-height: 1.38;
}
body { margin: 0; }
article { width: 100%; }
h1 {
  border-bottom: 2pt solid #3d7d85;
  color: #101827;
  font-size: 19pt;
  line-height: 1.15;
  margin: 0 0 10mm;
  padding-bottom: 5mm;
}
h2 {
  color: #2b6169;
  font-size: 13pt;
  margin: 12mm 0 4mm;
  page-break-after: avoid;
}
h3 {
  color: #344054;
  font-size: 10.5pt;
  margin: 7mm 0 3mm;
  page-break-after: avoid;
}
p { margin: 0 0 4mm; }
.disclaimer {
  background: #fff5f5;
  border: 0.75pt solid #f2b8b5;
  border-left: 4pt solid #d8352f;
  color: #4b5563;
  padding: 4mm;
}
section { page-break-inside: auto; }
table {
  border-collapse: collapse;
  margin: 3mm 0 7mm;
  width: 100%;
}
th, td {
  border: 0.5pt solid #d0d5dd;
  padding: 2.2mm 2.4mm;
  text-align: left;
  vertical-align: top;
}
th {
  background: #eef6f7;
  color: #1f2937;
  font-weight: 700;
}
.risk-table {
  font-size: 7.4pt;
  table-layout: fixed;
}
.risk-table th:nth-child(1), .risk-table td:nth-child(1) { width: 10%; }
.risk-table th:nth-child(2), .risk-table td:nth-child(2) { width: 25%; }
.risk-table th:nth-child(3), .risk-table td:nth-child(3) { width: 9%; }
.risk-table th:nth-child(4), .risk-table td:nth-child(4) { width: 19%; }
.risk-table th:nth-child(5), .risk-table td:nth-child(5) { width: 9%; }
.risk-table th:nth-child(6), .risk-table td:nth-child(6) { width: 10%; }
.risk-table th:nth-child(7), .risk-table td:nth-child(7) { width: 18%; }
tr { page-break-inside: avoid; }
.category-row td {
  background: #f8fafc;
  color: #2b6169;
  font-weight: 700;
}
ul { margin: 0; padding-left: 4mm; }
footer {
  border-top: 0.75pt solid #d0d5dd;
  color: #667085;
  font-size: 8pt;
  margin-top: 10mm;
  padding-top: 3mm;
}
"""

_AUTH_LABELS = {
    "sso_mfa": "SSO/MFA et intégration IdP documentés.",
    "partial": "Support partiel documenté; validation SI requise.",
    "none": "Aucun support SSO/MFA documenté.",
    "unknown": "À confirmer; preuve insuffisante sur SSO/MFA ou intégration UQAM.",
}
_AUDIT_LABELS = {
    "prompt_output_accessible": "Journaux d'accès et audit prompts/sorties accessibles à l'organisation documentés.",
    "access_logs_only": "Journaux d'accès documentés; audit prompts/sorties non confirmé.",
    "none": "Aucune journalisation organisationnelle documentée.",
    "unknown": "À confirmer; preuve insuffisante sur les journaux et l'audit prompts/sorties.",
}
_TERMS_LABELS = {
    "acceptable": "Conditions compatibles avec un usage institutionnel selon les sources consultées.",
    "problematic": "Clauses potentiellement problématiques détectées; revue contractuelle requise.",
    "unknown": "À confirmer; preuve insuffisante sur l'acceptabilité institutionnelle.",
}
_LICENSE_LABELS = {
    "yes": "Usage par une institution d'enseignement supérieur/public-sector permis selon les sources consultées.",
    "no": "Licence incompatible ou restriction explicite détectée.",
    "unknown": "À confirmer; preuve insuffisante sur la compatibilité avec une institution québécoise.",
}
_INCIDENT_LABELS = {
    "documented_with_notice": "Plan de réponse aux incidents et notification de brèche documentés.",
    "documented_no_notice": "Plan de réponse aux incidents documenté; délai de notification non confirmé.",
    "none": "Aucun plan de réponse aux incidents documenté dans les sources consultées.",
    "unknown": "À confirmer; preuve insuffisante sur la réponse aux incidents ou la notification de brèche.",
}


def _auto_observation(
    label: str,
    facts: ContractFacts,
    field_name: str,
) -> str:
    parts = [f"Réponse automatisée: {label}"]
    proof = facts.evidence.get(field_name)
    if proof is not None:
        if proof.note:
            parts.append(proof.note)
        if proof.quote:
            parts.append(f"« {proof.quote} »")
        if proof.source_url:
            parts.append(f"source: {proof.source_url}")
        if proof.source_collected_at:
            parts.append(f"collectée le: {proof.source_collected_at}")
        if proof.source_sha256:
            parts.append(f"sha256: {proof.source_sha256}")
    return " — ".join(parts)


def _arp_automated_observations(facts: ContractFacts | None) -> dict[str, str]:
    if facts is None:
        return {}
    return {
        "Mécanismes d'authentification": _auto_observation(
            _AUTH_LABELS[facts.authentication_support], facts, "authentication_support",
        ),
        "Journalisation et traçabilité": _auto_observation(
            _AUDIT_LABELS[facts.audit_logging], facts, "audit_logging",
        ),
        "Gestion des incidents": _auto_observation(
            _INCIDENT_LABELS[facts.incident_response], facts, "incident_response",
        ),
        "Conditions d'utilisation acceptables": _auto_observation(
            _TERMS_LABELS[facts.institutional_terms], facts, "institutional_terms",
        ),
        "Compatibilité licence usage gouvernemental": _auto_observation(
            _LICENSE_LABELS[facts.quebec_higher_ed_license],
            facts,
            "quebec_higher_ed_license",
        ),
    }

_env = Environment(
    loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _merge_rows(
    criteria_table: list[tuple[str, str, str]],
    factors: list[RiskFactor],
    automated_observations: dict[str, str] | None = None,
) -> list[dict]:
    by_criterion = {factor.criterion: factor for factor in factors}
    automated_observations = automated_observations or {}
    rows = []
    for category, criterion, description in criteria_table:
        factor = by_criterion.get(criterion)
        rows.append({
            "category": category,
            "criterion": criterion,
            "description": description,
            "inherent": factor.inherent if factor else None,
            "mitigation": factor.mitigation if factor else "",
            "residual": factor.residual if factor else None,
            "responsable": factor.responsable if factor else "",
            "observations": factor.observations if factor else automated_observations.get(criterion, ""),
        })
    return rows


def _group_by_category(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    return [
        (category, list(group))
        for category, group in groupby(rows, key=lambda row: row["category"])
    ]


def render_html(state: InterviewState) -> str:
    arp_tables = [
        {
            "tool_name": tool.name,
            "offering": tool.offering or (tool.arp.offering if tool.arp else None),
            "sources": tool.arp.contract_facts.sources if tool.arp else [],
            "groups": _group_by_category(
                _merge_rows(
                    ARP_CRITERIA,
                    tool.arp.criteria if tool.arp else [],
                    _arp_automated_observations(
                        tool.arp.contract_facts if tool.arp else None
                    ),
                )
            ),
        }
        for tool in state.tools
    ]
    usage_tables = [
        {
            "usage": usage,
            "index": index,
            "groups": _group_by_category(_merge_rows(USAGE_CRITERIA, usage.partie_b)),
        }
        for index, usage in enumerate(state.usages, start=1)
    ]
    return _env.get_template("report.html.j2").render(
        state=state,
        arp_tables=arp_tables,
        usage_tables=usage_tables,
    )


def pdf_output_dir() -> Path:
    return Path(os.getenv("POLICYBOT_PDF_OUTPUT_DIR", _DEFAULT_PDF_OUTPUT_DIR))


def pdf_filename(state: InterviewState) -> str:
    return f"policybot-{datetime.now().strftime(_FILENAME_TIMESTAMP_FORMAT)}.pdf"


def docx_output_dir() -> Path:
    return Path(os.getenv("POLICYBOT_DOCX_OUTPUT_DIR", _DEFAULT_DOCX_OUTPUT_DIR))


def fiche_template_path() -> Path:
    return Path(os.getenv("POLICYBOT_FICHE_TEMPLATE", _DEFAULT_FICHE_TEMPLATE))


def docx_filename(state: InterviewState) -> str:
    return f"policybot-{datetime.now().strftime(_FILENAME_TIMESTAMP_FORMAT)}-fiche.docx"


def _w(tag: str) -> str:
    return f"{{{_WORD_NS}}}{tag}"


def _table_cell(table: ET.Element, row_index: int, cell_index: int) -> ET.Element:
    return table.findall(_w("tr"))[row_index].findall(_w("tc"))[cell_index]


def _set_cell_text(cell: ET.Element, value: object) -> None:
    text = _text(value)
    tc_pr = cell.find(_w("tcPr"))
    for child in list(cell):
        cell.remove(child)
    if tc_pr is not None:
        cell.append(tc_pr)
    paragraph = ET.SubElement(cell, _w("p"))
    run = ET.SubElement(paragraph, _w("r"))
    lines = text.splitlines() or [""]
    for index, line in enumerate(lines):
        if index:
            ET.SubElement(run, _w("br"))
        text_element = ET.SubElement(run, _w("t"))
        text_element.set(f"{{{_XML_NS}}}space", "preserve")
        text_element.text = line


def _set_table_value(table: ET.Element, row_index: int, value: object, cell_index: int = 1) -> None:
    _set_cell_text(_table_cell(table, row_index, cell_index), value)


def _date_text(state: InterviewState) -> str:
    return state.request.date.isoformat() if state.request.date else ""


def _first_tool(state: InterviewState):
    return state.tools[0] if state.tools else None


def _first_usage(state: InterviewState):
    return state.usages[0] if state.usages else None


def _yes_no(value: bool) -> str:
    return "Oui" if value else "Non"


def _label(value: object, labels: dict[str, str]) -> str:
    return labels.get(_text(value), _text(value))


def _join_lines(values: list[str]) -> str:
    return "\n".join(value for value in values if value)


_IAG_TYPE_LABELS = {
    "publique": "IAG publique",
    "circuit_ferme": "IAG circuit ferme",
    "souveraine": "IAG souveraine",
    "gouvernementale": "IAG gouvernementale circuit ferme",
}
_NIVEAU_TI_LABELS = {
    "débutant": "Debutant",
    "intermédiaire": "Intermediaire",
    "avancé": "Avance",
}
_FORMATION_LABELS = {
    "aucune": "Aucune",
    "partielle": "Partielle",
    "complète": "Complete (MCN)",
}
_ACCES_LABELS = {
    "oui": "Oui",
    "non": "Non",
    "à vérifier": "A verifier",
}
_URGENCE_LABELS = {
    "faible": "Faible",
    "modérée": "Moderee",
    "élevée": "Elevee",
}
_MODE_ACQUISITION_LABELS = {
    "achat_direct": "Achat direct",
    "seao": "Via SEAO",
    "appel_offres": "Via appel d'offres",
    "contrat_existant": "Contrat existant",
}
_DATA_RESIDENCY_LABELS = {
    "canada": "Oui - Canada/Quebec a confirmer",
    "us": "Non - Etats-Unis",
    "eu": "Non - Union europeenne",
    "other": "Non - autre territoire",
    "unknown": "Inconnu",
}
_TRAINING_LABELS = {
    "yes": "Oui",
    "no": "Non",
    "opt_out_available": "A verifier - opt-out disponible",
    "unknown": "A verifier avec le fournisseur",
}


def _usage_nature(usage) -> str:
    if not usage:
        return ""
    description = _text(usage.raw_answers.get("data_description", ""))
    if description:
        return description
    return _join_lines([
        usage.description,
        f"Classification: {usage.data_classification}" if usage.data_classification else "",
    ])


def _fill_identification_table(table: ET.Element, state: InterviewState) -> None:
    _set_table_value(table, 0, state.request.numero)
    _set_table_value(table, 1, _date_text(state))
    _set_table_value(table, 2, state.request.demandeur)
    _set_table_value(table, 3, state.request.unite)


def _fill_tools_table(table: ET.Element, state: InterviewState) -> None:
    for index, tool in enumerate(state.tools[:2]):
        offset = index * 4
        _set_table_value(table, offset, tool.name)
        _set_table_value(table, offset + 1, _label(tool.iag_type, _IAG_TYPE_LABELS))
        _set_table_value(
            table,
            offset + 2,
            tool.offering.display_label()
            if tool.offering else tool.version_plan_tarifaire,
        )
        _set_table_value(table, offset + 3, tool.vendor or "")


def _usage_mode_text(usage) -> str:
    modes = []
    if "prompt" in usage.mode:
        modes.append("Prompt traditionnel")
    if "api" in usage.mode:
        api_text = "Appels API"
        if usage.systemes_api_cibles:
            api_text = f"{api_text} - systemes cibles: {usage.systemes_api_cibles}"
        modes.append(api_text)
    return ", ".join(modes)


def _usage_description_text(usage) -> str:
    details = [usage.description]
    if usage.frequence_utilisation:
        details.append(f"Frequence: {usage.frequence_utilisation}")
    if usage.nb_utilisateurs is not None:
        details.append(f"Nombre d'utilisateurs: {usage.nb_utilisateurs}")
    return _join_lines(details)


def _fill_usages_table(table: ET.Element, state: InterviewState) -> None:
    for index, usage in enumerate(state.usages[:4]):
        row = 1 + index * 5
        _set_table_value(table, row, _usage_description_text(usage))
        _set_table_value(table, row + 1, usage.data_classification or "")
        _set_table_value(table, row + 2, _usage_mode_text(usage))
        _set_table_value(table, row + 3, ", ".join(usage.result_use))
        _set_table_value(table, row + 4, _yes_no(usage.automated_decisions))


def _fill_profile_table(table: ET.Element, state: InterviewState) -> None:
    q = state.qualification
    _set_table_value(table, 0, q.nb_utilisateurs_vises if q.nb_utilisateurs_vises is not None else "")
    _set_table_value(table, 1, q.fonctions_roles)
    _set_table_value(table, 2, _label(q.niveau_maitrise_ti, _NIVEAU_TI_LABELS))
    _set_table_value(table, 3, _label(q.formation_iag_recue, _FORMATION_LABELS))
    _set_table_value(table, 4, _label(q.acces_protege_a_ou_plus, _ACCES_LABELS))


def _fill_data_table(table: ET.Element, state: InterviewState) -> None:
    tool = _first_tool(state)
    usage = _first_usage(state)
    facts = tool.arp.contract_facts if tool and tool.arp else None
    _set_table_value(table, 0, "Oui" if state.usages else "")
    _set_table_value(table, 1, _usage_nature(usage))
    _set_table_value(table, 2, _label(facts.data_residency, _DATA_RESIDENCY_LABELS) if facts else "")
    _set_table_value(table, 3, _yes_no(any(usage.rens_personnels for usage in state.usages)))
    _set_table_value(table, 4, _label(facts.trains_on_input, _TRAINING_LABELS) if facts else "")
    _set_table_value(table, 5, "Voir ARP et conditions fournisseur extraites automatiquement." if facts else "")


def _fill_value_table(table: ET.Element, state: InterviewState) -> None:
    q = state.qualification
    _set_table_value(table, 0, q.besoin_affaires)
    _set_table_value(table, 1, q.gains_qualitatifs)
    _set_table_value(table, 2, q.gains_quantitatifs)
    _set_table_value(table, 3, q.alternatives_considerees)
    _set_table_value(table, 4, _label(q.urgence_percue, _URGENCE_LABELS))


def _fill_finance_table(table: ET.Element, state: InterviewState) -> None:
    q = state.qualification
    _set_table_value(table, 0, q.cout_annuel_par_utilisateur)
    _set_table_value(table, 1, q.cout_total_annuel)
    _set_table_value(table, 2, _label(q.mode_acquisition, _MODE_ACQUISITION_LABELS))
    _set_table_value(table, 3, q.duree_contrat)
    _set_table_value(table, 4, q.responsable_budgetaire)


def _fill_observations_table(table: ET.Element, state: InterviewState) -> None:
    conditions = _join_lines(state.result_global.conditions)
    _set_table_value(table, 0, _join_lines([
        f"EFVP-R requise: {_yes_no(state.result_global.efvpr_required)}",
        f"Risque global: {state.result_global.risk_level or ''}",
    ]))
    _set_table_value(table, 1, conditions)
    _set_table_value(table, 2, "Validation et autorisation par l'autorite designee.")
    _set_table_value(table, 3, state.result_global.recommendation or "")
    _set_table_value(table, 4, "Poursuivre avec la grille d'evaluation des risques et la validation SI.")


def _fill_fiche_document(document_xml: bytes, state: InterviewState) -> bytes:
    root = ET.fromstring(document_xml)
    tables = root.findall(f".//{_w('tbl')}")
    if len(tables) < 8:
        raise RuntimeError("Le gabarit Word de fiche de qualification ne contient pas les 8 tableaux attendus.")
    _fill_identification_table(tables[0], state)
    _fill_tools_table(tables[1], state)
    _fill_usages_table(tables[2], state)
    _fill_profile_table(tables[3], state)
    _fill_data_table(tables[4], state)
    _fill_value_table(tables[5], state)
    _fill_finance_table(tables[6], state)
    _fill_observations_table(tables[7], state)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def render_docx(state: InterviewState) -> bytes:
    template = fiche_template_path()
    if not template.is_file():
        raise RuntimeError(f"Gabarit Word introuvable: {template}")
    buffer = BytesIO()
    with zipfile.ZipFile(template, "r") as source:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    data = _fill_fiche_document(data, state)
                target.writestr(item, data)
    return buffer.getvalue()


def write_docx(state: InterviewState, output_dir: str | os.PathLike | None = None) -> Path:
    directory = Path(output_dir) if output_dir is not None else docx_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / docx_filename(state)
    path.write_bytes(render_docx(state))
    return path


def _as_pdf_document(report_html: str) -> str:
    return (
        '<!doctype html><html lang="fr"><head>'
        '<meta charset="utf-8"><title>Rapport PolicyBot</title>'
        "</head><body>"
        f"{report_html}"
        "</body></html>"
    )


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import CSS, HTML  # optional dependency
        return HTML(string=_as_pdf_document(html), base_url=_TEMPLATES).write_pdf(
            stylesheets=[CSS(string=_PDF_CSS)]
        )
    except (ImportError, OSError) as exc:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint non disponible. Installez policybot[pdf] et les bibliotheques GTK/Pango, "
            "ou laissez le fallback ReportLab generer le PDF."
        ) from exc


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _para(value: object, style):
    from xml.sax.saxutils import escape
    from reportlab.platypus import Paragraph

    text = escape(_text(value)).replace("\n", "<br/>")
    return Paragraph(text or " ", style)


def _make_reportlab_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    base["Title"].fontSize = 22
    base["Title"].leading = 26
    base["Title"].textColor = colors.HexColor("#101827")
    base["Heading2"].fontSize = 15
    base["Heading2"].leading = 18
    base["Heading2"].spaceBefore = 14
    base["Heading2"].spaceAfter = 8
    base["Heading2"].textColor = colors.HexColor("#2b6169")
    base["Heading3"].fontSize = 11
    base["Heading3"].leading = 14
    base["Heading3"].spaceBefore = 10
    base["Heading3"].spaceAfter = 6
    base["BodyText"].fontSize = 9
    base["BodyText"].leading = 12
    base.add(ParagraphStyle(
        name="Small",
        parent=base["BodyText"],
        fontSize=7.2,
        leading=8.6,
    ))
    base.add(ParagraphStyle(
        name="Footer",
        parent=base["BodyText"],
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#667085"),
    ))
    return base


def _basic_table(rows: list[list[object]], styles, col_widths=None):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0d5dd")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef6f7")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _risk_table(headers: list[str], groups: list[tuple[str, list[dict]]], styles):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    rows = [[_para(header, styles["Small"]) for header in headers]]
    span_rows = []
    for category, group_rows in groups:
        span_rows.append(len(rows))
        rows.append([_para(category, styles["Small"])] + [""] * (len(headers) - 1))
        for row in group_rows:
            rows.append([
                _para(row["criterion"], styles["Small"]),
                _para(row["description"], styles["Small"]),
                _para(row["inherent"] or "", styles["Small"]),
                _para(row["mitigation"], styles["Small"]),
                _para(row["residual"] or "", styles["Small"]),
                _para(row["responsable"], styles["Small"]),
                _para(row["observations"], styles["Small"]),
            ])
    widths = [50, 145, 48, 110, 48, 58, 103]
    table = Table(rows, colWidths=widths, hAlign="LEFT", repeatRows=1)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d5dd")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef6f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index in span_rows:
        commands.extend([
            ("SPAN", (0, row_index), (-1, row_index)),
            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f8fafc")),
            ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.HexColor("#2b6169")),
        ])
    table.setStyle(TableStyle(commands))
    return table


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColorRGB(0.4, 0.44, 0.52)
    canvas.drawCentredString(
        doc.pagesize[0] / 2,
        10,
        f"PolicyBot - page {doc.page}",
    )
    canvas.restoreState()


def _render_reportlab_pdf(state: InterviewState) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Spacer, TableStyle
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("ReportLab non installe. Installez policybot[pdf].") from exc

    from io import BytesIO

    styles = _make_reportlab_styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=13 * mm,
        bottomMargin=15 * mm,
        title=f"Rapport PolicyBot {state.request.numero}",
    )
    story = []
    story.append(_para("Rapport de recommandation - PolicyBot", styles["Title"]))
    story.append(Spacer(1, 8))
    disclaimer = _basic_table(
        [[_para(
            "PolicyBot recommande; il n'autorise pas. Ce rapport requiert la validation et "
            "l'autorisation de l'autorite designee.",
            styles["BodyText"],
        )]],
        styles,
        [700],
    )
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff5f5")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f2b8b5")),
    ]))
    story.append(disclaimer)
    story.append(Spacer(1, 10))

    story.append(_para("Identification", styles["Heading2"]))
    tool_names = ", ".join(tool.name for tool in state.tools)
    story.append(_basic_table([
        [_para("Numero demande", styles["BodyText"]), _para(state.request.numero, styles["BodyText"])],
        [_para("Outil evalue", styles["BodyText"]), _para(tool_names, styles["BodyText"])],
        [_para("Demandeur", styles["BodyText"]), _para(state.request.demandeur, styles["BodyText"])],
        [_para("Unite", styles["BodyText"]), _para(state.request.unite, styles["BodyText"])],
        [_para("Date", styles["BodyText"]), _para(state.request.date or "", styles["BodyText"])],
    ], styles, [150, 550]))

    story.append(_para("Partie A - Analyse des risques du produit (ARP)", styles["Heading2"]))
    story.append(_para(
        "L'ARP evalue l'outil en tant que produit, independamment des usages specifiques.",
        styles["BodyText"],
    ))
    arp_tables = [
        {
            "tool_name": tool.name,
            "offering": tool.offering or (tool.arp.offering if tool.arp else None),
            "sources": tool.arp.contract_facts.sources if tool.arp else [],
            "groups": _group_by_category(
                _merge_rows(
                    ARP_CRITERIA,
                    tool.arp.criteria if tool.arp else [],
                    _arp_automated_observations(
                        tool.arp.contract_facts if tool.arp else None
                    ),
                )
            ),
        }
        for tool in state.tools
    ]
    for table in arp_tables:
        story.append(_para(f"Outil : {table['tool_name']}", styles["Heading3"]))
        if table["offering"] is not None:
            story.append(_para(
                f"Identite de l'offre contractuelle : {table['offering'].display_label()}",
                styles["BodyText"],
            ))
        if table["sources"]:
            story.append(_para("Sources contractuelles retenues :", styles["BodyText"]))
            for source in table["sources"]:
                story.append(_para(
                    f"{source.source_type} | {source.url} | collecte {source.collected_at} | "
                    f"effet {source.effective_date or 'inconnu'} | sha256 {source.sha256}",
                    styles["BodyText"],
                ))
        story.append(_risk_table([
            "Critere", "Description / question", "Risque inherent", "Mesures de mitigation",
            "Risque residuel", "Responsable", "Observations / constats",
        ], table["groups"], styles))
        story.append(Spacer(1, 8))

    story.append(_para("Partie B - Evaluation des risques par usage", styles["Heading2"]))
    usage_tables = [
        {
            "usage": usage,
            "index": index,
            "groups": _group_by_category(_merge_rows(USAGE_CRITERIA, usage.partie_b)),
        }
        for index, usage in enumerate(state.usages, start=1)
    ]
    for table in usage_tables:
        usage = table["usage"]
        story.append(_para(f"Usage {table['index']} : {usage.description}", styles["Heading3"]))
        story.append(_para(
            f"Classification des donnees : {usage.data_classification or ''} | "
            f"Renseignements personnels : {'Oui' if usage.rens_personnels else 'Non'} | "
            f"Matrice MCN : {usage.matrix_result or ''}",
            styles["BodyText"],
        ))
        story.append(_risk_table([
            "Critere", "Risque evalue", "Risque inherent", "Mesures de mitigation",
            "Risque residuel", "Responsable", "Observations",
        ], table["groups"], styles))
        story.append(Spacer(1, 8))

    story.append(_para("Partie C - Synthese et decision", styles["Heading2"]))
    conditions = "\n".join(state.result_global.conditions)
    story.append(_basic_table([
        [_para("Niveau de risque global", styles["BodyText"]), _para(state.result_global.risk_level, styles["BodyText"])],
        [_para("EFVP-R requise", styles["BodyText"]), _para("Oui" if state.result_global.efvpr_required else "Non", styles["BodyText"])],
        [_para("Recommandation preliminaire", styles["BodyText"]), _para(state.result_global.recommendation, styles["BodyText"])],
        [_para("Conditions / restrictions proposees", styles["BodyText"]), _para(conditions, styles["BodyText"])],
    ], styles, [190, 510]))
    story.append(Spacer(1, 10))
    story.append(_para(
        "Recommandation generee par PolicyBot - requiert validation et autorisation par l'autorite designee.",
        styles["Footer"],
    ))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def render_pdf(state: InterviewState) -> bytes:
    try:
        return _render_reportlab_pdf(state)
    except RuntimeError:
        return html_to_pdf(render_html(state))


def write_pdf(state: InterviewState, output_dir: str | os.PathLike | None = None) -> Path:
    directory = Path(output_dir) if output_dir is not None else pdf_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / pdf_filename(state)
    path.write_bytes(render_pdf(state))
    return path
