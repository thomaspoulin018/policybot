"""Internal debugging trace: one JSON-lines event per pipeline step.

Never writes raw free text (usage descriptions, contract terms, LLM
prompts/responses) to disk — only `mask_text()` output (length + hash).
See plan-tracabilite-interne.html for the design rationale.
"""
from __future__ import annotations
import contextvars
import hashlib
import json
import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Mapping


def _timestamped_log_path(log_dir: Path, now: datetime | None = None) -> Path:
    """Return a distinct JSON-lines log path for one application run."""
    started_at = now or datetime.now()
    timestamp = started_at.strftime("%Y-%m-%d_%H-%M-%S_%f")
    return log_dir / f"log_{timestamp}.jsonl"


_LOG_PATH = Path(
    os.environ.get("POLICYBOT_LOG_PATH") or _timestamped_log_path(Path("logs")),
)

_logger = logging.getLogger("policybot.trace")
_logger.setLevel(logging.INFO)
_logger.propagate = False


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def _build_handler() -> logging.Handler:
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    handler.setFormatter(_JsonLineFormatter())
    return handler


if not _logger.handlers:
    _logger.addHandler(_build_handler())

# Carries the enclosing interview_id across nested trace_step() calls (e.g. LLM
# provider calls made deep inside classify_data/_resolve_arp) without having to
# thread interview_id through every function signature.
_current_interview_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "policybot_interview_id", default=None,
)


@dataclass
class LLMUsage:
    """Aggregated LLM and Exa usage for one assessment, without content."""

    api_calls: int = 0
    successful_api_calls: int = 0
    failed_api_calls: int = 0
    usage_recorded_calls: int = 0
    cost_recorded_api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_available: bool = False
    exa_search_calls: int = 0
    exa_successful_search_calls: int = 0
    exa_failed_search_calls: int = 0
    exa_priced_search_calls: int = 0
    exa_estimated_cost_usd: float = 0.0

    def _openrouter_cost(self) -> float | None:
        if self.successful_api_calls == 0:
            return 0.0
        if self.cost_available and self.successful_api_calls == self.cost_recorded_api_calls:
            return round(self.cost_usd, 8)
        return None

    def _exa_cost(self) -> float | None:
        if self.exa_successful_search_calls == 0:
            return 0.0
        if self.exa_successful_search_calls == self.exa_priced_search_calls:
            return round(self.exa_estimated_cost_usd, 8)
        return None

    def as_dict(self) -> dict[str, int | float | bool | None]:
        openrouter_cost = self._openrouter_cost()
        exa_cost = self._exa_cost()
        total_cost = (
            round(openrouter_cost + exa_cost, 8)
            if openrouter_cost is not None and exa_cost is not None
            else None
        )
        return {
            "api_calls": self.api_calls,
            "successful_api_calls": self.successful_api_calls,
            "failed_api_calls": self.failed_api_calls,
            "usage_recorded_calls": self.usage_recorded_calls,
            "cost_recorded_api_calls": self.cost_recorded_api_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            # Retained for existing log consumers; it is the total for the run.
            "cost_usd": total_cost,
            "openrouter_cost_usd": openrouter_cost,
            "exa_search_calls": self.exa_search_calls,
            "exa_successful_search_calls": self.exa_successful_search_calls,
            "exa_failed_search_calls": self.exa_failed_search_calls,
            "exa_priced_search_calls": self.exa_priced_search_calls,
            # Estimated from Exa's public per-request pricing, not supplied by Exa.
            "exa_estimated_cost_usd": exa_cost,
            "total_cost_usd": total_cost,
        }


_current_llm_usage: contextvars.ContextVar[LLMUsage | None] = contextvars.ContextVar(
    "policybot_llm_usage", default=None,
)


def mask_text(text: str) -> dict:
    """The only sanctioned way to let free text influence a log line."""
    return {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:12]}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    return model_dump() if callable(model_dump) else {}


