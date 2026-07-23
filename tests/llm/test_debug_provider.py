from __future__ import annotations

from pydantic import BaseModel

from policybot.debug_run import current_debug_run, debug_run
from policybot.llm.debug_provider import DebugRecordingProvider
from policybot.llm.fake import FakeLLMProvider
from policybot.tracing import (
    collect_llm_usage,
    record_llm_call_started,
    record_llm_call_succeeded,
)


class StructuredAnswer(BaseModel):
    accepted: bool


def test_debug_provider_records_exact_prompts_and_serialized_responses(tmp_path):
    wrapped = DebugRecordingProvider(FakeLLMProvider(
        json_responses=[{"ok": True}, {"accepted": True}],
        text_responses=["prose"],
    ))

    with debug_run("abcd1234-0000", "ChatGPT", enabled=True, output_dir=tmp_path / "runs") as run:
        assert wrapped.complete_json(
            "system json", "user json", run_name="json-call",
            tags=["tag"], task="data_classification",
        ) == {"ok": True}
        assert wrapped.complete_structured(
            "system structured", "user structured", StructuredAnswer,
        ) == StructuredAnswer(accepted=True)
        assert wrapped.draft_text("system text", "user text") == "prose"
        assert current_debug_run() is run

    assert run is not None
    assert [call.method for call in run.llm_calls] == ["json", "structured", "text"]
    assert run.llm_calls[0].system == "system json"
    assert run.llm_calls[0].user == "user json"
    assert '"ok": true' in (run.llm_calls[0].response or "")
    assert '"accepted": true' in (run.llm_calls[1].response or "")
    assert run.llm_calls[2].response == "prose"


def test_debug_provider_preserves_underlying_exception(tmp_path):

    class FailingProvider(FakeLLMProvider):
        def draft_text(self, *args, **kwargs):
            raise RuntimeError("provider unavailable")

    wrapped = DebugRecordingProvider(FailingProvider())
    try:
        with debug_run("abcd1234-0000", "ChatGPT", enabled=True, output_dir=tmp_path / "runs") as run:
            wrapped.draft_text("system", "user")
    except RuntimeError:
        pass
    else:
        raise AssertionError("the provider exception must be preserved")

    assert run is not None
    assert run.llm_calls[0].status == "error"
    assert run.llm_calls[0].response is None


def test_debug_provider_associates_provider_usage_with_the_call(tmp_path):

    class UsageProvider(FakeLLMProvider):
        def complete_json(self, *args, **kwargs):
            record_llm_call_started()
            record_llm_call_succeeded({
                "input_tokens": 12,
                "output_tokens": 3,
                "total_tokens": 15,
                "cost_usd": 0.0025,
            })
            return {"ok": True}

    wrapped = DebugRecordingProvider(UsageProvider())
    with collect_llm_usage("usage-run"):
        with debug_run("abcd1234-0000", "ChatGPT", enabled=True, output_dir=tmp_path / "runs") as run:
            wrapped.complete_json("system", "user")

    assert run is not None
    call = run.llm_calls[0]
    assert (call.input_tokens, call.output_tokens, call.total_tokens) == (12, 3, 15)
    assert call.cost_usd == 0.0025
