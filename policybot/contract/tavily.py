from __future__ import annotations

import os
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.fetcher import FetchedTerms

DEFAULT_CONFIG_DIR = Path("configs") / "tavily_contracts"

FACT_FIELDS: tuple[dict, ...] = (
    {
        "name": "trains_on_input",
        "allowed_values": ["yes", "no", "opt_out_available", "unknown"],
        "query": "{tool} {vendor} terms use customer content prompts to train models opt out",
    },
    {
        "name": "data_retention",
        "allowed_values": ["none", "limited", "indefinite", "unknown"],
        "query": "{tool} {vendor} privacy data retention deletion policy customer data",
    },
    {
        "name": "data_residency",
        "allowed_values": ["canada", "us", "eu", "other", "unknown"],
        "query": "{tool} {vendor} data residency hosting location region subprocessors terms",
    },
    {
        "name": "sub_processors",
        "allowed_values": ["disclosed", "undisclosed", "unknown"],
        "query": "{tool} {vendor} subprocessors sub-processors list privacy terms",
    },
    {
        "name": "human_review",
        "allowed_values": ["yes", "no", "unknown"],
        "query": "{tool} {vendor} human review abuse monitoring customer prompts terms",
    },
    {
        "name": "encryption_standard",
        "allowed_values": ["strong", "partial", "none", "unknown"],
        "query": "{tool} {vendor} encryption in transit at rest security documentation",
    },
    {
        "name": "ip_ownership",
        "allowed_values": ["customer", "vendor", "unclear", "unknown"],
        "query": "{tool} {vendor} ownership output generated content intellectual property terms",
    },
    {
        "name": "applicable_law",
        "allowed_values": ["quebec_canada", "foreign", "unknown"],
        "query": "{tool} {vendor} governing law jurisdiction terms of service",
    },
    {
        "name": "foreign_vendor_dependency",
        "allowed_values": ["yes", "no", "unknown"],
        "query": "{tool} {vendor} company headquarters cloud provider data hosting country",
    },
    {
        "name": "contract_prohibits_reuse",
        "allowed_values": ["yes", "no", "unknown"],
        "query": "{tool} {vendor} contract prohibits reuse customer data confidentiality terms",
    },
    {
        "name": "reentraining_opt_out",
        "allowed_values": ["yes", "no", "unknown"],
        "query": "{tool} {vendor} opt out model training customer data prompts outputs",
    },
    {
        "name": "authentication_support",
        "allowed_values": ["sso_mfa", "partial", "none", "unknown"],
        "query": "{tool} {vendor} SSO SAML OIDC MFA enterprise admin identity provider security documentation",
    },
    {
        "name": "audit_logging",
        "allowed_values": ["prompt_output_accessible", "access_logs_only", "none", "unknown"],
        "query": "{tool} {vendor} audit logs access logs prompt output logs organization admin console trust center",
    },
    {
        "name": "institutional_terms",
        "allowed_values": ["acceptable", "problematic", "unknown"],
        "query": "{tool} {vendor} terms enterprise institutional use education acceptable use DPA privacy terms",
    },
    {
        "name": "quebec_higher_ed_license",
        "allowed_values": ["yes", "no", "unknown"],
        "query": "{tool} {vendor} license education higher education institution public sector government terms",
    },
    {
        "name": "incident_response",
        "allowed_values": ["documented_with_notice", "documented_no_notice", "none", "unknown"],
        "query": "{tool} {vendor} incident response breach notification security incident SLA trust center security policy",
    },)

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
    include_domains = [domain] if domain else []
    context = {"tool": tool_name, "vendor": vendor or tool_name}

    return {
        "tool": {
            "name": tool_name,
            "vendor": vendor,
            "terms_url": terms_url,
        },
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
            "include_domains": include_domains,
        },
        "extract_defaults": {
            "extract_depth": "advanced",
            "format": "markdown",
            "include_images": False,
            "include_favicon": False,
            "timeout": 30,
            "max_urls": 20,
        },
        "fields": [
            {
                "name": field["name"],
                "allowed_values": field["allowed_values"],
                "query": field["query"].format(**context),
            }
            for field in FACT_FIELDS
        ],
    }


