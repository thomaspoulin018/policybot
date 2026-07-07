from policybot.models import InterviewState, RequestInfo, Usage, ToolRef, GlobalResult
from policybot.report.renderer import render_html


def _state():
    return InterviewState(
        interview_id="i1",
        request=RequestInfo(numero="IAG-2026-001", demandeur="Jean Test", unite="VRAF"),
        tools=[ToolRef(name="ChatGPT", iag_type="publique")],
        usages=[Usage(description="Résumer des rapports", data_classification="Protégé B",
                      matrix_result="INTERDIT", verdict="Refuser", risk_level="Critique",
                      conditions=["Combinaison interdite."])],
        result_global=GlobalResult(risk_level="Critique", recommendation="Refuser",
                                   efvpr_required=False),
    )


def test_render_contains_request_and_verdict():
    html = render_html(_state())
    assert "IAG-2026-001" in html
    assert "Jean Test" in html
    assert "Refuser" in html
    assert "Protégé B" in html


def test_render_contains_disclaimer_footer():
    html = render_html(_state())
    assert "requiert validation et autorisation par l'autorité désignée" in html
