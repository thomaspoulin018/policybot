from __future__ import annotations

from datetime import datetime
from html import escape as html_escape
from io import BytesIO
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
import zipfile
import xml.etree.ElementTree as ET

from jinja2 import Environment, FileSystemLoader, select_autoescape

from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA
from policybot.models import CriterionCitation, CriterionFinding, InterviewState


_TEMPLATES = Path(__file__).with_name("templates")
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

_FRENCH_MONTHS = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "rapport"


def _filename_stem(state: InterviewState) -> str:
    """Le numéro de demande précède l'horodatage.

    Sans lui, deux demandes d'un même lot traitées dans la même seconde
    écriraient dans le même fichier.
    """
    numero = _safe_filename(state.request.numero) if state.request.numero else "policybot"
    return f"{numero}_{datetime.now():{_FILENAME_TIMESTAMP_FORMAT}}"


def pdf_filename(state: InterviewState) -> str:
    return f"{_filename_stem(state)}.pdf"


def docx_filename(state: InterviewState) -> str:
    return f"{_filename_stem(state)}-fiche.docx"


def pdf_output_dir() -> Path:
    return Path(os.environ.get("POLICYBOT_PDF_OUTPUT_DIR") or _DEFAULT_PDF_OUTPUT_DIR)


def docx_output_dir() -> Path:
    return Path(os.environ.get("POLICYBOT_DOCX_OUTPUT_DIR") or _DEFAULT_DOCX_OUTPUT_DIR)


def fiche_template_path() -> Path:
    return Path(os.environ.get("POLICYBOT_FICHE_TEMPLATE") or _DEFAULT_FICHE_TEMPLATE)


def _first_tool(state: InterviewState):
    return state.tools[0] if state.tools else None


def _first_usage(state: InterviewState):
    return state.usages[0] if state.usages else None


def _findings(state: InterviewState, partie: str | None = None) -> list[CriterionFinding]:
    tool = _first_tool(state)
    findings = tool.arp.findings if tool and tool.arp else []
    return [item for item in findings if partie is None or item.partie == partie]


def _ordered_rows(
    findings: list[CriterionFinding],
    criteria: list[tuple[str, str, str]],
) -> list[dict]:
    by_key = {(item.category, item.criterion): item for item in findings}
    return [
        {
            "category": category,
            "criterion": criterion,
            "description": description,
            "finding": by_key.get((category, criterion)),
        }
        for category, criterion, description in criteria
    ]


