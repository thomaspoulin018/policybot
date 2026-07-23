"""Exa-backed, deterministic collection of one contract fact per search."""
from __future__ import annotations

import contextvars
import json
import os
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Protocol

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.arp import _quote_is_anchored
from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.contract.fact_search import (
    EXA_SEARCH_TYPES,
    FACT_SEARCHES,
    FactSearchConfig,
)
from policybot.contract.source_policy import (
    build_source_policy,
    contract_source_urls,
    classify_source,
    source_effective_date,
    source_is_allowed,
    source_sort_key,
)
from policybot.models import ContractOfferingIdentity, FactEvidence
from policybot.tracing import (
    mask_text,
    record_exa_search_failed,
    record_exa_search_started,
    record_exa_search_succeeded,
    trace_step,
)


DEFAULT_MAX_WORKERS = 8

# One Exa search per fact runs concurrently against api.exa.ai.  Under load the
# server intermittently resets or drops connections (ConnectionReset / SSL EOF)
# and can answer 429/5xx; each of those is transient — a plain retry recovers
# the fact.  Without a retry a single blip permanently marked the fact
# ``collection_failure``, silently hollowing out Partie A.  Retries stay inside
# ``_collect_one`` so an exhausted fact still degrades alone, never the
# interview.  Tune with ``POLICYBOT_EXA_MAX_ATTEMPTS``.
DEFAULT_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY_S = 0.5
# 429 plus the whole 5xx range are the retryable HTTP statuses exa_py surfaces
# as ``ValueError("... status code NNN ...")``; a 4xx (400/401/403) is a
# permanent request/auth problem and must fail fast without burning retries.
_RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
_HTTP_STATUS_RE = re.compile(r"status code (\d{3})")


def _http_status(exc: Exception) -> int | None:
    """Return the HTTP status exa_py encoded in a ValueError message, if any."""
    if isinstance(exc, ValueError) and (match := _HTTP_STATUS_RE.search(str(exc))):
        return int(match.group(1))
    return None


def _is_transient(exc: Exception) -> bool:
    """True when retrying the same Exa search could plausibly succeed.

    Network failures (``requests`` raises ``ConnectionError``/``SSLError``/
    ``Timeout`` — all ``OSError`` subclasses, as are the builtin
    ``ConnectionResetError``/``TimeoutError``) are always transient.  A
    ValueError only counts when its embedded HTTP status is 429/5xx; a 4xx is
    permanent, and any other ValueError (e.g. a bad-response parse) is not
    worth retrying.
    """
    status = _http_status(exc)
    if status is not None:
        return status in _RETRYABLE_HTTP_STATUS
    if isinstance(exc, ValueError):
        return False
    return isinstance(exc, OSError)


def _sleep_before_retry(attempt: int) -> None:
    """Exponential backoff with full jitter, to de-synchronise worker retries."""
    ceiling = _RETRY_BASE_DELAY_S * (2 ** (attempt - 1))
    time.sleep(random.uniform(0, ceiling))


# Exa's Search response carries a ``costDollars`` object whose ``total`` is
# Exa's own per-request cost estimate (labelled "not an invoice record").  We
# read that value when present (see ``_response_cost_usd``).  The public rates
# below are only a fallback for responses that omit it — e.g. a stubbed client
# or an older API.  See https://exa.ai/pricing (verified 2026-07-21).
_EXA_SEARCH_BASE_COST_USD = {
    "auto": 0.007,
    "deep": 0.012,
}
_EXA_AI_SUMMARY_COST_PER_RESULT_USD = 0.001


class ExaClient(Protocol):
    def search(self, query: str, **kwargs: Any) -> Any:
        """Run one Exa search."""


@dataclass(frozen=True)
class _FactSearchResult:
    fact: str
    proof: FactEvidence
    documents: list[EvidenceDocument]
    failed: bool = False


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, Mapping) else None
    if hasattr(value, "__dict__"):
        return vars(value)
    return None


def _field(value: Any, name: str, default: Any = None) -> Any:
    mapping = _as_mapping(value)
    if mapping is not None:
        return mapping.get(name, default)
    return getattr(value, name, default)


def _results(response: Any) -> list[Any]:
    raw = _field(response, "results", ())
    return list(raw) if isinstance(raw, (list, tuple)) else []


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(part for item in value if (part := _text(item)))
    if isinstance(value, Mapping):
        return _text(value.get("text") or value.get("content") or "")
    return ""


