# policybot/web/routes.py
from __future__ import annotations
import logging
import os
import unicodedata
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from policybot.classify.tool_registry import lookup_tool
from policybot.classify.tool_type import classify_tool_type, tool_type_question
from policybot.interview.questions import data_description_question, usage_details_question
from policybot.models import RequestInfo, QualificationProfile
from policybot.interview.orchestrator import Interview
from policybot.preapproved.known_tools import load_known_tools
from policybot.report.renderer import (
    docx_output_dir,
    pdf_output_dir,
    render_html,
    write_docx,
    write_pdf,
)
from policybot.web.ai_assist import guess_mode, guess_tool_type, suggest_options, IAG_TYPE_LABELS, LABEL_TO_IAG_TYPE
from policybot.web.wizard_state import (
    WizardState,
    WizardUsageDraft,
    compose_description,
    demo_wizard_scenarios,
    demo_wizard_state,
)

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)
logger = logging.getLogger(__name__)

router = APIRouter()

PROFILE_FIELDS = {
    "nb_utilisateurs_vises", "fonctions_roles", "niveau_maitrise_ti",
    "formation_iag_recue", "acces_protege_a_ou_plus",
}
DATA_FIELDS = {"data_checked", "data_free_text"}
USAGE_FIELDS = {
    "usage_description", "mode", "frequence_utilisation",
    "nb_utilisateurs", "systemes_api_cibles",
}
RESULT_FIELDS = {"result_use_checked", "result_use_free_text", "automated_decisions"}
CONTEXT_FIELDS = {
    "besoin_affaires", "gains_qualitatifs", "gains_quantitatifs",
    "alternatives_considerees", "urgence_percue", "cout_annuel_par_utilisateur",
    "cout_total_annuel", "mode_acquisition", "duree_contrat", "responsable_budgetaire",
}

_FACT_LABELS = {
    "training_default": "Utilisation des données pour l’entraînement",
    "opt_out_available": "Option de retrait de l’entraînement",
    "opt_out_confirmed_enabled": "Option de retrait confirmée active",
    "data_retention": "Conservation des données",
    "data_residency": "Localisation des données",
    "sub_processors": "Sous-traitants",
    "provider_human_access": "Accès humain du fournisseur",
    "encryption_standard": "Chiffrement des données",
    "ip_ownership": "Propriété intellectuelle",
    "applicable_law": "Juridiction applicable",
    "foreign_vendor_dependency": "Dépendance envers un fournisseur étranger",
    "contract_prohibits_reuse": "Interdiction contractuelle de réutilisation",
    "authentication_support": "Authentification",
    "audit_logging": "Journalisation",
    "institutional_terms_available": "Conditions institutionnelles",
    "dpa_available": "Accord de traitement des données",
    "institutional_use_restricted": "Restriction d’usage institutionnel",
    "quebec_higher_ed_license": "Compatibilité avec l’enseignement supérieur québécois",
    "incident_response": "Gestion des incidents",
}


def _hidden_fields_for(state: WizardState, current_fields: set[str]) -> list[tuple[str, str]]:
    return [(name, value) for name, value in state.to_hidden_fields() if name not in current_fields]


def _iag_type_from_label(label: str) -> str | None:
    direct = LABEL_TO_IAG_TYPE.get(label)
    if direct:
        return direct
    key = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode().lower()
    if key == "iag publique":
        return "publique"
    if key.startswith("iag circuit ferm"):
        return "circuit_ferme"
    if key == "iag souveraine":
        return "souveraine"
    if key == "iag gouvernementale":
        return "gouvernementale"
    return None

def _group_form(form) -> dict:
    grouped: dict[str, object] = {}
    for key in dict.fromkeys(form.keys()):
        values = form.getlist(key)
        if not values:
            continue
        grouped[key] = values if len(values) > 1 else values[0]
    return grouped


def _required_text(value: object, message: str) -> str | None:
    return message if not str(value or "").strip() else None


def _safe_source_url(value: str | None) -> str | None:
    """Expose uniquement un lien Web sûr provenant d'une preuve collectée."""
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _contract_evidence_for_user(result_state) -> list[dict[str, str]]:
    """Prépare les preuves acceptées pour la synthèse lisible par l'employé."""
    evidence: list[dict[str, str]] = []
    for tool in result_state.tools:
        if tool.arp is None:
            continue
        for field_name, proof in tool.arp.contract_facts.evidence.items():
            source_url = _safe_source_url(proof.source_url)
            if proof.outcome != "accepted" or not proof.quote or not source_url:
                continue
            evidence.append({
                "tool_name": tool.name,
                "label": _FACT_LABELS.get(field_name, field_name.replace("_", " ")),
                "quote": proof.quote,
                "source_url": source_url,
            })
    return evidence


