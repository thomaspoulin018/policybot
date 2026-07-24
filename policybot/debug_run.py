"""Diagnostics locaux explicites, en clair, pour les appels LLM."""
from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator


_logger = logging.getLogger("policybot.debug_run")


@dataclass(frozen=True)
class LLMCallRecord:
    method: str
    run_name: str | None
    tags: tuple[str, ...]
    task: str | None
    system: str
    user: str
    response: str | None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: float = 0.0
    status: str = "ok"


@dataclass
class DebugRun:
    interview_id: str
    tool_name: str
    started_at: datetime
    started_monotonic: float
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    finished_at: datetime | None = None
    duration_ms: float | None = None


_current_debug_run: contextvars.ContextVar[DebugRun | None] = contextvars.ContextVar(
    "policybot_debug_run", default=None,
)


def current_debug_run() -> DebugRun | None:
    return _current_debug_run.get()


def record_llm_call(record: LLMCallRecord) -> None:
    if run := _current_debug_run.get():
        run.llm_calls.append(record)


def _fence(text: str | None) -> str:
    content = text if text is not None else "(aucune réponse)"
    size = 3
    while "`" * size in content:
        size += 1
    fence = "`" * size
    return f"{fence}\n{content}\n{fence}"


def render_run_md(run: DebugRun) -> str:
    lines = [
        f"# Run debug — {run.tool_name}",
        "",
        "> Contient du texte non masqué. Usage local seulement.",
        "",
        f"- interview_id : {run.interview_id}",
        f"- Durée : {(run.duration_ms or 0):.0f} ms",
        "",
        f"## Appels LLM ({len(run.llm_calls)})",
    ]
    for index, call in enumerate(run.llm_calls, 1):
        lines.extend([
            "",
            f"### {index}. {call.method} — {call.status}",
            "",
            "**System**",
            _fence(call.system),
            "",
            "**User**",
            _fence(call.user),
            "",
            "**Réponse**",
            _fence(call.response),
        ])
    return "\n".join(lines) + "\n"


def _write_run(run: DebugRun, output_dir: str | Path) -> None:
    stamp = run.started_at.strftime("%Y-%m-%d_%H-%M-%S")
    safe_id = "".join(char for char in run.interview_id if char.isalnum())[:8]
    destination = Path(output_dir) / f"{stamp}_{safe_id}" / "run.md"
    destination.parent.mkdir(parents=True, exist_ok=False)
    destination.write_text(render_run_md(run), encoding="utf-8")


@contextmanager
def debug_run(
    interview_id: str,
    tool_name: str,
    *,
    enabled: bool = False,
    output_dir: str | Path = "logs/runs",
) -> Iterator[DebugRun | None]:
    if not enabled:
        yield None
        return
    run = DebugRun(
        interview_id=interview_id,
        tool_name=tool_name,
        started_at=datetime.now(),
        started_monotonic=time.monotonic(),
    )
    token = _current_debug_run.set(run)
    try:
        yield run
    finally:
        run.finished_at = datetime.now()
        run.duration_ms = (time.monotonic() - run.started_monotonic) * 1000
        _current_debug_run.reset(token)
        try:
            _write_run(run, output_dir)
        except Exception:
            _logger.warning("Unable to write local PolicyBot debug run")
