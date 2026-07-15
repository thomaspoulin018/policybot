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
from logging.handlers import RotatingFileHandler

_LOG_PATH = os.environ.get("POLICYBOT_LOG_PATH", os.path.join("logs", "policybot.jsonl"))

_logger = logging.getLogger("policybot.trace")
_logger.setLevel(logging.INFO)
_logger.propagate = False


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return record.getMessage()


def _build_handler() -> logging.Handler:
    log_dir = os.path.dirname(_LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
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


def mask_text(text: str) -> dict:
    """The only sanctioned way to let free text influence a log line."""
    return {"len": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:12]}


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
              **fields, **extra)
        raise
    else:
        _emit(iid, step, "ok", time.monotonic() - start, **fields, **extra)
    finally:
        _current_interview_id.reset(token)