def _group(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    groups: list[tuple[str, list[dict]]] = []
    for row in rows:
        if not groups or groups[-1][0] != row["category"]:
            groups.append((row["category"], []))
        groups[-1][1].append(row)
    return groups


def _format_french_date(value: object | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value).date()
        except ValueError:
            return value
    return f"{value.day} {_FRENCH_MONTHS[value.month - 1]} {value.year}"


def _source_type_label(source_type: str) -> str:
    return {
        "contractual": "Contractuelle",
        "official_technical": "Technique officielle",
        "secondary": "Secondaire",
        "unknown": "Non précisée",
    }.get(source_type, source_type.replace("_", " ").capitalize())


def _source_reference_label(url: str) -> str:
    parsed = urlsplit(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc and parts:
        return f"{parsed.netloc} / {parts[-1]}"
    return parsed.netloc or url


def _unique_sources(state: InterviewState) -> list[CriterionCitation]:
    seen: set[str] = set()
    result: list[CriterionCitation] = []
    for finding in _findings(state):
        for citation in finding.citations:
            if citation.url and citation.url not in seen:
                seen.add(citation.url)
                result.append(citation)
    return result


def _finding_observation(finding: CriterionFinding | None) -> str:
    if finding is None:
        return ""
    if finding.outcome != "ok" or not finding.answer:
        text = "Aucune source probante trouvée."
    else:
        text = finding.answer
        if finding.justification:
            text += f"\nJustification : {finding.justification}"
    if finding.rejected_citations:
        text += (
            f"\n{finding.rejected_citations} citation(s) non ancrée(s) rejetée(s)."
        )
    return text


def _context(state: InterviewState) -> dict:
    tool = _first_tool(state)
    arp = tool.arp if tool else None
    return {
        "state": state,
        "tool": tool,
        "arp": arp,
        "partie_a": _group(_ordered_rows(_findings(state, "A"), ARP_CRITERIA)),
        "partie_b": _group(_ordered_rows(_findings(state, "B"), USAGE_CRITERIA)),
        "sources": _unique_sources(state),
        "total_cost": arp.total_cost_dollars if arp else 0.0,
    }


def render_html(state: InterviewState) -> str:
    env = Environment(
        loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
        autoescape=select_autoescape(("html", "j2")),
    )
    return env.get_template("report.html.j2").render(**_context(state))


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _para(value: object | None, style):
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    content = escape(_text(value)).replace("\n", "<br/>")
    return Paragraph(content or " ", style)


def _make_reportlab_styles():
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    styles = getSampleStyleSheet()
    styles["Title"].fontSize = 22
    styles["Title"].leading = 26
    styles["Title"].textColor = colors.HexColor("#101827")
    styles["Heading2"].fontSize = 15
    styles["Heading2"].leading = 18
    styles["Heading2"].spaceBefore = 14
    styles["Heading2"].spaceAfter = 8
    styles["Heading2"].textColor = colors.HexColor("#2b6169")
    styles["Heading3"].fontSize = 11
    styles["Heading3"].leading = 14
    styles["Heading3"].spaceBefore = 10
    styles["Heading3"].spaceAfter = 6
    styles["BodyText"].fontSize = 9
    styles["BodyText"].leading = 12
    styles.add(ParagraphStyle(
        name="Small", parent=styles["BodyText"], fontSize=7.2, leading=8.6,
    ))
    styles.add(ParagraphStyle(
        name="Observation", parent=styles["Small"], fontSize=6.8, leading=8.1,
    ))
    styles.add(ParagraphStyle(
        name="SourceLink", parent=styles["Small"], fontSize=6.8, leading=8.2,
        textColor=colors.HexColor("#1d4ed8"),
    ))
    styles.add(ParagraphStyle(
        name="Footer", parent=styles["BodyText"], fontSize=7.5, leading=9,
        textColor=colors.HexColor("#667085"),
    ))
    return styles


def _basic_table(rows: list[list[object]], col_widths=None, repeat_rows: int = 1):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    table = Table(
        rows, colWidths=col_widths, hAlign="LEFT", repeatRows=repeat_rows,
        splitInRow=1,
    )
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


def _finding_flowables(finding: CriterionFinding | None, styles):
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    if finding is None:
        return []
    flowables = [_para(_finding_observation(finding), styles["Observation"])]
    for citation in finding.citations:
        target = escape(citation.deep_link or citation.url, {'"': "&quot;"})
        quote = escape(citation.text)
        label = escape(_source_type_label(citation.source_type))
        flowables.append(Paragraph(
            f'{label} — <link href="{target}"><u>« {quote} »</u></link>',
            styles["Observation"],
        ))
    return flowables


def _risk_table(groups: list[tuple[str, list[dict]]], styles, usage: bool = False):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    headers = [
        "Critère",
        "Risque évalué" if usage else "Description / question",
        "Risque inhérent",
        "Mesures de mitigation",
        "Risque résiduel",
        "Responsable",
        "Observations" if usage else "Observations / constats",
    ]
    rows: list[list[object]] = [[_para(header, styles["Small"]) for header in headers]]
    category_rows: list[int] = []
    for category, group_rows in groups:
        category_rows.append(len(rows))
        rows.append([_para(category, styles["Small"])] + [""] * 6)
        for row in group_rows:
            finding = row["finding"]
            rows.append([
                _para(row["criterion"], styles["Small"]),
                _para(row["description"], styles["Small"]),
                _para(finding.inherent_risk if finding else "", styles["Small"]),
                _para("", styles["Small"]),
                _para("", styles["Small"]),
                _para("", styles["Small"]),
                _finding_flowables(finding, styles),
            ])
    table = Table(
        rows, colWidths=[50, 145, 48, 110, 48, 58, 103], hAlign="LEFT",
        repeatRows=1, splitInRow=1,
    )
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d0d5dd")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef6f7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for row_index in category_rows:
        commands.extend([
            ("SPAN", (0, row_index), (-1, row_index)),
            ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#f8fafc")),
            ("TEXTCOLOR", (0, row_index), (-1, row_index), colors.HexColor("#2b6169")),
        ])
    table.setStyle(TableStyle(commands))
    return table


def _source_register(sources: list[CriterionCitation], styles):
    from reportlab.platypus import Paragraph
    from xml.sax.saxutils import escape

    rows = [[
        _para("Type", styles["Small"]),
        _para("Source", styles["Small"]),
        _para("Collectée le", styles["Small"]),
        _para("Date d'effet", styles["Small"]),
    ]]
    for source in sources:
        url = escape(source.url, {'"': "&quot;"})
        label = escape(_source_reference_label(source.url))
        rows.append([
            _para(_source_type_label(source.source_type), styles["Small"]),
            Paragraph(f'<link href="{url}"><u>{label}</u></link>', styles["SourceLink"]),
            _para(_format_french_date(source.collected_at), styles["Small"]),
            _para("Non précisée", styles["Small"]),
        ])
    return _basic_table(rows, [108, 398, 105, 89])


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColorRGB(0.4, 0.44, 0.52)
    canvas.drawCentredString(doc.pagesize[0] / 2, 10, f"PolicyBot - page {doc.page}")
    canvas.restoreState()


def render_pdf(state: InterviewState) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, SimpleDocTemplate, Spacer, TableStyle

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
    story = [
        _para("Rapport de recommandation - PolicyBot", styles["Title"]),
        Spacer(1, 8),
    ]
    disclaimer = _basic_table(
        [[_para(
            "PolicyBot fournit des constats et des niveaux de risque proposés; il "
            "n'autorise pas. La partie C doit être complétée et validée par "
            "l'autorité désignée.",
            styles["BodyText"],
        )]],
        [700],
        repeat_rows=0,
    )
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff5f5")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#f2b8b5")),
    ]))
    story.extend([disclaimer, Spacer(1, 10)])

    story.append(_para("Identification", styles["Heading2"]))
    tool_names = ", ".join(tool.name for tool in state.tools)
    story.append(_basic_table([
        [_para("Numéro demande", styles["BodyText"]), _para(state.request.numero, styles["BodyText"])],
        [_para("Outil évalué", styles["BodyText"]), _para(tool_names, styles["BodyText"])],
        [_para("Demandeur", styles["BodyText"]), _para(state.request.demandeur, styles["BodyText"])],
        [_para("Unité", styles["BodyText"]), _para(state.request.unite, styles["BodyText"])],
        [_para("Date", styles["BodyText"]), _para(_format_french_date(state.request.date), styles["BodyText"])],
    ], [150, 550]))

    story.append(_para("Partie A - Analyse des risques du produit (ARP)", styles["Heading2"]))
    story.append(_para(
        "L'ARP évalue l'outil en tant que produit, indépendamment des usages spécifiques.",
        styles["BodyText"],
    ))
    for tool in state.tools or [None]:
        story.append(_para(f"Outil : {tool.name if tool else ''}", styles["Heading3"]))
        offering = (
            tool.offering or (tool.arp.offering if tool and tool.arp else None)
            if tool else None
        )
        if offering:
            story.append(_para(
                f"Identité de l'offre contractuelle : {offering.display_label()}",
                styles["BodyText"],
            ))
        story.append(_risk_table(
            _group(_ordered_rows(
                [item for item in (tool.arp.findings if tool and tool.arp else []) if item.partie == "A"],
                ARP_CRITERIA,
            )),
            styles,
        ))
        story.append(Spacer(1, 8))

    story.append(_para("Partie B - Évaluation des risques par usage", styles["Heading2"]))
    usages = state.usages or [None]
    part_b_groups = _group(_ordered_rows(_findings(state, "B"), USAGE_CRITERIA))
    for index, usage in enumerate(usages, start=1):
        description = usage.description if usage else ""
        story.append(_para(f"Usage {index} : {description}", styles["Heading3"]))
        if usage:
            story.append(_para(
                f"Classification des données : {usage.data_classification or ''} | "
                f"Renseignements personnels : {'Oui' if usage.rens_personnels else 'Non'}",
                styles["BodyText"],
            ))
        story.append(_risk_table(part_b_groups, styles, usage=True))
        story.append(Spacer(1, 8))

    story.append(KeepTogether([
        _para("Partie C - Synthèse et décision", styles["Heading2"]),
        _para(
            "Section réservée à l'autorité désignée. Aucun résultat n'est calculé "
            "automatiquement par PolicyBot.",
            styles["BodyText"],
        ),
        _basic_table([
            [_para("Niveau de risque global", styles["BodyText"]), _para("", styles["BodyText"])],
            [_para("EFVP-R requise", styles["BodyText"]), _para("", styles["BodyText"])],
            [_para("Recommandation préliminaire", styles["BodyText"]), _para("", styles["BodyText"])],
            [_para("Conditions / restrictions proposées", styles["BodyText"]), _para("", styles["BodyText"])],
        ], [190, 510], repeat_rows=0),
    ]))

    sources = _unique_sources(state)
    if sources:
        story.append(_para("Sources contractuelles consultées", styles["Heading2"]))
        story.append(_para(
            "Liens consultés pour l'analyse. Chaque adresse est affichée une seule fois.",
            styles["BodyText"],
        ))
        story.append(_source_register(sources, styles))

    tool = _first_tool(state)
    total_cost = tool.arp.total_cost_dollars if tool and tool.arp else 0.0
    story.extend([
        Spacer(1, 10),
        _para(
            f"Coût total estimé des recherches Exa : {total_cost:.4f} $ US.",
            styles["Footer"],
        ),
        _para(
            "Rapport généré par PolicyBot — validation et autorisation par "
            "l'autorité désignée requises.",
            styles["Footer"],
        ),
    ])
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()


