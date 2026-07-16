from __future__ import annotations

from policybot.config import LLMTask
from policybot.llm.provider import LLMProvider, StructuredModel


class TaskRoutingLLMProvider(LLMProvider):
    """Delegate each LLM call to the provider configured for its task."""

    def __init__(self, providers: dict[LLMTask, LLMProvider]):
        self._providers = providers

    def _provider(self, task: LLMTask | None) -> LLMProvider:
        if task is None:
            raise ValueError("An LLM task is required when task routing is enabled")
        try:
            return self._providers[task]
        except KeyError as exc:
            raise ValueError(f"No LLM provider configured for task: {task}") from exc

    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None,
                      task: LLMTask | None = None) -> dict:
        return self._provider(task).complete_json(
            system, user, run_name=run_name, tags=tags, task=task,
        )

    def complete_structured(self, system: str, user: str,
                            schema: type[StructuredModel], *,
                            run_name: str | None = None,
                            tags: list[str] | None = None,
                            task: LLMTask | None = None) -> StructuredModel:
        return self._provider(task).complete_structured(
            system, user, schema, run_name=run_name, tags=tags, task=task,
        )

    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None,
                   task: LLMTask | None = None) -> str:
        return self._provider(task).draft_text(
            system, user, run_name=run_name, tags=tags, task=task,
        )
