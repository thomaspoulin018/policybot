# policybot/web/routes.py
from __future__ import annotations
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

KNOWN_TOOLS = ["ChatGPT", "ChatGPT Pro", "Claude.ai", "Perplexity", "Microsoft Copilot Entreprise"]

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
        "active_step": "outil", "known_tools": KNOWN_TOOLS,
    })
