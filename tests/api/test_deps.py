import policybot.api.deps as deps
from policybot.config import LLM_TASKS, load_config
from policybot.llm.fake import FakeLLMProvider
from policybot.llm.debug_provider import DebugRecordingProvider
from policybot.llm.router import TaskRoutingLLMProvider


def test_default_interview_builds_one_configured_provider_per_task(
    monkeypatch, tmp_path,
):
    created = []

    def provider_factory(api_key, **kwargs):
        created.append((api_key, kwargs))
        return FakeLLMProvider()

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(deps, "OpenRouterProvider", provider_factory)

    interview = deps.default_interview(str(tmp_path / "pb.db"))

    assert isinstance(interview.llm, TaskRoutingLLMProvider)
    assert len(created) == len(LLM_TASKS)
    assert {kwargs["model"] for _, kwargs in created} == {"openai/gpt-5.6-luna"}
    assert all(api_key == "test-key" for api_key, _ in created)
    assert all(kwargs["max_tokens"] > 0 for _, kwargs in created)
    assert all(kwargs["timeout"] > 0 for _, kwargs in created)
    assert interview._arp_cache_mode == "disabled"


def test_default_interview_wraps_provider_when_yaml_enables_debug_runs(
    monkeypatch, tmp_path,
):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config = load_config()
    config.debug_runs.enabled = True
    monkeypatch.setattr(deps, "load_config", lambda _path: config)

    interview = deps.default_interview(str(tmp_path / "pb.db"))

    assert isinstance(interview.llm, DebugRecordingProvider)
