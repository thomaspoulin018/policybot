from __future__ import annotations
import logging
from datetime import date
from typing import Callable, Optional
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from policybot.classify.tool_registry import lookup_tool
from policybot.models import ContractOfferingIdentity

logger = logging.getLogger(__name__)


class FetchedTerms(BaseModel):
    text: str
    source_url: str
    fetched_at: date


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _default_get(url: str) -> str:
    resp = httpx.get(url, timeout=30.0, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_terms(
    tool_name: str,
    http_get: Optional[Callable[[str], str]] = None,
) -> Optional[FetchedTerms]:
    entry = lookup_tool(tool_name)
    if not entry or not entry.get("terms_url"):
        return None  # caller falls back to manual paste
    getter = http_get or _default_get
    try:
        html = getter(entry["terms_url"])
    except httpx.HTTPError:
        # Vendor site unreachable or blocking automated fetches (e.g. a
        # Cloudflare bot challenge) — fall back to manual paste instead of
        # failing the whole assessment.
        logger.warning(
            "terms fetch failed for tool_name=%r url=%s; falling back to manual paste",
            tool_name, entry["terms_url"], exc_info=True,
        )
        return None
    return FetchedTerms(
        text=html_to_text(html),
        source_url=entry["terms_url"],
        fetched_at=date.today(),
    )


def fetch_offering_terms(
    tool_name: str,
    offering: ContractOfferingIdentity,
    http_get: Optional[Callable[[str], str]] = None,
) -> list[FetchedTerms]:
    """Récupère les sources prioritaires de l'offre, jamais celles d'un autre plan."""
    entry = lookup_tool(tool_name) or {}
    configured = entry.get("contract_sources") or {}
    urls = list(configured.get(offering.contract_type) or [])
    if not urls and entry.get("terms_url"):
        urls = [entry["terms_url"]]
    getter = http_get or _default_get
    collected: list[FetchedTerms] = []
    for url in dict.fromkeys(urls):
        try:
            html = getter(url)
        except httpx.HTTPError:
            logger.warning(
                "offering terms fetch failed for tool_name=%r url=%s",
                tool_name, url, exc_info=True,
            )
            continue
        collected.append(FetchedTerms(
            text=html_to_text(html),
            source_url=url,
            fetched_at=date.today(),
        ))
    return collected
