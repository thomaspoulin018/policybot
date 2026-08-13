from __future__ import annotations

from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

from policybot.models import CriterionFinding, InterviewState


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
    """Prefix the timestamp with the request number to avoid collisions."""
    numero = _safe_filename(state.request.numero) if state.request.numero else "policybot"
    return f"{numero}_{datetime.now():{_FILENAME_TIMESTAMP_FORMAT}}"


def docx_filename(state: InterviewState) -> str:
    return f"{_filename_stem(state)}-fiche.docx"


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
    findings = tool.findings if tool else []
    return [item for item in findings if partie is None or item.partie == partie]


def _ordered_rows(findings: list[CriterionFinding], criteria) -> list[dict]:
    by_id = {item.id: item for item in findings}
    return [
        {
            "id": definition.id,
            "category": definition.category,
            "criterion": definition.criterion,
            "description": definition.question,
            "finding": by_id.get(definition.id),
        }
        for definition in criteria
    ]


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
        "official": "Officielle",
        "other": "Autre",
        "unknown": "Non précisée",
    }.get(source_type, source_type.replace("_", " ").capitalize())


def _text(value: object | None) -> str:
    return "" if value is None else str(value)


def _w(tag: str) -> str:
    return f"{{{_WORD_NS}}}{tag}"


def _table_cell(table: ET.Element, row_index: int, cell_index: int) -> ET.Element:
    return table.findall(_w("tr"))[row_index].findall(_w("tc"))[cell_index]


def _cell_text(cell: ET.Element) -> str:
    return " ".join(
        "".join(node.text or "" for node in paragraph.iter(_w("t"))).strip()
        for paragraph in cell.findall(_w("p"))
    ).strip()


def _normalized_heading(value: str) -> str:
    """Neutralise casse, accents, espaces insécables, tirets et apostrophes."""
    folded = unicodedata.normalize("NFKD", value.replace("\xa0", " "))
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    for dash in ("—", "–", "‑"):
        folded = folded.replace(dash, "-")
    for quote in ("’", "‘", "`"):
        folded = folded.replace(quote, "'")
    return " ".join(folded.casefold().split())


def _table_by_heading(tables: list[ET.Element], heading: str) -> ET.Element:
    wanted = _normalized_heading(heading)
    for table in tables:
        rows = table.findall(_w("tr"))
        if not rows:
            continue
        cells = rows[0].findall(_w("tc"))
        if cells and _normalized_heading(_cell_text(cells[0])).startswith(wanted):
            return table
    raise RuntimeError(
        "Le gabarit Word de fiche de qualification ne contient aucun tableau "
        f"commençant par « {heading} »."
    )


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
        offering = tool.offering
        _set_table_value(table, offset, tool.name)
        _set_table_value(table, offset + 1, _label(tool.iag_type, _IAG_TYPE_LABELS))
        _set_table_value(
            table,
            offset + 2,
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
    _set_table_value(
        table, 0,
        q.nb_utilisateurs_vises if q.nb_utilisateurs_vises is not None else "",
    )
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
        "Voir la grille d'évaluation et les sources contractuelles consultées."
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


# La section 8 (« Points de conformité identifiés ») reste volontairement
# vierge : elle est complétée par le responsable SI, pas par PolicyBot.
_FICHE_TABLES = (
    ("Numéro de demande", _fill_identification_table),
    ("Outil 1", _fill_tools_table),
    ("Description de l'usage", _fill_usages_table),
    ("Nombre d'utilisateurs visés", _fill_profile_table),
    ("L'outil accède-t-il à des données institutionnelles", _fill_data_table),
    ("Problème ou besoin d'affaires adressé", _fill_value_table),
    ("Coût estimé", _fill_finance_table),
)


def _fill_fiche_document(document_xml: bytes, state: InterviewState) -> bytes:
    root = ET.fromstring(document_xml)
    tables = root.findall(f".//{_w('tbl')}")
    for heading, fill in _FICHE_TABLES:
        fill(_table_by_heading(tables, heading), state)
    section_8 = _table_by_heading(tables, "Points de conformité identifiés")
    for row_index in range(len(section_8.findall(_w("tr")))):
        _set_table_value(section_8, row_index, "")
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
