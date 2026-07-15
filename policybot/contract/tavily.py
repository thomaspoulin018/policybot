from __future__ import annotations

import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms
from policybot.tracing import trace_step

DEFAULT_CONFIG_DIR = Path("configs") / "tavily_contracts"

CONFIG_SCHEMA_VERSION = 2

SEARCH_KEYS = {
    "search_depth",
    "max_results",
    "topic",
    "include_answer",
    "include_raw_content",
    "include_images",
    "include_image_descriptions",
    "include_favicon",
    "include_domains",
    "exclude_domains",
    "country",
    "auto_parameters",
    "time_range",
    "start_date",
    "end_date",
    "include_usage",
    "safe_search",
}

EXTRACT_KEYS = {
    "extract_depth",
    "format",
    "include_images",
    "include_favicon",
    "include_usage",
    "timeout",
}


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug or "outil"


def _domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        return netloc[4:]
    return netloc or None


def build_contract_search_config(tool_name: str) -> dict:
    entry = lookup_tool(tool_name) or {}
    vendor = entry.get("vendor") or ""
    terms_url = entry.get("terms_url") or ""
    domain = _domain_from_url(terms_url)
    context = {"tool": tool_name, "vendor": vendor or tool_name}

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "tool": {"name": tool_name, "vendor": vendor, "terms_url": terms_url},
        "search_defaults": {
            "search_depth": "advanced",
            "max_results": 5,
            "topic": "general",
            "include_answer": False,
            "include_raw_content": True,
            "include_images": False,
            "include_favicon": False,
            "country": "canada",
            "safe_search": False,
            "include_domains": [domain] if domain else [],
        },
        "extract_defaults": {
            "extract_depth": "advanced",
            "format": "markdown",
            "include_images": False,
            "include_favicon": False,
            "timeout": 30,
            "max_urls": 20,
        },
        "families": [
            {
                "name": family.name,
                "query": family.query.format(**context),
                "fields": [
                    {"name": field.name, "allowed_values": list(field.allowed_values)}
                    for field in family.fields
                ],
            }
            for family in FACT_FAMILIES
        ],
    }


