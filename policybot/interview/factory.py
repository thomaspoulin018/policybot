from __future__ import annotations
import os
from pathlib import Path
from policybot.config import LLM_TASKS, load_config
from policybot.llm.debug_provider import DebugRecordingProvider
from policybot.llm.openrouter import OpenRouterProvider
from policybot.llm.fake import FakeLLMProvider
from policybot.llm.router import TaskRoutingLLMProvider
from policybot.contract.cache import ArpCache
from policybot.interview.orchestrator import Interview


def default_interview(
    db_path: str = "policybot.db",
    config_path: str | Path | None = None,
) -> Interview:
    config = load_config(config_path)
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        providers = {}
        for task in LLM_TASKS:
            task_config = getattr(config.llm.tasks, task)
            providers[task] = OpenRouterProvider(
                key,
                model=task_config.model,
                reasoning_effort=task_config.reasoning_effort,
                max_tokens=task_config.max_tokens,
                temperature=task_config.temperature,
                timeout=task_config.timeout,
            )
        llm = TaskRoutingLLMProvider(providers)
    else:
        llm = FakeLLMProvider()
    if config.debug_runs.enabled:
        llm = DebugRecordingProvider(llm)
    return Interview(
        llm=llm,
        store=ArpCache(db_path),
        arp_cache_mode=config.cache.arp.mode,
        debug_runs_enabled=config.debug_runs.enabled,
        debug_runs_output_dir=config.debug_runs.output_dir,
    )
