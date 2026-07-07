"""Unit tests for OpenRouterProvider, with ChatOpenAI stubbed out so no network
call (and no LangSmith trace) happens during the suite."""
from types import SimpleNamespace
from langchain_core.messages import SystemMessage, HumanMessage
import policybot.llm.openrouter as orm


def _install_fake_chat(monkeypatch, content, captured):
    class FakeChat:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def bind(self, **kwargs):
            captured.setdefault("bind", {}).update(kwargs)
            return self

        def invoke(self, messages, config=None):
            captured["messages"] = messages
            captured["config"] = config
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
    # JSON mode binds response_format
    assert captured["bind"]["response_format"] == {"type": "json_object"}
    # LangSmith trace annotations threaded through
    assert captured["config"]["run_name"] == "classify_data_sensitivity"
    assert captured["config"]["tags"] == ["data_classification"]
    # Correct message roles and order
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
