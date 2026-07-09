from __future__ import annotations
import os
from itertools import groupby
from jinja2 import Environment, FileSystemLoader, select_autoescape
from policybot.models import InterviewState, RiskFactor
from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA

_TEMPLATES = os.path.join(os.path.dirname(__file__), "templates")
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES, encoding="utf-8"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _merge_rows(
    criteria_table: list[tuple[str, str, str]],
    factors: list[RiskFactor],
) -> list[dict]:
    by_criterion = {factor.criterion: factor for factor in factors}
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
            "observations": factor.observations if factor else "",
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
            "groups": _group_by_category(
                _merge_rows(ARP_CRITERIA, tool.arp.criteria if tool.arp else [])
            ),
        }
        for tool in state.tools
    ]
    usage_tables = [
        {
            "usage": usage,
            "index": index + 1,
            "groups": _group_by_category(_merge_rows(USAGE_CRITERIA, usage.partie_b)),
        }
        for index, usage in enumerate(state.usages)
    ]
    return _env.get_template("report.html.j2").render(
        state=state,
        arp_tables=arp_tables,
        usage_tables=usage_tables,
    )


def html_to_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML  # optional dependency
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "WeasyPrint non installé. `pip install policybot[pdf]` "
            "(nécessite les bibliothèques GTK sur Windows)."
        ) from exc
    return HTML(string=html).write_pdf()  # pragma: no cover
