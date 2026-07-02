from __future__ import annotations
from datetime import date
from typing import Callable, Optional
import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from policybot.classify.tool_registry import lookup_tool


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
    html = getter(entry["terms_url"])
    return FetchedTerms(
        text=html_to_text(html),
        source_url=entry["terms_url"],
        fetched_at=date.today(),
    )