def write_pdf(
    state: InterviewState, output_dir: str | os.PathLike | None = None
) -> Path:
    directory = Path(output_dir) if output_dir is not None else pdf_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / pdf_filename(state)
    path.write_bytes(render_pdf(state))
    return path


def _w(tag: str) -> str:
    return f"{{{_WORD_NS}}}{tag}"


def _table_cell(table: ET.Element, row_index: int, cell_index: int) -> ET.Element:
    return table.findall(_w("tr"))[row_index].findall(_w("tc"))[cell_index]


def _set_cell_text(cell: ET.Element, value: object | None) -> None:
    text = _text(value)
    properties = cell.find(_w("tcPr"))
    for child in list(cell):
        cell.remove(child)
    if properties is not None:
        cell.append(properties)
    paragraph = ET.SubElement(cell, _w("p"))
    run = ET.SubElement(paragraph, _w("r"))
    for index, line in enumerate(text.splitlines() or [""]):
        if index:
            ET.SubElement(run, _w("br"))
        text_element = ET.SubElement(run, _w("t"))
        text_element.set(f"{{{_XML_NS}}}space", "preserve")
        text_element.text = line


def _set_table_value(
    table: ET.Element, row_index: int, value: object | None, cell_index: int = 1
) -> None:
    _set_cell_text(_table_cell(table, row_index, cell_index), value)