def _summary(result: Any) -> Mapping[str, Any] | None:
    raw = _field(result, "summary")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return _as_mapping(raw)


def _document_from_result(result: Any) -> tuple[EvidenceDocument, Mapping[str, Any]] | None:
    raw = _as_mapping(result)
    if raw is None:
        return None
    url = str(raw.get("url") or "").strip()
    if not url:
        return None
    page_text = _text(raw.get("text") or raw.get("content"))
    highlights = _text(raw.get("highlights"))
    content = "\n\n".join(part for part in (page_text, highlights) if part).strip()
    if not content:
        return None
    return EvidenceDocument(
        url=url,
        content=content,
        title=str(raw.get("title") or ""),
        source_type=classify_source(url),
        collection_method="exa_search",
        effective_date=source_effective_date(dict(raw)),
        collected_at=date.today(),
    ), raw


def _identity_values(
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
) -> dict[str, str]:
    def known_or_unknown(value: str) -> str:
        cleaned = value.strip()
        return cleaned if cleaned and cleaned.casefold() != "unknown" else "unknown"

    return {
        "tool": known_or_unknown(tool_name),
        "vendor": known_or_unknown(vendor),
        "plan": known_or_unknown(offering.plan),
        "deployment_mode": known_or_unknown(offering.deployment_mode),
        "contract_type": known_or_unknown(offering.contract_type),
        "contract_version": known_or_unknown(offering.contract_version),
        "jurisdiction": known_or_unknown(offering.jurisdiction),
    }


def _missing_identity_fields(
    definition: FactSearchConfig,
    *,
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
) -> tuple[str, ...]:
    values = _identity_values(tool_name, vendor, offering)
    return tuple(sorted(
        placeholder for placeholder in definition.placeholders()
        if values[placeholder].casefold() == "unknown"
    ))


def _search_kwargs(
    definition: FactSearchConfig,
    *,
    query: str,
    include_domains: Iterable[str],
    search_type: str | None = None,
) -> dict[str, Any]:
    contents = definition.exa.contents
    return {
        "type": search_type or definition.exa.type,
        "num_results": definition.exa.num_results,
        "include_domains": list(dict.fromkeys(domain for domain in include_domains if domain)),
        "contents": {
            "text": {"max_characters": contents.text.max_characters},
            "highlights": {
                "query": contents.highlights.query,
                "num_sentences": contents.highlights.num_sentences,
            },
            "summary": {
                "query": contents.summary.query,
                "schema": contents.summary.schema_,
            },
        },
    }


def _response_cost_usd(response: Any) -> float | None:
    """Return Exa's own per-request cost (``costDollars.total``) if present.

    Exa's Search response exposes ``cost_dollars`` (``exa_py`` dataclass) or the
    raw ``costDollars`` mapping; either way its ``total`` is Exa's estimate for
    the request actually run — far more accurate than the public-rate fallback.
    A stubbed client or an older API simply omits it, yielding ``None``.
    """
    cost = _field(response, "cost_dollars")
    if cost is None:
        cost = _field(response, "costDollars")
    if cost is None:
        return None
    total = _field(cost, "total")
    try:
        value = float(total)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def estimate_search_cost_usd(
    definition: FactSearchConfig,
    *,
    search_type: str | None = None,
) -> float | None:
    """Return the public-rate estimate for one configured Exa search.

    The current contract-fact configuration always requests an AI summary for
    every result.  Exa's API-key response does not expose charged usage, so an
    unsupported search type deliberately produces ``None`` instead of a guess.
    """
    base_cost = _EXA_SEARCH_BASE_COST_USD.get(search_type or definition.exa.type)
    if base_cost is None:
        return None
    return base_cost + (
        definition.exa.num_results * _EXA_AI_SUMMARY_COST_PER_RESULT_USD
    )


def _unknown(note: str, outcome: str, *, source_url: str | None = None,
             quote: str | None = None, declared_source_url: str | None = None) -> FactEvidence:
    return FactEvidence(
        value="unknown", source_url=source_url, quote=quote,
        declared_source_url=declared_source_url,
        note=note, outcome=outcome,
    )


