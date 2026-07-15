# tests/test_tracing.py
import json
import logging
import pytest
from policybot.models import RequestInfo
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview, UnknownToolError
from tests.helpers.arp_fixtures import arp_extraction_responses


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[dict] = []

    def emit(self, record):
        self.records.append(json.loads(record.getMessage()))


@pytest.fixture
def trace_events():
    handler = _ListHandler()
    logger = logging.getLogger("policybot.trace")
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)


def _terms_get(url):
    return "<html><body>content may be used to train models</body></html>"


def _make_interview(tmp_path, json_responses):
    llm = FakeLLMProvider(json_responses=json_responses)
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    return Interview(llm=llm, store=store, http_get=_terms_get)


def test_pipeline_steps_share_interview_id(tmp_path, trace_events):
    itv = _make_interview(tmp_path, json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(trains_on_input="no", data_residency="canada"),
    ])
    state = itv.assess(
        request=RequestInfo(numero="IAG-TEST-001"),
        tool_name="ChatGPT",
        usage_inputs=[{
            "description": "Chercher de l'info publique",
            "data_description": "information publique sur le web",
            "automated_decisions": False, "mode": ["prompt"], "result_use": [],
        }],
    )

    steps = {e["step"] for e in trace_events}
    expected = {"assess", "classify_data", "resolve_arp", "llm_call",
                "evaluate_usage", "synthesize"}
    assert expected <= steps

    interview_ids = {e["interview_id"] for e in trace_events}
    assert interview_ids == {state.interview_id}


def test_no_raw_text_leaks_into_logs(tmp_path, trace_events):
    sentinel_nas = "NAS-123-456-789"
    sentinel_email = "jean.tremblay@example.com"
    itv = _make_interview(tmp_path, json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.95},
        *arp_extraction_responses(trains_on_input="no", data_residency="canada"),
    ])
    itv.assess(
        request=RequestInfo(numero="IAG-TEST-002"),
        tool_name="ChatGPT",
        usage_inputs=[{
            "description": "desc",
            "data_description": f"dossier contenant {sentinel_nas} et {sentinel_email}",
            "automated_decisions": False, "mode": ["prompt"], "result_use": [],
        }],
    )

    raw = json.dumps(trace_events)
    assert sentinel_nas not in raw
    assert sentinel_email not in raw


def test_unknown_tool_error_is_logged_before_raising(tmp_path, trace_events):
    itv = _make_interview(tmp_path, json_responses=[])
    with pytest.raises(UnknownToolError):
        itv.assess(
            request=RequestInfo(numero="IAG-TEST-003"),
            tool_name="OutilTotalementInconnu",
            usage_inputs=[],
        )

    error_events = [e for e in trace_events if e["status"] == "error"]
    assert error_events
    assert error_events[0]["step"] == "assess"
    assert error_events[0]["error"] == "UnknownToolError"
    assert error_events[0]["interview_id"] is not None