def _is_stale(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as fh:
            existing = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return True
    if not isinstance(existing, dict):
        return True
    return int(existing.get("schema_version", 0)) < CONFIG_SCHEMA_VERSION


def ensure_contract_search_config(
    tool_name: str,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> Path:
    directory = Path(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slugify(tool_name)}.yaml"
    if not path.exists() or _is_stale(path):
        path.write_text(
            yaml.safe_dump(
                build_contract_search_config(tool_name),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    return path


def load_contract_search_config(path: Path | str) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if not isinstance(config, dict):
        raise ValueError("Tavily contract config must be a YAML object.")
    if not isinstance(config.get("families"), list):
        raise ValueError("Tavily contract config must define a families list.")
    return config


def _extract_kwargs(config: dict) -> dict:
    defaults = dict(config.get("extract_defaults") or {})
    return {
        key: value
        for key, value in defaults.items()
        if key in EXTRACT_KEYS and value not in (None, "")
    }


def _response_results(response: object) -> list[dict]:
    if not isinstance(response, dict):
        return []
    results = response.get("results", [])
    if not isinstance(results, list):
        return []
    # Ne garder que les éléments dict : un résultat mal formé (chaîne, None)
    # ferait autrement lever `.get()` jusqu'à Interview.assess.
    return [result for result in results if isinstance(result, dict)]


def _extract_result_content(result: dict) -> str:
    return (
        result.get("raw_content")
        or result.get("content")
        or result.get("text")
        or ""
    )


TAVILY_EXTRACT_HARD_LIMIT = 20


def _family_search_kwargs(config: dict, family: dict) -> dict:
    merged = dict(config.get("search_defaults") or {})
    merged.update(family.get("search") or {})
    return {
        key: value
        for key, value in merged.items()
        if key in SEARCH_KEYS and value not in (None, "")
    }


def _round_robin_urls(urls_by_family: dict[str, list[str]], budget: int) -> list[str]:
    """Un quota égal par famille, servi en alternance, plafonné à la limite Tavily.

    Sert la première URL de chaque famille, puis la deuxième, etc. — sans quoi
    les familles interrogées en premier mangeraient tout le budget.
    """
    per_family = max(1, budget // max(1, len(urls_by_family)))
    ordered: list[str] = []
    seen: set[str] = set()
    for rank in range(per_family):
        for urls in urls_by_family.values():
            if rank >= len(urls):
                continue
            url = urls[rank]
            if url in seen:
                continue
            seen.add(url)
            ordered.append(url)
            if len(ordered) >= budget:
                return ordered
    return ordered


def _extract_budget(config: dict) -> int:
    defaults = dict(config.get("extract_defaults") or {})
    try:
        configured = int(defaults.get("max_urls", TAVILY_EXTRACT_HARD_LIMIT))
    except (TypeError, ValueError):
        configured = TAVILY_EXTRACT_HARD_LIMIT
    return max(1, min(configured, TAVILY_EXTRACT_HARD_LIMIT))


def _family_chunk(url: str, content: str, extracted: bool) -> str:
    origin = "Source extraite Tavily" if extracted else "Source recherche Tavily"
    return f"{origin}\nURL: {url}\n{content}"


def _error_kind(exc: Exception) -> str:
    """« Ta clé est épuisée » et « la page ne répond pas » n'appellent pas la même réaction."""
    name = type(exc).__name__
    message = str(exc)
    if "APIKey" in name or "401" in message or "403" in message:
        return "auth"
    if "UsageLimit" in name or "429" in message or "quota" in message.lower():
        return "quota"
    return "network"


def collect_evidence_from_tavily(
    config: dict, search_func, extract_func=None,
) -> ContractEvidence:
    families = config["families"]
    urls_by_family: dict[str, list[str]] = {}
    search_hits: dict[str, dict[str, dict]] = {}  # famille → url → résultat de recherche
    failed: list[str] = []

    for family in families:
        query = family.get("query")
        if not query:
            continue
        name = family["name"]
        with trace_step(None, "tavily_family_search", family=name) as extra:
            try:
                response = search_func(query=query, **_family_search_kwargs(config, family))
            except Exception as exc:  # noqa: BLE001 — une famille perdue ne doit pas tuer l'entrevue
                failed.append(name)
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
                continue
            hits: dict[str, dict] = {}
            for result in _response_results(response):
                url = result.get("url") or ""
                if url and url not in hits:
                    hits[url] = result
            extra["outcome"] = "ok"
            extra["hits"] = len(hits)
        if hits:
            urls_by_family[name] = list(hits)
            search_hits[name] = hits

    selected = _round_robin_urls(urls_by_family, _extract_budget(config))
    extracted_by_url: dict[str, str] = {}
    if selected and extract_func is not None:
        with trace_step(None, "tavily_extract", urls=len(selected)) as extra:
            try:
                response = extract_func(selected, **_extract_kwargs(config))
            except Exception as exc:  # noqa: BLE001 — repli sur le contenu de recherche
                response = {}
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
            else:
                extra["outcome"] = "ok"
            for result in _response_results(response):
                url = result.get("url") or ""
                content = _extract_result_content(result)
                if url and content:
                    extracted_by_url[url] = content
            extra["extracted"] = len(extracted_by_url)

    by_family: dict[str, FetchedTerms] = {}
    for name, hits in search_hits.items():
        chunks: list[str] = []
        for url, result in hits.items():
            if url in extracted_by_url:
                chunks.append(_family_chunk(url, extracted_by_url[url], extracted=True))
                continue
            content = result.get("raw_content") or result.get("content") or ""
            if content:
                chunks.append(_family_chunk(url, content, extracted=False))
        if chunks:
            by_family[name] = FetchedTerms(
                text="\n\n---\n\n".join(chunks),
                source_url=next(iter(hits)),
                fetched_at=date.today(),
            )

    return ContractEvidence(by_family=by_family, failed_families=tuple(failed))


def search_contract_terms_with_tavily(
    tool_name: str,
    *,
    api_key: str | None = None,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    client=None,
) -> ContractEvidence | None:
    path = ensure_contract_search_config(tool_name, config_dir=config_dir)
    config = load_contract_search_config(path)

    tavily_client = client
    should_close = False
    if tavily_client is None:
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            return None
        try:
            from tavily import TavilyClient

            tavily_client = TavilyClient(api_key=key)
        except Exception as exc:  # noqa: BLE001 — clé invalide ou paquet absent
            with trace_step(None, "tavily_client_init") as extra:
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
            return None
        should_close = True

    try:
        evidence = collect_evidence_from_tavily(
            config, tavily_client.search, tavily_client.extract,
        )
    finally:
        if should_close and hasattr(tavily_client, "close"):
            try:
                tavily_client.close()
            except Exception as exc:  # noqa: BLE001 — une fermeture ratée ne doit pas tuer l'entrevue
                with trace_step(None, "tavily_client_close") as extra:
                    extra["outcome"] = "failed"
                    extra["error_kind"] = _error_kind(exc)

    return None if evidence.is_empty() else evidence
