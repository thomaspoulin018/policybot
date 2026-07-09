# tests/test_golden_scenarios.py
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.report.renderer import render_html


def _terms_get(url):
    return "<html><body>content may be used to train models</body></html>"


def test_slide5_chatgpt_protege_b_is_refused_and_report_flags_it(tmp_path):
    """Slide 5: ChatGPT/Perplexity + Protégé B strategic/financial data ⇒ INTERDIT."""
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.95},
        {"trains_on_input": "yes", "data_retention": "indefinite", "data_residency": "us",
         "sub_processors": "undisclosed", "human_review": "no", "extraction_confidence": 0.85},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-006", demandeur="VRAF", unite="Finances"),
        tool_name="ChatGPT Pro",
        usage_inputs=[{
            "description": "Résumer des rapports financiers stratégiques",
            "data_description": "rapports financiers stratégiques et renseignements personnels",
            "automated_decisions": False, "mode": ["prompt"],
            "result_use": ["Prise de décision"],
        }],
    )
    usage = state.usages[0]
    assert usage.data_classification == "Protégé B"
    assert usage.matrix_result == "INTERDIT"
    assert usage.verdict == "Refuser"
    assert usage.efvpr_required is True
    assert state.result_global.recommendation == "Refuser"

    html = render_html(state)
    assert "Identification" in html
    assert "Partie A — Analyse des risques du produit (ARP)" in html
    assert "Partie B — Évaluation des risques par usage" in html
    assert "Partie C — Synthèse et décision" in html
    assert "Refuser" in html
    assert "ÉFVP-R requise" in html
    assert "requiert validation et autorisation par l'autorité désignée" in html
