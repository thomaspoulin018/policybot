from html import unescape
from policybot.models import InterviewState, RequestInfo, Usage, ToolRef, GlobalResult, ContractFacts
from policybot.contract.arp import build_arp
from policybot.grille.engine import evaluate_usage
from policybot.report.renderer import render_html


def _state():
    facts = ContractFacts(
        trains_on_input="yes",
        data_residency="us",
        applicable_law="foreign",
        foreign_vendor_dependency="yes",
        contract_prohibits_reuse="no",
        encryption_standard="none",
        reentraining_opt_out="no",
        ip_ownership="vendor",
    )
    arp = build_arp("ChatGPT", "publique", facts)
    usage = evaluate_usage(
        Usage(description="Résumer des rapports", data_classification="Non classifié"),
        ContractFacts(trains_on_input="no"),
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


def test_render_contains_request_and_verdict():
    html = unescape(render_html(_state()))
    assert "IAG-2026-001" in html
    assert "ChatGPT" in html
    assert "Refuser" in html
    assert "Non classifié" in html


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


def test_render_contains_partie_c_conditions():
    state = _state()
    state.result_global.conditions = ["Vérifier l'hébergement des données au Québec."]
    html = unescape(render_html(state))
    assert "Vérifier l'hébergement des données au Québec." in html