def _render_outil(request: Request, state: WizardState, errors: dict[str, str] | None = None):
    return templates.TemplateResponse(request, "wizard_outil.html.j2", {
        "active_step": "outil",
        "known_tools": load_known_tools(),
        "demo_scenarios": demo_wizard_scenarios(),
        "state": state,
        "errors": errors or {},
    }, status_code=422 if errors else 200)


def _render_profil_utilisateurs(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
        "active_step": "profil_utilisateurs",
        "hidden_fields": _hidden_fields_for(state, PROFILE_FIELDS),
        "state": state,
    })


def _render_donnees(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_donnees.html.j2", {
        "active_step": "donnees",
        "hidden_fields": _hidden_fields_for(state, DATA_FIELDS),
        "state": state,
        "question": data_description_question(),
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_usage(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": _hidden_fields_for(state, USAGE_FIELDS),
        "state": state,
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_resultats(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_resultats.html.j2", {
        "active_step": "resultats",
        "hidden_fields": _hidden_fields_for(state, RESULT_FIELDS),
        "state": state,
        "question": usage_details_question(),
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_contexte_affaires(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_contexte_affaires.html.j2", {
        "active_step": "contexte_affaires",
        "hidden_fields": _hidden_fields_for(state, CONTEXT_FIELDS),
        "state": state,
    })


@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return _render_outil(request, WizardState())


@router.post("/wizard/test-prefill", response_class=HTMLResponse)
async def wizard_test_prefill(request: Request):
    form = _group_form(await request.form())
    scenario_id = str(form.get("scenario_id") or "public_permitted")
    try:
        state = demo_wizard_state(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Scénario de test inconnu") from None
    return _render_contexte_affaires(request, state)


@router.post("/wizard/goto/outil", response_class=HTMLResponse)
async def wizard_goto_outil(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_outil(request, state)


@router.post("/wizard/outil", response_class=HTMLResponse)
async def wizard_outil(request: Request):
    form = _group_form(await request.form())
    tool_name = str(form.get("tool_name") or form.get("tool_name_other") or "").strip()
    demandeur = str(form.get("demandeur", "") or "").strip()
    unite = str(form.get("unite", "") or "").strip()
    version_plan_tarifaire = str(form.get("version_plan_tarifaire", "") or "").strip()
    deployment_mode = str(form.get("deployment_mode", "") or "").strip()
    contract_type = str(form.get("contract_type", "") or "").strip()
    contract_version = str(form.get("contract_version", "") or "").strip()
    jurisdiction = str(form.get("jurisdiction", "") or "").strip()
    contract_effective_date = str(form.get("contract_effective_date", "") or "").strip()
    state = WizardState(tool_name=tool_name, demandeur=demandeur, unite=unite,
                        version_plan_tarifaire=version_plan_tarifaire,
                        deployment_mode=deployment_mode,
                        contract_type=contract_type,
                        contract_version=contract_version,
                        jurisdiction=jurisdiction,
                        contract_effective_date=contract_effective_date)
    errors = {
        name: error for name, error in {
            "tool_name": _required_text(tool_name, "Indiquez le nom de l'outil d'IA generative."),
            "demandeur": _required_text(demandeur, "Indiquez le nom du demandeur."),
            "unite": _required_text(unite, "Indiquez l'unite administrative du demandeur."),
        }.items() if error
    }
    if errors:
        return _render_outil(request, state, errors)
    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        return _render_profil_utilisateurs(request, state)
    llm = request.app.state.interview.llm
    try:
        guessed_type = guess_tool_type(tool_name, llm)
    except Exception:
        guessed_type = None
    return templates.TemplateResponse(request, "wizard_tool_type.html.j2", {
        "active_step": "outil", "question": tool_type_question(), "tool_name": tool_name,
        "guessed_label": IAG_TYPE_LABELS.get(guessed_type) if guessed_type else None,
        "version_plan_tarifaire": version_plan_tarifaire, "state": state,
    })


@router.post("/wizard/outil/type", response_class=HTMLResponse)
async def wizard_outil_type(request: Request):
    form = _group_form(await request.form())
    tool_name = form.get("tool_name", "") or ""
    demandeur = form.get("demandeur", "") or ""
    unite = form.get("unite", "") or ""
    tool_type_label = form.get("tool_type", "") or ""
    tool_type_override = _iag_type_from_label(tool_type_label)
    version_plan_tarifaire = form.get("version_plan_tarifaire", "") or ""
    state = WizardState(tool_name=tool_name, demandeur=demandeur, unite=unite,
                         tool_type_override=tool_type_override,
                         version_plan_tarifaire=version_plan_tarifaire,
                         deployment_mode=form.get("deployment_mode", "") or "",
                         contract_type=form.get("contract_type", "") or "",
                         contract_version=form.get("contract_version", "") or "",
                         jurisdiction=form.get("jurisdiction", "") or "",
                         contract_effective_date=form.get("contract_effective_date", "") or "")
    return _render_profil_utilisateurs(request, state)


@router.post("/wizard/goto/profil-utilisateurs", response_class=HTMLResponse)
async def wizard_goto_profil_utilisateurs(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_profil_utilisateurs(request, state)


@router.post("/wizard/profil-utilisateurs", response_class=HTMLResponse)
async def wizard_profil_utilisateurs_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_donnees(request, state)


@router.post("/wizard/goto/donnees", response_class=HTMLResponse)
async def wizard_goto_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_donnees(request, state)


@router.post("/wizard/donnees", response_class=HTMLResponse)
async def wizard_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_usage(request, state)


@router.post("/wizard/suggest/donnees", response_class=HTMLResponse)
async def suggest_donnees(request: Request):
    form = _group_form(await request.form())
    free_text = form.get("data_free_text", "") or ""
    options = []
    if free_text:
        llm = request.app.state.interview.llm
        try:
            options = suggest_options(data_description_question(), free_text, llm)
        except Exception:
            options = []
    return templates.TemplateResponse(request, "_suggest_fragment.html.j2", {
        "options": options, "field_name": "data_checked",
    })


@router.post("/wizard/mode-guess", response_class=HTMLResponse)
async def mode_guess(request: Request):
    form = _group_form(await request.form())
    description = form.get("usage_description", "") or ""
    guessed = "prompt"
    if description:
        llm = request.app.state.interview.llm
        try:
            guessed = guess_mode(description, llm)
        except Exception:
            guessed = "prompt"
    return templates.TemplateResponse(request, "wizard_mode_fragment.html.j2", {
        "guessed_mode": guessed,
    })


@router.post("/wizard/suggest/usage", response_class=HTMLResponse)
async def suggest_usage(request: Request):
    form = _group_form(await request.form())
    free_text = form.get("result_use_free_text", "") or ""
    options = []
    if free_text:
        llm = request.app.state.interview.llm
        try:
            options = suggest_options(usage_details_question(), free_text, llm)
        except Exception:
            options = []
    return templates.TemplateResponse(request, "_suggest_fragment.html.j2", {
        "options": options, "field_name": "result_use_checked",
    })


@router.post("/wizard/goto/usage", response_class=HTMLResponse)
async def wizard_goto_usage(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_usage(request, state)


@router.post("/wizard/usage", response_class=HTMLResponse)
async def wizard_usage_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_resultats(request, state)


@router.post("/wizard/goto/resultats", response_class=HTMLResponse)
async def wizard_goto_resultats(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_resultats(request, state)


@router.post("/wizard/resultats", response_class=HTMLResponse)
async def wizard_resultats_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    if form.get("usage_action") == "add_usage":
        state = state.with_current_usage_saved().cleared_current_usage()
        return _render_donnees(request, state)
    return _render_contexte_affaires(request, state)


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _usage_input_from_draft(draft: WizardUsageDraft) -> dict:
    result_use = list(draft.result_use_checked)
    if draft.result_use_free_text:
        result_use.append(draft.result_use_free_text)
    return {
        "description": draft.usage_description,
        "data_description": compose_description(draft.data_checked, draft.data_free_text),
        "automated_decisions": draft.automated_decisions,
        "mode": [draft.mode] if draft.mode else ["prompt"],
        "result_use": result_use,
        "frequence_utilisation": draft.frequence_utilisation,
        "nb_utilisateurs": _as_int(draft.nb_utilisateurs),
        "systemes_api_cibles": draft.systemes_api_cibles,
    }


def _usage_inputs_from_state(state: WizardState) -> list[dict]:
    usage_inputs = [_usage_input_from_draft(draft) for draft in state.saved_usages]
    if state.has_current_usage():
        usage_inputs.append(_usage_input_from_draft(state.current_usage_draft()))
    return usage_inputs

@router.post("/wizard/goto/contexte-affaires", response_class=HTMLResponse)
async def wizard_goto_contexte_affaires(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_contexte_affaires(request, state)


@router.post("/wizard/contexte-affaires", response_class=HTMLResponse)
async def wizard_contexte_affaires_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    usage_inputs = _usage_inputs_from_state(state)
    qualification = QualificationProfile(
        nb_utilisateurs_vises=_as_int(state.nb_utilisateurs_vises),
        fonctions_roles=state.fonctions_roles,
        niveau_maitrise_ti=state.niveau_maitrise_ti or None,
        formation_iag_recue=state.formation_iag_recue or None,
        acces_protege_a_ou_plus=state.acces_protege_a_ou_plus or None,
        besoin_affaires=state.besoin_affaires,
        gains_qualitatifs=state.gains_qualitatifs,
        gains_quantitatifs=state.gains_quantitatifs,
        alternatives_considerees=state.alternatives_considerees,
        urgence_percue=state.urgence_percue or None,
        cout_annuel_par_utilisateur=state.cout_annuel_par_utilisateur,
        cout_total_annuel=state.cout_total_annuel,
        mode_acquisition=state.mode_acquisition or None,
        duree_contrat=state.duree_contrat,
        responsable_budgetaire=state.responsable_budgetaire,
    )
    itv: Interview = request.app.state.interview
    numero = f"IAG-{date.today():%Y}-{uuid.uuid4().hex[:6]}"
    try:
        result_state = itv.assess(
            request=RequestInfo(numero=numero, demandeur=state.demandeur, unite=state.unite),
            tool_name=state.tool_name,
            usage_inputs=usage_inputs,
            iag_type_override=state.tool_type_override,
            qualification=qualification,
            tool_version_plan_tarifaire=state.version_plan_tarifaire,
            deployment_mode=state.deployment_mode or None,
            contract_type=state.contract_type or None,
            contract_version=state.contract_version or None,
            jurisdiction=state.jurisdiction or None,
            contract_effective_date=(
                date.fromisoformat(state.contract_effective_date)
                if state.contract_effective_date else None
            ),
        )
    except Exception:
        logger.exception("wizard/contexte-affaires assess failed for tool_name=%r numero=%s", state.tool_name, numero)
        return templates.TemplateResponse(request, "error.html.j2", {
            "active_step": "contexte_affaires",
        }, status_code=502)
    report_html = render_html(result_state)
    pdf_path = None
    pdf_error = None
    docx_path = None
    docx_error = None
    try:
        pdf_path = write_pdf(result_state)
    except Exception as exc:
        logger.warning("PDF export failed for numero=%s", numero, exc_info=True)
        pdf_error = str(exc)
    try:
        docx_path = write_docx(result_state)
    except Exception as exc:
        logger.warning("DOCX export failed for numero=%s", numero, exc_info=True)
        docx_error = str(exc)
    return templates.TemplateResponse(request, "resultat.html.j2", {
        "active_step": "resultat",
        "report_html": report_html,
        "recommendation": result_state.result_global.recommendation,
        "contract_evidence": _contract_evidence_for_user(result_state),
        "pdf_filename": pdf_path.name if pdf_path else None,
        "pdf_error": pdf_error,
        "docx_filename": docx_path.name if docx_path else None,
        "docx_error": docx_error,
    })


@router.get("/output/pdf/{filename}")
def download_result_pdf(filename: str):
    if Path(filename).name != filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=404)
    directory = pdf_output_dir().resolve()
    path = (directory / filename).resolve()
    try:
        path.relative_to(directory)
    except ValueError:
        raise HTTPException(status_code=404) from None
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=filename)

@router.get("/output/docx/{filename}")
def download_result_docx(filename: str):
    if Path(filename).name != filename or not filename.endswith(".docx"):
        raise HTTPException(status_code=404)
    directory = docx_output_dir().resolve()
    path = (directory / filename).resolve()
    try:
        path.relative_to(directory)
    except ValueError:
        raise HTTPException(status_code=404) from None
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
    )
