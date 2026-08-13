import pytest

import policybot.interview.factory as factory
from policybot.config import CleApiManquante
from policybot.llm import FakeLLMProvider


def test_default_interview_configures_the_provider_from_yaml(monkeypatch):
    created = []

    def provider_factory(api_key, **kwargs):
        created.append((api_key, kwargs))
        return FakeLLMProvider()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(factory, "OpenRouterProvider", provider_factory)

    factory.default_interview()

    assert len(created) == 1
    api_key, kwargs = created[0]
    assert api_key == "test-key"
    assert kwargs["model"] == "openai/gpt-5.6-luna"
    assert kwargs["max_tokens"] > 0
    assert kwargs["timeout"] > 0


def test_default_interview_refuses_to_run_without_an_api_key(monkeypatch):
    """Le repli hors ligne silencieux levait `IndexError` au premier appel."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(CleApiManquante) as erreur:
        factory.default_interview()

    assert "OPENROUTER_API_KEY" in str(erreur.value)
