# tests/test_golden_scenarios.py
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.report.renderer import render_html
from tests.helpers.arp_fixtures import exa_evidence


_GOLDEN_TERMS = (
    "The vendor's terms of service and privacy policy describe this fact "
    "explicitly for institutional customers such as universities."
)


def _terms_get(url):
    return f"<html><body>{_GOLDEN_TERMS}</body></html>"


def test_slide5_chatgpt_protege_b_is_refused_and_report_flags_it(tmp_path):
    """Slide 5: ChatGPT/Perplexity + Protégé B strategic/financial data ⇒ INTERDIT."""
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.95},
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    exa_search=lambda tool_name, offering: exa_evidence(
                        training_default="yes", data_retention="indefinite", data_residency="us",
                        sub_processors="undisclosed", provider_human_access="no",
                    ))
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


def test_golden_chatgpt_public_offer_keeps_opt_out_as_unconfirmed(tmp_path):
    """Une option d'opt-out ne devient pas une garantie active dans l'ARP."""
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.95},
    ])
    state = Interview(
        llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
        exa_search=lambda tool_name, offering: exa_evidence(
            evidence=_GOLDEN_TERMS,
            training_default="yes", opt_out_available="yes",
            opt_out_confirmed_enabled="unknown", data_residency="multi_region",
        ),
    ).assess(
        request=RequestInfo(numero="IAG-2026-007"),
        tool_name="ChatGPT Pro",
        usage_inputs=[{
            "description": "Résumer des sources publiques",
            "data_description": "articles déjà publiés",
            "automated_decisions": False, "mode": ["prompt"], "result_use": [],
        }],
    )

    facts = state.tools[0].arp.contract_facts
    assert facts.training_default == "yes"
    assert facts.opt_out_available == "yes"
    assert facts.opt_out_confirmed_enabled == "unknown"
    assert facts.data_residency == "multi_region"
