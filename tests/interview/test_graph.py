from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.interview.graph import run_graph
from tests.helpers.arp_fixtures import arp_extraction_responses


def _terms_get(url):
    return "<html><body>train our models</body></html>"


def test_graph_runs_full_pipeline(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(trains_on_input="no", data_residency="canada"),
    ])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=_terms_get)
    state = run_graph(itv, RequestInfo(numero="IAG-2026-003"), "ChatGPT",
                      [{"description": "info publique", "data_description": "info publique",
                        "automated_decisions": False, "mode": ["prompt"], "result_use": []}])
    assert state.status == "complete"
    assert state.result_global.recommendation == "Autoriser"