def ensure_contract_search_config(
    tool_name: str,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
) -> Path:
    directory = Path(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_slugify(tool_name)}.yaml"
    if not path.exists():
        config = build_contract_search_config(tool_name)
        path.write_text(
            yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return path


def load_contract_search_config(path: Path | str) -> dict:
    with Path(path).open("r", encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    if not isinstance(config, dict):
        raise ValueError("Tavily contract config must be a YAML object.")
    if "fields" not in config or not isinstance(config["fields"], list):
        raise ValueError("Tavily contract config must define a fields list.")
    return config


def _search_kwargs(config: dict, field: dict) -> dict:
    merged = dict(config.get("search_defaults") or {})
    merged.update(field.get("search") or {})
    return {
        key: value
        for key, value in merged.items()
        if key in SEARCH_KEYS and value not in (None, "")
    }


def _extract_kwargs(config: dict) -> dict:
    defaults = dict(config.get("extract_defaults") or {})
    return {
        key: value
        for key, value in defaults.items()
        if key in EXTRACT_KEYS and value not in (None, "")
    }


def _extract_max_urls(config: dict) -> int:
    defaults = dict(config.get("extract_defaults") or {})
    try:
        configured = int(defaults.get("max_urls", 20))
    except (TypeError, ValueError):
        configured = 20
    return max(1, min(configured, 20))


def _response_results(response: object) -> list[dict]:
    if not isinstance(response, dict):
        return []
    results = response.get("results", [])
    return results if isinstance(results, list) else []


def _unique_urls(results: list[dict]) -> list[str]:
    seen = set()
    urls: list[str] = []
    for result in results:
        url = result.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _extract_result_content(result: dict) -> str:
    return (
        result.get("raw_content")
        or result.get("content")
        or result.get("text")
        or ""
    )


def _fallback_search_chunks(results: list[dict]) -> list[str]:
    chunks: list[str] = []
    for result in results:
        url = result.get("url") or ""
        title = result.get("title") or url or "Resultat Tavily"
        content = result.get("raw_content") or result.get("content") or ""
        if not content:
            continue
        chunks.append(
            f"Source recherche Tavily\n"
            f"Titre: {title}\n"
            f"URL: {url}\n"
            f"{content}"
        )
    return chunks


def collect_terms_from_tavily(config: dict, search_func, extract_func=None) -> FetchedTerms | None:
    search_results: list[dict] = []
    tool_name = (config.get("tool") or {}).get("name") or "outil"

    for field in config["fields"]:
        query = field.get("query")
        if not query:
            continue
        response = search_func(query=query, **_search_kwargs(config, field))
        for result in _response_results(response):
            result = dict(result)
            result["field"] = field["name"]
            search_results.append(result)

    urls = _unique_urls(search_results)[:_extract_max_urls(config)]
    chunks: list[str] = []
    if urls and extract_func is not None:
        extracted = extract_func(urls, **_extract_kwargs(config))
        for result in _response_results(extracted):
            url = result.get("url") or ""
            content = _extract_result_content(result)
            if not content:
                continue
            chunks.append(
                f"Source extraite Tavily\n"
                f"URL: {url}\n"
                f"{content}"
            )

    if not chunks:
        chunks = _fallback_search_chunks(search_results)

    if not chunks:
        return None

    source_url = urls[0] if urls else f"tavily://search/{_slugify(tool_name)}"
    return FetchedTerms(
        text="\n\n---\n\n".join(chunks),
        source_url=source_url,
        fetched_at=date.today(),
    )


def search_contract_terms_with_tavily(
    tool_name: str,
    *,
    api_key: str | None = None,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    client=None,
) -> FetchedTerms | None:
    path = ensure_contract_search_config(tool_name, config_dir=config_dir)
    config = load_contract_search_config(path)

    tavily_client = client
    should_close = False
    if tavily_client is None:
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            return None
        from tavily import TavilyClient

        tavily_client = TavilyClient(api_key=key)
        should_close = True

    try:
        return collect_terms_from_tavily(
            config,
            tavily_client.search,
            tavily_client.extract,
        )
    finally:
        if should_close and hasattr(tavily_client, "close"):
            tavily_client.close()
