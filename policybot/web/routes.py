# policybot/web/routes.py
from __future__ import annotations
import logging
import os
import uuid
from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from policybot.classify.tool_registry import lookup_tool
from policybot.classify.tool_type import classify_tool_type, tool_type_question
from policybot.interview.questions import data_description_question, usage_details_question
from policybot.models import RequestInfo, QualificationProfile
from policybot.interview.orchestrator import Interview
from policybot.preapproved.known_tools import load_known_tools
from policybot.report.renderer import render_html
from policybot.web.ai_assist import guess_mode, guess_tool_type, suggest_options, IAG_TYPE_LABELS, LABEL_TO_IAG_TYPE
from policybot.web.wizard_state import WizardState, compose_description

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)
logger = logging.getLogger(__name__)

router = APIRouter()


def _group_form(form) -> dict:
    grouped: dict[str, object] = {}
    for key in dict.fromkeys(form.keys()):
        values = form.getlist(key)
        if not values:
            continue
        grouped[key] = values if len(values) > 1 else values[0]
    return grouped


@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return templates.TemplateResponse(request, "wizard_outil.html.j2", {
        "active_step": "outil", "known_tools": load_known_tools(),
    })


@router.post("/wizard/outil", response_class=HTMLResponse)
async def wizard_outil(request: Request):
    form = _group_form(await request.form())
    tool_name = (form.get("tool_name") or form.get("tool_name_other") or "").strip()
    version_plan_tarifaire = form.get("version_plan_tarifaire", "") or ""

    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        state = WizardState(tool_name=tool_name, version_plan_tarifaire=version_plan_tarifaire)
        return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
            "active_step": "profil_utilisateurs",
            "hidden_fields": state.to_hidden_fields(),
        })

    llm = request.app.state.interview.llm
    try:
        guessed_type = guess_tool_type(tool_name, llm)
    except Exception:
        guessed_type = None
    guessed_label = IAG_TYPE_LABELS.get(guessed_type) if guessed_type else None
    return templates.TemplateResponse(request, "wizard_tool_type.html.j2", {
        "active_step": "outil",
        "question": tool_type_question(), "tool_name": tool_name,
        "guessed_label": guessed_label,
        "version_plan_tarifaire": version_plan_tarifaire,
    })


@router.post("/wizard/outil/type", response_class=HTMLResponse)
async def wizard_outil_type(request: Request):
    form = _group_form(await request.form())
    tool_name = form.get("tool_name", "") or ""
    tool_type_label = form.get("tool_type", "") or ""
    tool_type_override = LABEL_TO_IAG_TYPE.get(tool_type_label)
    version_plan_tarifaire = form.get("version_plan_tarifaire", "") or ""
    state = WizardState(tool_name=tool_name, tool_type_override=tool_type_override,
                         version_plan_tarifaire=version_plan_tarifaire)
    return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
        "active_step": "profil_utilisateurs",
        "hidden_fields": state.to_hidden_fields(),
    })


@router.post("/wizard/profil-utilisateurs", response_class=HTMLResponse)
async def wizard_profil_utilisateurs_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_donnees.html.j2", {
        "active_step": "donnees",
        "hidden_fields": state.to_hidden_fields(),
        "question": data_description_question(),
    })


@router.post("/wizard/donnees", response_class=HTMLResponse)
async def wizard_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": state.to_hidden_fields(),
    })


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


@router.post("/wizard/usage", response_class=HTMLResponse)
async def wizard_usage_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_resultats.html.j2", {
        "active_step": "resultats",
        "hidden_fields": state.to_hidden_fields(),
        "question": usage_details_question(),
    })


@router.post("/wizard/resultats", response_class=HTMLResponse)
async def wizard_resultats_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return templates.TemplateResponse(request, "wizard_contexte_affaires.html.j2", {
        "active_step": "contexte_affaires",
        "hidden_fields": state.to_hidden_fields(),
    })


def _as_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@router.post("/wizard/contexte-affaires", response_class=HTMLResponse)
async def wizard_contexte_affaires_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    description = compose_description(state.data_checked, state.data_free_text)
    result_use = list(state.result_use_checked)
    if state.result_use_free_text:
        result_use.append(state.result_use_free_text)
    usage_input = {
        "description": state.usage_description,
        "data_description": description,
        "automated_decisions": state.automated_decisions,
        "mode": [state.mode] if state.mode else ["prompt"],
        "result_use": result_use,
        "frequence_utilisation": state.frequence_utilisation,
        "nb_utilisateurs": _as_int(state.nb_utilisateurs),
        "systemes_api_cibles": state.systemes_api_cibles,
    }
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
            request=RequestInfo(numero=numero),
            tool_name=state.tool_name,
            usage_inputs=[usage_input],
            iag_type_override=state.tool_type_override,
            qualification=qualification,
            tool_version_plan_tarifaire=state.version_plan_tarifaire,
        )
    except Exception:
        logger.exception("wizard/contexte-affaires assess failed for tool_name=%r numero=%s", state.tool_name, numero)
        return templates.TemplateResponse(request, "error.html.j2", {
            "active_step": "contexte_affaires",
        }, status_code=502)
    report_html = render_html(result_state)
    return templates.TemplateResponse(request, "resultat.html.j2", {
        "active_step": "resultat", "report_html": report_html,
    })
