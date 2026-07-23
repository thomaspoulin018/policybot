"""Local, opt-in clear-text diagnostics for one interview assessment.

Unlike :mod:`policybot.tracing`, this module intentionally retains prompts,
responses and contract excerpts.  It is for local development only and is
disabled unless the application configuration explicitly enables it.
"""
from __future__ import annotations

import contextvars
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.models import FactEvidence


_logger = logging.getLogger("policybot.debug_run")
_current_debug_run: contextvars.ContextVar[DebugRun | None] = contextvars.ContextVar(
    "policybot_debug_run", default=None,
)
_MAX_DOCUMENT_EXCERPT_CHARS = 2_000


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


@dataclass(frozen=True)
class ContractSearchRecord:
    tool_name: str
    source: str
    documents_by_fact: dict[str, list[EvidenceDocument]]
    facts: dict[str, FactEvidence]
    failed_facts: tuple[str, ...]


@dataclass
class DebugRun:
    interview_id: str
    tool_name: str
    started_at: datetime
    started_monotonic: float
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    contract_searches: list[ContractSearchRecord] = field(default_factory=list)
    finished_at: datetime | None = None
    duration_ms: float | None = None


def _debug_runs_root(output_dir: str | Path) -> Path:
    """Return the configured local output directory."""
    return Path(output_dir)


def current_debug_run() -> DebugRun | None:
    """Return the active run for inspection by wrappers and tests."""
    return _current_debug_run.get()


def record_llm_call(record: LLMCallRecord) -> None:
    """Append a clear-text LLM record when a debug run is active."""
    if run := _current_debug_run.get():
        run.llm_calls.append(record)


def record_contract_search(
    tool_name: str, source: str, evidence: ContractEvidence,
) -> None:
    """Append the exact contract-search evidence when a debug run is active."""
    if run := _current_debug_run.get():
        run.contract_searches.append(ContractSearchRecord(
            tool_name=tool_name,
            source=source,
            documents_by_fact={
                fact: list(documents)
                for fact, documents in evidence.documents_by_fact.items()
            },
            facts=dict(evidence.facts),
            failed_facts=tuple(evidence.failed_facts),
        ))


def _fence(text: str | None, language: str = "") -> str:
    content = text if text is not None else "(aucune réponse)"
    # Select a fence longer than any run of backticks in the content, so an
    # embedded Markdown example cannot close the diagnostic block early.
    fence_length = 3
    while "`" * fence_length in content:
        fence_length += 1
    fence = "`" * fence_length
    return f"{fence}{language}\n{content}\n{fence}"


def _format_optional(value: int | float | None, suffix: str = "") -> str:
    return f"{value}{suffix}" if value is not None else "indisponible"


def _render_document(document: EvidenceDocument) -> list[str]:
    lines = [
        f"- URL : {document.url}",
        f"  - Titre : {document.title or '(sans titre)'}",
        f"  - Type : {document.source_type}",
    ]
    if document.effective_date:
        lines.append(f"  - Date d'effet : {document.effective_date.isoformat()}")
    excerpt = document.content[:_MAX_DOCUMENT_EXCERPT_CHARS]
    if len(document.content) > _MAX_DOCUMENT_EXCERPT_CHARS:
        excerpt += "\n[extrait tronqué]"
    lines.extend(["  - Extrait :", _fence(excerpt)])
    return lines


def render_run_md(run: DebugRun) -> str:
    """Render a complete, standalone diagnostic report without disk I/O."""
    duration_ms = run.duration_ms if run.duration_ms is not None else 0.0
    known_total_tokens = sum(
        call.total_tokens or 0 for call in run.llm_calls if call.total_tokens is not None
    )
    known_cost = sum(
        call.cost_usd or 0.0 for call in run.llm_calls if call.cost_usd is not None
    )
    token_summary = (
        str(known_total_tokens)
        if any(call.total_tokens is not None for call in run.llm_calls)
        else "indisponibles"
    )
    cost_summary = (
        f"{known_cost:.8f} USD"
        if any(call.cost_usd is not None for call in run.llm_calls)
        else "indisponible"
    )
    lines = [
        f"# Run debug — {run.tool_name}",
        "",
        "> ⚠️ Contient du texte NON masqué (prompts, réponses, extraits contrat).",
        "> Local, dev-only. Ne pas committer, ne pas partager.",
        "",
        f"- interview_id : {run.interview_id}",
        f"- Outil : {run.tool_name}",
        f"- Démarré : {run.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Durée totale : {duration_ms:.0f} ms",
        f"- LLM : {len(run.llm_calls)} appels · {token_summary} tokens · {cost_summary}",
        "",
        "---",
        f"## Appels LLM ({len(run.llm_calls)})",
    ]
    for index, call in enumerate(run.llm_calls, start=1):
        details = [call.method]
        if call.run_name:
            details.append(call.run_name)
        if call.task:
            details.append(f"task={call.task}")
        details.extend((f"{call.duration_ms:.0f} ms", call.status))
        lines.extend([
            "",
            f"### {index}. {' · '.join(details)}",
            "",
            "**System**",
            _fence(call.system),
            "",
            "**User**",
            _fence(call.user),
            "",
            "**Réponse**",
            _fence(call.response, "json" if call.method != "text" else ""),
            "",
            "**Usage** : " + " · ".join((
                f"in={_format_optional(call.input_tokens)}",
                f"out={_format_optional(call.output_tokens)}",
                f"total={_format_optional(call.total_tokens)}",
                _format_optional(call.cost_usd, " USD"),
            )),
        ])
        if call.tags:
            lines.append(f"**Tags** : {', '.join(call.tags)}")

    lines.extend(["", "---", "## Recherche de contrat"])
    if not run.contract_searches:
        lines.append("\nAucune recherche de contrat effectuée.")
    for search in run.contract_searches:
        lines.extend([
            "",
            f"### {search.source}",
            "",
            f"**Outil** : {search.tool_name} · **Source** : {search.source}",
        ])
        fact_names = sorted(set(search.documents_by_fact) | set(search.facts))
        for fact_name in fact_names:
            fact = search.facts.get(fact_name)
            lines.extend(["", f"#### Fait : {fact_name}"])
            if fact is not None:
                lines.append(f"- Valeur : {fact.value}")
                lines.append(f"- Statut : {fact.outcome or 'non précisé'}")
                if fact.source_url:
                    lines.append(f"- URL : {fact.source_url}")
                if fact.quote:
                    lines.append(f"- Citation : « {fact.quote} »")
                if fact.note:
                    lines.append(f"- Note : {fact.note}")
            documents = search.documents_by_fact.get(fact_name, [])
            lines.append(f"- Documents candidats : {len(documents)}")
            for document in documents:
                lines.extend(_render_document(document))
        if search.failed_facts:
            lines.append(
                "\n### Faits en échec : " + ", ".join(search.failed_facts)
            )
    return "\n".join(lines) + "\n"


def _write_run(run: DebugRun, output_dir: str | Path) -> None:
    stamp = run.started_at.strftime("%Y-%m-%d_%H-%M-%S")
    safe_id = "".join(char for char in run.interview_id if char.isalnum())[:8]
    destination = _debug_runs_root(output_dir) / f"{stamp}_{safe_id}" / "run.md"
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
    """Collect one assessment's local diagnostics and write them on exit.

    Writing diagnostics is best-effort: an unavailable disk must never change
    the assessment result.
    """
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
            # Do not use exc_info here: an operating-system exception can embed
            # a path containing developer-provided clear text.
            _logger.warning("Unable to write local PolicyBot debug run")