def _yes_no(value: bool) -> str:
    return "Oui" if value else "Non"


def _label(value: object | None, labels: dict[str, str]) -> str:
    return labels.get(_text(value), _text(value))


def _join_lines(values: list[str]) -> str:
    return "\n".join(value for value in values if value)


_IAG_TYPE_LABELS = {
    "publique": "IAG publique",
    "circuit_ferme": "IAG circuit fermé",
    "souveraine": "IAG souveraine",
    "gouvernementale": "IAG gouvernementale circuit fermé",
}
_NIVEAU_TI_LABELS = {
    "débutant": "Débutant",
    "intermédiaire": "Intermédiaire",
    "avancé": "Avancé",
}
_FORMATION_LABELS = {
    "aucune": "Aucune",
    "partielle": "Partielle",
    "complète": "Complète (MCN)",
}
_ACCES_LABELS = {"oui": "Oui", "non": "Non", "à vérifier": "À vérifier"}
_URGENCE_LABELS = {"faible": "Faible", "modérée": "Modérée", "élevée": "Élevée"}
_MODE_ACQUISITION_LABELS = {
    "achat_direct": "Achat direct",
    "seao": "Via SEAO",
    "appel_offres": "Via appel d'offres",
    "contrat_existant": "Contrat existant",
}


def _finding_by_id(state: InterviewState, criterion_id: str) -> CriterionFinding | None:
    return next((item for item in _findings(state) if item.id == criterion_id), None)


