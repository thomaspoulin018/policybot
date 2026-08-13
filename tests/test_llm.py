"""Tests de la couche modèle : l'appel HTTP est toujours simulé, la suite
reste entièrement hors ligne."""
import json
from contextlib import contextmanager
from io import BytesIO

import pytest

import policybot.llm as llm_module
from policybot.llm import FakeLLMProvider, LLMError, OpenRouterProvider
from policybot.tracing import collect_llm_usage


def _install_fake_urlopen(monkeypatch, payload, captured, error=None):
    @contextmanager
    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        if error is not None:
            raise error
        yield BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(llm_module.urllib.request, "urlopen", fake_urlopen)


def _completion(content, usage=None):
    body = {"choices": [{"message": {"content": content}}]}
    if usage is not None:
        body["usage"] = usage
    return body


def test_complete_json_posts_to_openrouter_and_parses_the_content(monkeypatch):
    captured = {}
    _install_fake_urlopen(monkeypatch, _completion('{"ok": true, "n": 2}'), captured)

    provider = OpenRouterProvider("sk-secret", model="google/gemma-2-27b-it")
    assert provider.complete_json("system prompt", "user prompt") == {"ok": True, "n": 2}

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-secret"
    body = captured["body"]
    assert body["model"] == "google/gemma-2-27b-it"
    assert body["response_format"] == {"type": "json_object"}
    assert body["reasoning_effort"] == "low"
    assert body["max_tokens"] == 4096
    assert body["temperature"] == 0.0
    assert body["usage"] == {"include": True}
    assert captured["timeout"] == 60.0
    assert body["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user prompt"},
    ]


def test_environment_configures_model_and_reasoning_effort(monkeypatch):
    captured = {}
    _install_fake_urlopen(monkeypatch, _completion("{}"), captured)
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-5.6-luna")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "minimal")
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "2048")
    monkeypatch.setenv("OPENROUTER_TEMPERATURE", "0.3")
    monkeypatch.setenv("OPENROUTER_TIMEOUT", "25")

    OpenRouterProvider("sk-secret").complete_json("s", "u")

    body = captured["body"]
    assert body["model"] == "openai/gpt-5.6-luna"
    assert body["reasoning_effort"] == "minimal"
    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.3
    assert captured["timeout"] == 25.0


@pytest.mark.parametrize("variable, value", [
    ("OPENROUTER_MAX_TOKENS", "0"),
    ("OPENROUTER_TEMPERATURE", "3"),
    ("OPENROUTER_TIMEOUT", "0"),
])
def test_out_of_range_settings_are_refused(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError):
        OpenRouterProvider("sk-secret")


def test_usage_and_cost_are_aggregated_from_openrouter_response(monkeypatch):
    captured = {}
    _install_fake_urlopen(monkeypatch, _completion(
        '{"ok": true}',
        usage={"prompt_tokens": 125, "completion_tokens": 25,
               "total_tokens": 150, "cost": 0.00125},
    ), captured)

    provider = OpenRouterProvider("sk-secret")
    with collect_llm_usage("interview-usage") as totals:
        assert provider.complete_json("system", "user") == {"ok": True}

    snapshot = totals.as_dict()
    assert snapshot["api_calls"] == 1
    assert snapshot["successful_api_calls"] == 1
    assert snapshot["failed_api_calls"] == 0
    assert snapshot["input_tokens"] == 125
    assert snapshot["output_tokens"] == 25
    assert snapshot["total_tokens"] == 150
    assert snapshot["cost_usd"] == 0.00125
    assert snapshot["total_cost_usd"] == 0.00125


def test_network_failure_is_reported_and_counted(monkeypatch):
    captured = {}
    _install_fake_urlopen(
        monkeypatch, None, captured,
        error=llm_module.urllib.error.URLError("boom"),
    )

    provider = OpenRouterProvider("sk-secret")
    with collect_llm_usage("interview-usage") as totals:
        with pytest.raises(LLMError):
            provider.complete_json("system", "user")

    assert totals.as_dict()["failed_api_calls"] == 1


def test_unusable_response_is_reported_and_counted(monkeypatch):
    captured = {}
    _install_fake_urlopen(monkeypatch, {"choices": []}, captured)

    provider = OpenRouterProvider("sk-secret")
    with collect_llm_usage("interview-usage") as totals:
        with pytest.raises(LLMError):
            provider.complete_json("system", "user")

    assert totals.as_dict()["failed_api_calls"] == 1


def test_fake_provider_serves_prepared_answers_and_records_calls():
    fake = FakeLLMProvider([{"a": 1}, {"b": 2}])

    assert fake.complete_json("sys", "u1") == {"a": 1}
    assert fake.complete_json("sys", "u2") == {"b": 2}
    assert fake.calls == [("sys", "u1"), ("sys", "u2")]
