from __future__ import annotations

import os
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import yaml

from policybot.classify.tool_registry import lookup_tool
from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.contract.families import FACT_FAMILIES
from policybot.contract.offering import build_offering_identity
from policybot.contract.source_policy import (
    build_source_policy,
    classify_source,
    source_effective_date,
    source_is_allowed,
    source_sort_key,
)
from policybot.models import ContractOfferingIdentity
from policybot.tracing import trace_step

DEFAULT_CONFIG_DIR = Path("configs") / "tavily_contracts"
DEFAULT_MARKDOWN_OUTPUT_DIR = Path("output") / "tavily"

CONFIG_SCHEMA_VERSION = 3

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


def build_contract_search_config(
    tool_name: str,
    offering: ContractOfferingIdentity | None = None,
) -> dict:
    entry = lookup_tool(tool_name) or {}
    vendor = entry.get("vendor") or ""
    terms_url = entry.get("terms_url") or ""
    domain = _domain_from_url(terms_url)
    identity = offering or build_offering_identity(
        tool_name,
        entry.get("iag_type") or "publique",
        vendor=vendor or tool_name,
    )
    scope = " ".join(part for part in (
        identity.plan,
        identity.deployment_mode,
        identity.contract_type,
        identity.contract_version,
    ) if part)
    context = {"tool": tool_name, "vendor": vendor or tool_name}
    contract_sources = entry.get("contract_sources") or {}
    priority_urls = list(contract_sources.get(identity.contract_type) or [])

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "tool": {"name": tool_name, "vendor": vendor, "terms_url": terms_url},
        "offering": identity.model_dump(mode="json"),
        "source_policy": build_source_policy(
            identity, terms_url=terms_url, priority_urls=priority_urls,
        ),
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
                "query": " ".join((family.query.format(**context), scope)).strip(),
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
    offering: ContractOfferingIdentity | None = None,
) -> Path:
    directory = Path(config_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"-{offering.cache_key().split(':')[-1][:12]}" if offering else ""
    path = directory / f"{_slugify(tool_name)}{suffix}.yaml"
    if not path.exists() or _is_stale(path):
        path.write_text(
            yaml.safe_dump(
                build_contract_search_config(tool_name, offering),
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


def _error_kind(exc: Exception) -> str:
    """« Ta clé est épuisée » et « la page ne répond pas » n'appellent pas la même réaction."""
    name = type(exc).__name__
    message = str(exc)
    if "APIKey" in name or "401" in message or "403" in message:
        return "auth"
    if "UsageLimit" in name or "429" in message or "quota" in message.lower():
        return "quota"
    return "network"


def _markdown_fence(content: str) -> str:
    """Return a code fence that cannot be closed by *content*."""
    longest_run = max((len(run) for run in re.findall(r"`+", content)), default=0)
    return "`" * max(3, longest_run + 1)


def _markdown_code_block(content: str, language: str = "") -> str:
    fence = _markdown_fence(content)
    return f"{fence}{language}\n{content}\n{fence}"


def _format_tavily_response(response: object) -> str:
    """Serialize a provider response for an ARP audit artifact, never tracing."""
    try:
        return yaml.safe_dump(response, allow_unicode=True, sort_keys=False)
    except Exception:  # noqa: BLE001 — an audit artifact must not stop an interview
        return repr(response)


def _markdown_output_path(tool_name: str, output_dir: Path | str) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    return Path(output_dir) / f"{timestamp}_{_slugify(tool_name)}.md"


def _write_tavily_markdown(
    path: Path,
    config: dict,
    search_responses: dict[str, object],
    search_errors: dict[str, str],
    selected_urls: list[str],
    extract_response: object | None,
    extract_error: str | None,
) -> None:
    """Write the raw Tavily exchange used to collect one ARP's evidence."""
    tool = config.get("tool") or {}
    tool_name = str(tool.get("name") or "Outil inconnu")
    lines = [
        f"# Collecte Tavily — {tool_name}",
        "",
        f"Généré le {datetime.now().astimezone().isoformat(timespec='seconds')}.",
        "",
        "Ce fichier conserve les requêtes et les réponses Tavily brutes utilisées "
        "pour l’ARP. Il ne constitue pas une autorisation.",
        "",
        "## Recherches par famille de critères",
    ]
    for family in config.get("families") or []:
        name = str(family.get("name") or "famille inconnue")
        query = str(family.get("query") or "")
        lines.extend(["", f"### {name}", "", "#### Requête", "", _markdown_code_block(query)])
        if name in search_errors:
            lines.extend(["", "#### Erreur", "", _markdown_code_block(search_errors[name])])
        elif name in search_responses:
            response = _format_tavily_response(search_responses[name])
            lines.extend(["", "#### Réponse Tavily Search", "", _markdown_code_block(response, "yaml")])
        else:
            lines.extend(["", "Aucune réponse n’a été reçue pour cette famille."])

    lines.extend(["", "## Extraction Tavily", "", "### URLs demandées", ""])
    lines.append(_markdown_code_block("\n".join(selected_urls) or "Aucune URL sélectionnée."))
    if extract_error:
        lines.extend(["", "### Erreur", "", _markdown_code_block(extract_error)])
    elif extract_response is not None:
        response = _format_tavily_response(extract_response)
        lines.extend(["", "### Réponse Tavily Extract", "", _markdown_code_block(response, "yaml")])
    else:
        lines.extend(["", "Aucun appel Tavily Extract n’a été nécessaire."])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collect_evidence_from_tavily(
    config: dict, search_func, extract_func=None, *, markdown_output_path: Path | None = None,
) -> ContractEvidence:
    families = config["families"]
    urls_by_family: dict[str, list[str]] = {}
    search_hits: dict[str, dict[str, dict]] = {}  # famille → url → résultat de recherche
    failed: list[str] = []
    search_responses: dict[str, object] = {}
    search_errors: dict[str, str] = {}

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
                search_errors[name] = type(exc).__name__
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
                continue
            search_responses[name] = response
            hits: dict[str, dict] = {}
            priority_candidates = [
                {"url": url, "title": "Source contractuelle prioritaire"}
                for url in (config.get("source_policy") or {}).get("priority_urls") or []
            ]
            candidates = [
                result for result in _response_results(response)
                if source_is_allowed(result, config.get("source_policy"))
            ]
            candidates = priority_candidates + candidates
            candidates.sort(key=lambda result: source_sort_key(
                result, config.get("source_policy"),
            ))
            for result in candidates:
                url = result.get("url") or ""
                if not url:
                    continue
                if url not in hits:
                    hits[url] = result
                else:
                    # Une URL prioritaire peut aussi être revenue dans Search.
                    # Garder son rang, mais enrichir son placeholder avec le
                    # titre, le score et le contenu réellement collectés.
                    hits[url] = {**hits[url], **{
                        key: value for key, value in result.items()
                        if value not in (None, "", [], {})
                    }}
            extra["outcome"] = "ok"
            extra["hits"] = len(hits)
        if hits:
            urls_by_family[name] = list(hits)
            search_hits[name] = hits

    selected = _round_robin_urls(urls_by_family, _extract_budget(config))
    extracted_by_url: dict[str, str] = {}
    extract_response: object | None = None
    extract_error: str | None = None
    if selected and extract_func is not None:
        with trace_step(None, "tavily_extract", urls=len(selected)) as extra:
            try:
                response = extract_func(selected, **_extract_kwargs(config))
            except Exception as exc:  # noqa: BLE001 — repli sur le contenu de recherche
                response = {}
                extract_error = type(exc).__name__
                extra["outcome"] = "failed"
                extra["error_kind"] = _error_kind(exc)
                extra["error"] = type(exc).__name__
            else:
                extra["outcome"] = "ok"
                extract_response = response
            for result in _response_results(response):
                url = result.get("url") or ""
                content = _extract_result_content(result)
                if url and content:
                    extracted_by_url[url] = content
            extra["extracted"] = len(extracted_by_url)

    documents_by_family: dict[str, list[EvidenceDocument]] = {}
    for name, hits in search_hits.items():
        documents: list[EvidenceDocument] = []
        offering_effective_date = (config.get("offering") or {}).get("effective_date")
        try:
            default_effective_date = (
                date.fromisoformat(offering_effective_date)
                if offering_effective_date else None
            )
        except ValueError:
            default_effective_date = None
        for url, result in hits.items():
            if url in extracted_by_url:
                content = extracted_by_url[url]
            else:
                content = result.get("raw_content") or result.get("content") or ""
            if content:
                documents.append(EvidenceDocument(
                    url=url,
                    title=str(result.get("title") or ""),
                    content=content,
                    source_type=classify_source(url),
                    collection_method=("extract" if url in extracted_by_url else "search"),
                    effective_date=source_effective_date(result) or default_effective_date,
                    collected_at=date.today(),
                ))
        if documents:
            documents_by_family[name] = documents

    if markdown_output_path is not None:
        with trace_step(None, "tavily_markdown", path=str(markdown_output_path)) as extra:
            try:
                _write_tavily_markdown(
                    markdown_output_path,
                    config,
                    search_responses,
                    search_errors,
                    selected,
                    extract_response,
                    extract_error,
                )
            except Exception as exc:  # noqa: BLE001 — optional audit output never blocks ARP
                extra["outcome"] = "failed"
                extra["error"] = type(exc).__name__
            else:
                extra["outcome"] = "ok"

    return ContractEvidence(
        documents_by_family=documents_by_family,
        failed_families=tuple(failed),
    )


def search_contract_terms_with_tavily(
    tool_name: str,
    *,
    offering: ContractOfferingIdentity | None = None,
    api_key: str | None = None,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    markdown_output_dir: Path | str | None = None,
    client=None,
) -> ContractEvidence | None:
    path = ensure_contract_search_config(
        tool_name, config_dir=config_dir, offering=offering,
    )
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

    output_dir = markdown_output_dir
    if output_dir is None:
        output_dir = os.getenv("POLICYBOT_TAVILY_MARKDOWN_DIR") or DEFAULT_MARKDOWN_OUTPUT_DIR
    markdown_path = _markdown_output_path(tool_name, output_dir)

    try:
        evidence = collect_evidence_from_tavily(
            config,
            tavily_client.search,
            tavily_client.extract,
            markdown_output_path=markdown_path,
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