def _usage_nature(usage) -> str:
    if not usage:
        return ""
    description = _text(usage.raw_answers.get("data_description", ""))
    return description or _join_lines([
        usage.description,
        f"Classification : {usage.data_classification}" if usage.data_classification else "",
    ])


def _usage_mode_text(usage) -> str:
    modes = []
    if "prompt" in usage.mode:
        modes.append("Prompt traditionnel")
    if "api" in usage.mode:
        api_text = "Appels API"
        if usage.systemes_api_cibles:
            api_text += f" — systèmes cibles : {usage.systemes_api_cibles}"
        modes.append(api_text)
    return ", ".join(modes)


def _usage_description_text(usage) -> str:
    return _join_lines([
        usage.description,
        f"Fréquence : {usage.frequence_utilisation}" if usage.frequence_utilisation else "",
        f"Nombre d'utilisateurs : {usage.nb_utilisateurs}"
        if usage.nb_utilisateurs is not None else "",
    ])


def _fill_identification_table(table: ET.Element, state: InterviewState) -> None:
    _set_table_value(table, 0, state.request.numero)
    _set_table_value(table, 1, state.request.date.isoformat() if state.request.date else "")
    _set_table_value(table, 2, state.request.demandeur)
    _set_table_value(table, 3, state.request.unite)


def _fill_tools_table(table: ET.Element, state: InterviewState) -> None:
    for index, tool in enumerate(state.tools[:2]):
        offset = index * 4
        offering = tool.offering or (tool.arp.offering if tool.arp else None)
        _set_table_value(table, offset, tool.name)
        _set_table_value(table, offset + 1, _label(tool.iag_type, _IAG_TYPE_LABELS))
        _set_table_value(
            table, offset + 2,
            offering.display_label() if offering else tool.version_plan_tarifaire,
        )
        _set_table_value(table, offset + 3, tool.vendor or "")


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
    usage = _first_usage(state)
    residency = _finding_by_id(state, "A01")
    training = _finding_by_id(state, "A04")
    _set_table_value(table, 0, "Oui" if state.usages else "")
    _set_table_value(table, 1, _usage_nature(usage))
    _set_table_value(table, 2, residency.answer if residency else "")
    _set_table_value(
        table, 3,
        _yes_no(any(item.rens_personnels for item in state.usages)) if state.usages else "",
    )
    _set_table_value(table, 4, training.answer if training else "")
    _set_table_value(
        table, 5,
        "Voir le rapport PolicyBot et les sources contractuelles consultées."
        if _findings(state) else "",
    )


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
    found = [
        f"{item.criterion} : {item.answer}"
        for item in _findings(state)
        if item.outcome == "ok" and item.answer
    ]
    missing = [
        row["criterion"]
        for row in _ordered_rows(_findings(state, "B"), USAGE_CRITERIA)
        if row["finding"] is None
    ]
    _set_table_value(table, 0, _join_lines(found))
    _set_table_value(table, 1, "")
    _set_table_value(
        table, 2,
        "Critères non recherchés à compléter par l'autorité désignée : "
        + ", ".join(missing)
        if missing else "",
    )
    _set_table_value(table, 3, "")
    _set_table_value(
        table, 4,
        "Compléter la partie C du rapport, puis faire valider la qualification "
        "et les mesures par la Direction des systèmes d'information.",
    )


def _fill_fiche_document(document_xml: bytes, state: InterviewState) -> bytes:
    root = ET.fromstring(document_xml)
    tables = root.findall(f".//{_w('tbl')}")
    if len(tables) < 8:
        raise RuntimeError(
            "Le gabarit Word de fiche de qualification ne contient pas les "
            "8 tableaux attendus."
        )
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
        raise RuntimeError(f"Gabarit Word introuvable : {template}")
    buffer = BytesIO()
    with zipfile.ZipFile(template, "r") as source:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "word/document.xml":
                    data = _fill_fiche_document(data, state)
                target.writestr(item, data)
    return buffer.getvalue()


def write_docx(
    state: InterviewState, output_dir: str | os.PathLike | None = None
) -> Path:
    directory = Path(output_dir) if output_dir is not None else docx_output_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / docx_filename(state)
    path.write_bytes(render_docx(state))
    return path


def html_to_pdf(html: str) -> bytes:
    from weasyprint import HTML
    return HTML(string=html).write_pdf()
