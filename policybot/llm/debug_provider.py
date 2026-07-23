"""LLM provider decorator that captures clear-text diagnostics locally."""
from __future__ import annotations

import json
import time

from policybot.config import LLMTask
from policybot.debug_run import LLMCallRecord, record_llm_call
from policybot.llm.provider import LLMProvider, StructuredModel
from policybot.tracing import llm_usage_snapshot


class DebugRecordingProvider(LLMProvider):
    """Delegate to an LLM provider while recording its prompts and result.

    Token and billing metadata are intentionally optional: the stable
    ``LLMProvider`` interface returns parsed content rather than a transport
    response.  Providers that do not expose that metadata remain fully usable.
    """

    def __init__(self, provider: LLMProvider):
        self._provider = provider

    def _record(
        self, *, method: str, system: str, user: str, run_name: str | None,
        tags: list[str] | None, task: LLMTask | None, started: float,
        response: str | None, status: str,
        usage_before: dict[str, int | float] | None,
    ) -> None:
        usage_after = llm_usage_snapshot()
        usage = self._usage_delta(usage_before, usage_after)
        record_llm_call(LLMCallRecord(
            method=method,
            run_name=run_name,
            tags=tuple(tags or ()),
            task=task,
            system=system,
            user=user,
            response=response,
            **usage,
            duration_ms=(time.monotonic() - started) * 1000,
            status=status,
        ))

    @staticmethod
    def _usage_delta(
        before: dict[str, int | float] | None,
        after: dict[str, int | float] | None,
    ) -> dict[str, int | float | None]:
        """Return this call's provider-reported usage, if available."""
        unavailable: dict[str, int | float | None] = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost_usd": None,
        }
        if before is None or after is None:
            return unavailable
        if after["successful_api_calls"] <= before["successful_api_calls"]:
            return unavailable
        token_data = (
            after["input_tokens"] - before["input_tokens"],
            after["output_tokens"] - before["output_tokens"],
            after["total_tokens"] - before["total_tokens"],
        )
        result: dict[str, int | float | None] = {
            "input_tokens": token_data[0]
            if after["usage_recorded_calls"] > before["usage_recorded_calls"] else None,
            "output_tokens": token_data[1]
            if after["usage_recorded_calls"] > before["usage_recorded_calls"] else None,
            "total_tokens": token_data[2]
            if after["usage_recorded_calls"] > before["usage_recorded_calls"] else None,
            "cost_usd": round(after["cost_usd"] - before["cost_usd"], 8)
            if after["cost_recorded_api_calls"] > before["cost_recorded_api_calls"] else None,
        }
        return result

    def complete_json(self, system: str, user: str, *, run_name: str | None = None,
                      tags: list[str] | None = None,
                      task: LLMTask | None = None) -> dict:
        started = time.monotonic()
        usage_before = llm_usage_snapshot()
        try:
            result = self._provider.complete_json(
                system, user, run_name=run_name, tags=tags, task=task,
            )
        except Exception:
            self._record(method="json", system=system, user=user, run_name=run_name,
                         tags=tags, task=task, started=started, response=None, status="error",
                         usage_before=usage_before)
            raise
        self._record(method="json", system=system, user=user, run_name=run_name,
                     tags=tags, task=task, started=started,
                     response=json.dumps(result, ensure_ascii=False, indent=2), status="ok",
                     usage_before=usage_before)
        return result

    def complete_structured(self, system: str, user: str,
                            schema: type[StructuredModel], *,
                            run_name: str | None = None,
                            tags: list[str] | None = None,
                            task: LLMTask | None = None) -> StructuredModel:
        started = time.monotonic()
        usage_before = llm_usage_snapshot()
        try:
            result = self._provider.complete_structured(
                system, user, schema, run_name=run_name, tags=tags, task=task,
            )
        except Exception:
            self._record(method="structured", system=system, user=user, run_name=run_name,
                         tags=tags, task=task, started=started, response=None, status="error",
                         usage_before=usage_before)
            raise
        self._record(method="structured", system=system, user=user, run_name=run_name,
                     tags=tags, task=task, started=started,
                     response=result.model_dump_json(indent=2), status="ok",
                     usage_before=usage_before)
        return result

    def draft_text(self, system: str, user: str, *, run_name: str | None = None,
                   tags: list[str] | None = None,
                   task: LLMTask | None = None) -> str:
        started = time.monotonic()
        usage_before = llm_usage_snapshot()
        try:
            result = self._provider.draft_text(
                system, user, run_name=run_name, tags=tags, task=task,
            )
        except Exception:
            self._record(method="text", system=system, user=user, run_name=run_name,
                         tags=tags, task=task, started=started, response=None, status="error",
                         usage_before=usage_before)
            raise
        self._record(method="text", system=system, user=user, run_name=run_name,
                     tags=tags, task=task, started=started, response=result, status="ok",
                     usage_before=usage_before)
        return result
