from __future__ import annotations
import os
from jinja2 import Environment, FileSystemLoader, select_autoescape
from policybot.models import InterviewState

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_html(state: InterviewState) -> str:
    return _env.get_template("report.html.j2").render(state=state)


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML  # optional dependency
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint non installé. `pip install policybot[pdf]` "
            "(nécessite les bibliothèques GTK sur Windows)."
        ) from exc
    return HTML(string=html).write_pdf()  # pragma: no cover
