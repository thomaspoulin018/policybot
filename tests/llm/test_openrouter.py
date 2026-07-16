"""Unit tests for OpenRouterProvider, with ChatOpenAI stubbed out so no network
call (and no LangSmith trace) happens during the suite."""
from types import SimpleNamespace

from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import BaseModel

import policybot.llm.openrouter as orm
from policybot.tracing import collect_llm_usage


class StructuredAnswer(BaseModel):
    ok: bool
    n: int


def _install_fake_chat(monkeypatch, content, captured):
    class FakeChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self._structured = False

        def bind(self, **kwargs):
            captured.setdefault("bind", {}).update(kwargs)
            return self

        def with_structured_output(self, schema, **kwargs):
            captured["structured_schema"] = schema
            captured["structured_kwargs"] = kwargs
            self._structured = True
            return self

        def invoke(self, messages, config=None):
            captured["messages"] = messages
            captured["config"] = config
            if self._structured:
                return content
            return SimpleNamespace(content=content)

    monkeypatch.setattr(orm, "ChatOpenAI", FakeChat)


def test_complete_json_parses_binds_and_tags(monkeypatch):
    captured = {}
    _install_fake_chat(monkeypatch, '{"ok": true, "n": 2}', captured)

    provider = orm.OpenRouterProvider("sk-secret", model="google/gemma-2-27b-it")
    out = provider.complete_json(
        "system prompt", "user prompt",
        run_name="classify_data_sensitivity", tags=["data_classification"],
    )

    assert out == {"ok": True, "n": 2}
    # OpenRouter wiring
    assert captured["init"]["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["init"]["model"] == "google/gemma-2-27b-it"
    assert captured["init"]["reasoning_effort"] == "low"
    assert captured["init"]["max_tokens"] == 4096
    assert captured["init"]["temperature"] == 0.0
    assert captured["init"]["timeout"] == 60.0
    # JSON mode binds response_format
    assert captured["bind"]["response_format"] == {"type": "json_object"}
    # LangSmith trace annotations threaded through
    assert captured["config"]["run_name"] == "classify_data_sensitivity"
    assert captured["config"]["tags"] == ["data_classification"]
    # Correct message roles and order
    sys_msg, user_msg = captured["messages"]
    assert isinstance(sys_msg, SystemMessage) and sys_msg.content == "system prompt"
    assert isinstance(user_msg, HumanMessage) and user_msg.content == "user prompt"


def test_complete_structured_uses_langchain_schema_and_tags(monkeypatch):
    captured = {}
    _install_fake_chat(monkeypatch, {"ok": True, "n": 2}, captured)

    provider = orm.OpenRouterProvider("sk-secret")
    out = provider.complete_structured(
        "system prompt", "user prompt", StructuredAnswer,
        run_name="extract_contract_facts", tags=["arp_extraction"],
    )

    assert out == StructuredAnswer(ok=True, n=2)
    assert captured["structured_schema"] is StructuredAnswer
    assert captured["structured_kwargs"] == {"method": "json_mode", "include_raw": True}
    assert captured["config"]["run_name"] == "extract_contract_facts"
    assert captured["config"]["tags"] == ["arp_extraction"]
    sys_msg, user_msg = captured["messages"]
    assert isinstance(sys_msg, SystemMessage) and sys_msg.content == "system prompt"
    assert isinstance(user_msg, HumanMessage) and user_msg.content == "user prompt"


def test_draft_text_no_json_binding_no_config(monkeypatch):
    captured = {}
    _install_fake_chat(monkeypatch, "free-form narrative", captured)

    provider = orm.OpenRouterProvider("sk-secret")
    out = provider.draft_text("system prompt", "user prompt")

    assert out == "free-form narrative"
    # Plain text must NOT force JSON response_format
    assert "bind" not in captured
    # No run_name/tags -> no config passed
    assert captured["config"] is None


def test_environment_configures_model_and_reasoning_effort(monkeypatch):
    captured = {}
    _install_fake_chat(monkeypatch, "free-form narrative", captured)
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-5.6-luna")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "2048")
    monkeypatch.setenv("OPENROUTER_TEMPERATURE", "0.3")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "25")

    orm.OpenRouterProvider("sk-secret")

    assert captured["init"]["model"] == "openai/gpt-5.6-luna"
    assert captured["init"]["reasoning_effort"] == "minimal"
    assert captured["init"]["max_tokens"] == 2048
    assert captured["init"]["temperature"] == 0.3
    assert captured["init"]["timeout"] == 25.0


def test_usage_and_cost_are_aggregated_from_openrouter_response(monkeypatch):
    captured = {}
    response = SimpleNamespace(
        content='{"ok": true, "n": 2}',
        usage_metadata={"input_tokens": 125, "output_tokens": 25, "total_tokens": 150},
        response_metadata={"usage": {"cost": 0.00125}},
    )

    _install_fake_chat(monkeypatch, response.content, captured)

    # Make the fake return an object with the same metadata as a real
    # non-streaming OpenRouter/LangChain message.
    provider = orm.OpenRouterProvider("sk-secret")
    provider._llm.invoke = lambda messages, config=None: response

    with collect_llm_usage("interview-usage") as totals:
        assert provider.complete_json("system", "user") == {"ok": True, "n": 2}

    assert totals.as_dict() == {
        "api_calls": 1,
        "successful_api_calls": 1,
        "failed_api_calls": 0,
        "usage_recorded_calls": 1,
        "input_tokens": 125,
        "output_tokens": 25,
        "total_tokens": 150,
        "cost_usd": 0.00125,
    }


def test_structured_call_uses_raw_response_for_usage_accounting(monkeypatch):
    captured = {}
    _install_fake_chat(monkeypatch, {"ok": True, "n": 2}, captured)
    provider = orm.OpenRouterProvider("sk-secret")
    raw = SimpleNamespace(
        usage_metadata={},
        response_metadata={"token_usage": {
            "prompt_tokens": 80, "completion_tokens": 20,
            "total_tokens": 100, "cost": 0.0008,
        }},
    )
    provider._llm.invoke = lambda messages, config=None: {
        "raw": raw,
        "parsed": {"ok": True, "n": 2},
    }

    with collect_llm_usage("interview-usage") as totals:
        assert provider.complete_structured("system", "user", StructuredAnswer) == StructuredAnswer(
            ok=True, n=2,
        )

    assert totals.as_dict()["total_tokens"] == 100
    assert totals.as_dict()["cost_usd"] == 0.0008