def _collect_one(
    definition: FactSearchConfig,
    *,
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
    client: ExaClient,
    source_urls: list[str],
    search_type: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> _FactSearchResult:
    missing_fields = _missing_identity_fields(
        definition, tool_name=tool_name, vendor=vendor, offering=offering,
    )
    rendered = definition.render(**_identity_values(tool_name, vendor, offering))
    query = rendered.query
    policy = build_source_policy(
        offering, priority_urls=source_urls, source_urls=source_urls,
    )
    known_domains = [url.split("/", 3)[2] for url in source_urls if "://" in url]
    include_domains = (*rendered.include_domains, *known_domains)
    kwargs = _search_kwargs(
        definition,
        query=query,
        include_domains=include_domains,
        search_type=search_type,
    )

    with trace_step(None, "exa_fact_search", fact=definition.fact) as extra:
        extra.update({
            "query": mask_text(query),
            "missing_identity_fields": list(missing_fields),
            "option_a": definition.selection.strategy,
            "option_d_require_declared_source_url": (
                definition.selection.require_declared_source_url
            ),
        })
        attempts = 0
        while True:
            attempts += 1
            record_exa_search_started()
            try:
                response = client.search(query, **kwargs)
                break
            except Exception as exc:  # noqa: BLE001 - a fact must never abort an interview
                record_exa_search_failed()
                if attempts < max(1, max_attempts) and _is_transient(exc):
                    _sleep_before_retry(attempts)
                    continue
                extra.update(
                    outcome="collection_failure",
                    error=type(exc).__name__,
                    error_status=_http_status(exc),
                    attempts=attempts,
                )
                return _FactSearchResult(
                    definition.fact,
                    _unknown("collecte Exa échouée", "collection_failure"),
                    [],
                    failed=True,
                )
        extra["attempts"] = attempts
        reported_cost = _response_cost_usd(response)
        cost_reported = reported_cost is not None
        cost_usd = (
            reported_cost if cost_reported
            else estimate_search_cost_usd(definition, search_type=search_type)
        )
        record_exa_search_succeeded(cost_usd, reported=cost_reported)
        extra.update(cost_usd=cost_usd, cost_reported=cost_reported)

        documents: list[EvidenceDocument] = []
        accepted: list[tuple[FactEvidence, Mapping[str, Any]]] = []
        rejections: list[str] = []
        result_count = 0
        for result in _results(response):
            document_result = _document_from_result(result)
            if document_result is None:
                continue
            document, raw_result = document_result
            result_count += 1
            if not source_is_allowed(dict(raw_result), policy):
                rejections.append("source_rejected")
                continue
            documents.append(document)
            summary = _summary(result)
            if summary is None:
                rejections.append("summary_missing")
                continue
            value = str(summary.get("value") or "unknown")
            quote = str(summary.get("quote") or "").strip() or None
            declared_url = str(summary.get("source_url") or "").strip() or None
            if (
                definition.selection.require_declared_source_url
                and declared_url != document.url
            ):
                rejections.append("declared_source_url_rejected")
                continue
            if value not in definition.allowed_values:
                rejections.append("invalid_value")
                continue
            if value == "unknown":
                rejections.append("model_abstention")
                continue
            if not quote or not _quote_is_anchored(quote, document.content):
                rejections.append("citation_rejected")
                continue
            accepted.append((
                FactEvidence(
                    value=value,
                    source_url=document.url,
                    quote=quote,
                    declared_source_url=declared_url,
                    confidence=1.0,
                    outcome="accepted",
                    source_type=document.source_type,
                    source_effective_date=document.effective_date,
                    source_collected_at=document.collected_at,
                    source_sha256=document.sha256,
                ),
                raw_result,
            ))

        if accepted:
            # Option A: contractual > DPA > official technical > commercial >
            # secondary, then Exa relevance score.  Sorting is stable, so the
            # search response order breaks an exact tie deterministically.
            proof, selected = min(
                accepted, key=lambda item: source_sort_key(dict(item[1]), policy),
            )
            extra.update(
                outcome="accepted",
                result_count=result_count,
                accepted_candidates=len(accepted),
                selected_source_type=proof.source_type,
                selected_source_url=mask_text(proof.source_url or ""),
            )
            return _FactSearchResult(definition.fact, proof, documents)

        if not result_count:
            proof = _unknown("aucune évidence Exa collectée", "evidence_missing")
        elif rejections and set(rejections) == {"declared_source_url_rejected"}:
            proof = _unknown(
                "URL déclarée par Exa différente de la source du résultat",
                "declared_source_url_rejected",
            )
        elif "citation_rejected" in rejections:
            proof = _unknown(
                "citation introuvable dans la source Exa correspondante",
                "citation_rejected",
            )
        elif "invalid_value" in rejections:
            proof = _unknown(
                "valeur Exa hors des valeurs permises", "invalid_value",
            )
        elif "model_abstention" in rejections:
            proof = FactEvidence(value="unknown", outcome="model_abstention")
        else:
            proof = _unknown("aucune source Exa applicable", "evidence_missing")
        extra.update(
            outcome=proof.outcome,
            result_count=result_count,
            accepted_candidates=0,
            rejected_candidates=len(rejections),
        )
        return _FactSearchResult(definition.fact, proof, documents)


def collect_evidence_from_exa(
    tool_name: str,
    vendor: str,
    offering: ContractOfferingIdentity,
    client: ExaClient,
    *,
    definitions: Iterable[FactSearchConfig] = FACT_SEARCHES,
    max_workers: int = DEFAULT_MAX_WORKERS,
    search_type: str | None = None,
    max_attempts: int | None = None,
) -> ContractEvidence:
    """Collect every configured fact concurrently and degrade independently."""
    configs = tuple(definitions)
    source_urls = contract_source_urls(tool_name, offering)
    workers = max(1, min(max_workers, len(configs)))
    attempts = _configured_attempts() if max_attempts is None else max_attempts
    results: dict[str, _FactSearchResult] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="policybot-exa") as pool:
        futures = {
            pool.submit(
                contextvars.copy_context().run,
                _collect_one,
                definition,
                tool_name=tool_name,
                vendor=vendor,
                offering=offering,
                client=client,
                source_urls=source_urls,
                search_type=search_type,
                max_attempts=attempts,
            ): definition.fact
            for definition in configs
        }
        for future in as_completed(futures):
            fact = futures[future]
            try:
                results[fact] = future.result()
            except Exception as exc:  # defensive boundary around worker setup
                with trace_step(None, "exa_fact_search", fact=fact) as extra:
                    extra.update(outcome="collection_failure", error=type(exc).__name__)
                results[fact] = _FactSearchResult(
                    fact, _unknown("collecte Exa échouée", "collection_failure"), [], True,
                )

    return ContractEvidence(
        documents_by_fact={
            fact: result.documents for fact, result in results.items() if result.documents
        },
        facts={fact: result.proof for fact, result in results.items()},
        failed_facts=tuple(
            fact for fact, result in results.items() if result.failed
        ),
    )


