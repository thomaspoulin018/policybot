import json
import logging

import pytest

from policybot.tracing import (
    collect_llm_usage,
    record_exa_search_started,
    record_exa_search_succeeded,
    trace_step,
)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

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


def test_exa_reported_cost_is_aggregated(trace_events):
    with collect_llm_usage("exa-cost"):
        record_exa_search_started()
        record_exa_search_succeeded(0.031, reported=True)
    summary = trace_events[-1]
    assert summary["exa_reported_search_calls"] == 1
    assert summary["exa_estimated_cost_usd"] == 0.031


def test_error_text_is_masked(trace_events):
    secret = "jean.tremblay@example.com"
    with pytest.raises(RuntimeError):
        with trace_step("interview", "failure"):
            raise RuntimeError(secret)
    assert secret not in json.dumps(trace_events)
    assert trace_events[-1]["error_message"]["len"] == len(secret)
