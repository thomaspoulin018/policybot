import pytest

from policybot.config import LLM_TASKS
from policybot.llm.fake import FakeLLMProvider
from policybot.llm.router import TaskRoutingLLMProvider


def test_router_selects_provider_for_explicit_task():
    providers = {
        task: FakeLLMProvider(json_responses=[{"task": task}])
        for task in LLM_TASKS
    }
    router = TaskRoutingLLMProvider(providers)

    result = router.complete_json("system", "user", task="mode_detection")

    assert result == {"task": "mode_detection"}
    assert len(providers["mode_detection"].calls) == 1
    assert all(
        not provider.calls
        for task, provider in providers.items()
        if task != "mode_detection"
    )


def test_router_rejects_call_without_task():
    router = TaskRoutingLLMProvider({
        task: FakeLLMProvider(json_responses=[{}]) for task in LLM_TASKS
    })

    with pytest.raises(ValueError, match="task is required"):
        router.complete_json("system", "user")