def _configured_workers() -> int:
    raw = os.environ.get("POLICYBOT_EXA_MAX_WORKERS", "")
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_WORKERS
    except ValueError:
        return DEFAULT_MAX_WORKERS


def _configured_attempts() -> int:
    raw = os.environ.get("POLICYBOT_EXA_MAX_ATTEMPTS", "")
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_ATTEMPTS
    except ValueError:
        return DEFAULT_MAX_ATTEMPTS


def _configured_search_type() -> str | None:
    """Return a valid global Exa mode, without overriding YAML by default."""
    configured = os.environ.get("POLICYBOT_EXA_SEARCH_TYPE", "").strip().lower()
    return configured if configured in EXA_SEARCH_TYPES else None


def search_contract_facts_with_exa(
    tool_name: str,
    *,
    offering: ContractOfferingIdentity,
    api_key: str | None = None,
    client: ExaClient | None = None,
    definitions: Iterable[FactSearchConfig] = FACT_SEARCHES,
    max_workers: int | None = None,
    search_type: str | None = None,
    max_attempts: int | None = None,
) -> ContractEvidence | None:
    """Create the real client lazily; a missing key is a clean unknown fallback."""
    configs = tuple(definitions)
    selected_search_type = search_type or _configured_search_type()
    entry = lookup_tool(tool_name) or {}
    vendor = str(entry.get("vendor") or offering.vendor or "")
    active_client = client
    if active_client is None:
        key = api_key or os.environ.get("EXA_API_KEY")
        if not key:
            return None
        try:
            from exa_py import Exa  # imported only for real, opted-in calls
            active_client = Exa(api_key=key)
        except Exception as exc:  # noqa: BLE001 - dependency/auth setup must not abort assessment
            with trace_step(None, "exa_client_init") as extra:
                extra.update(outcome="failed", error=type(exc).__name__)
            return None
    return collect_evidence_from_exa(
        tool_name,
        vendor,
        offering,
        active_client,
        definitions=configs,
        max_workers=max_workers or _configured_workers(),
        search_type=selected_search_type,
        max_attempts=max_attempts,
    )