def _number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _cost(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def extract_llm_usage(response: Any) -> dict[str, int | float | None]:
    """Normalize LangChain/OpenRouter usage metadata from a model response.

    OpenRouter may expose the native ``usage`` object either in LangChain's
    ``usage_metadata`` or in ``response_metadata``.  We deliberately use the
    provider-reported cost instead of duplicating a mutable pricing table.
    """
    response_metadata = _as_mapping(getattr(response, "response_metadata", None))
    candidates = (
        _as_mapping(getattr(response, "usage_metadata", None)),
        _as_mapping(response_metadata.get("usage")),
        _as_mapping(response_metadata.get("token_usage")),
    )
    def first_number(*names: str) -> int | None:
        for candidate in candidates:
            for name in names:
                number = _number(candidate.get(name))
                if number is not None:
                    return number
        return None

    def first_cost(*names: str) -> float | None:
        for candidate in candidates:
            for name in names:
                cost = _cost(candidate.get(name))
                if cost is not None:
                    return cost
        return None

    input_tokens = first_number("input_tokens", "prompt_tokens")
    output_tokens = first_number("output_tokens", "completion_tokens")
    total_tokens = first_number("total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": first_cost("cost", "total_cost"),
    }


def record_llm_call_started() -> None:
    if usage := _current_llm_usage.get():
        usage.api_calls += 1


def record_llm_call_failed() -> None:
    if usage := _current_llm_usage.get():
        usage.failed_api_calls += 1


def record_llm_call_succeeded(usage_data: Mapping[str, int | float | None]) -> None:
    if usage := _current_llm_usage.get():
        usage.successful_api_calls += 1
        values = {name: usage_data.get(name) for name in (
            "input_tokens", "output_tokens", "total_tokens",
        )}
        if any(value is not None for value in values.values()):
            usage.usage_recorded_calls += 1
            usage.input_tokens += int(values["input_tokens"] or 0)
            usage.output_tokens += int(values["output_tokens"] or 0)
            usage.total_tokens += int(values["total_tokens"] or 0)
        cost_usd = usage_data.get("cost_usd")
        if cost_usd is not None:
            usage.cost_available = True
            usage.cost_recorded_api_calls += 1
            usage.cost_usd += float(cost_usd)


def record_exa_search_started() -> None:
    if usage := _current_llm_usage.get():
        usage.exa_search_calls += 1


def record_exa_search_failed() -> None:
    if usage := _current_llm_usage.get():
        usage.exa_failed_search_calls += 1


def record_exa_search_succeeded(estimated_cost_usd: float | None) -> None:
    if usage := _current_llm_usage.get():
        usage.exa_successful_search_calls += 1
        if estimated_cost_usd is not None:
            usage.exa_priced_search_calls += 1
            usage.exa_estimated_cost_usd += estimated_cost_usd


@contextmanager
def collect_llm_usage(interview_id: str):
    """Collect and emit LLM and Exa API usage totals for one run."""
    usage = LLMUsage()
    token = _current_llm_usage.set(usage)
    run_status = "ok"
    try:
        yield usage
    except Exception:
        run_status = "error"
        raise
    finally:
        _current_llm_usage.reset(token)
        _emit(interview_id, "llm_usage_summary", run_status, 0.0, **usage.as_dict())


def _safe_error_fields(exc: Exception) -> dict:
    """Return diagnostic metadata without copying exception text to the log.

    HTTP clients commonly expose their response status either on ``response``
    or directly on the exception. The status distinguishes a bad request, an
    authentication issue, and a transient provider failure, while the response
    body/message may contain user-supplied content and must stay masked.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is None:
        status = getattr(exc, "status_code", None)
    return {"http_status": status} if isinstance(status, int) else {}


def _emit(interview_id: str | None, step: str, status: str, duration_s: float, **fields) -> None:
    _logger.info(json.dumps({
        "ts": time.time(),
        "interview_id": interview_id,
        "step": step,
        "status": status,
        "duration_ms": round(duration_s * 1000, 1),
        **fields,
    }))


@contextmanager
def trace_step(interview_id: str | None, step: str, **fields):
    """Log one `ok`/`error` event for `step`, timed, re-raising any exception.

    Yields a dict the caller can mutate to add fields discovered while the
    step runs (e.g. a classification result), merged into the final event.
    """
    iid = interview_id or _current_interview_id.get()
    token = _current_interview_id.set(iid)
    start = time.monotonic()
    extra: dict = {}
    try:
        yield extra
    except Exception as exc:
        _emit(iid, step, "error", time.monotonic() - start,
              error=type(exc).__name__, error_message=mask_text(str(exc)),
              **_safe_error_fields(exc),
              **fields, **extra)
        raise
    else:
        _emit(iid, step, "ok", time.monotonic() - start, **fields, **extra)
    finally:
        _current_interview_id.reset(token)
