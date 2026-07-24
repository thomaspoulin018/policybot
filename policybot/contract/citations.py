"""Validation, normalisation et liens profonds des citations Exa."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from urllib.parse import quote, urlsplit, urlunsplit

from policybot.contract.source_policy import classify_source
from policybot.models import CriterionCitation


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _quote_is_anchored(quote_text: str, page_text: str) -> bool:
    needle = _normalize(quote_text).casefold()
    haystack = _normalize(page_text).casefold()
    return bool(needle) and needle in haystack


def _find_offsets(quote_text: str, page_text: str) -> tuple[int, int] | None:
    exact = page_text.find(quote_text)
    if exact >= 0:
        return exact, exact + len(quote_text)
    words = [re.escape(word) for word in quote_text.split()]
    if not words:
        return None
    match = re.search(r"\s+".join(words), page_text, flags=re.IGNORECASE)
    return (match.start(), match.end()) if match else None


def build_deep_link(url: str, text: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not text:
        return url
    words = _normalize(text).split()
    if len(words) <= 12:
        directive = quote(" ".join(words), safe="")
    else:
        directive = (
            f"{quote(' '.join(words[:5]), safe='')},"
            f"{quote(' '.join(words[-5:]), safe='')}"
        )
    anchor = parsed.fragment.split(":~:", 1)[0]
    return urlunsplit(parsed._replace(fragment=f"{anchor}:~:text={directive}"))


def validated_citation(
    *,
    url: str,
    title: str,
    page_text: str,
    quote_text: str,
    begin: int | None = None,
    end: int | None = None,
) -> CriterionCitation | None:
    extracted = ""
    if (
        isinstance(begin, int) and isinstance(end, int)
        and 0 <= begin < end <= len(page_text)
    ):
        candidate = page_text[begin:end]
        if _quote_is_anchored(candidate, page_text) and (
            not quote_text or _normalize(candidate).casefold() == _normalize(quote_text).casefold()
        ):
            extracted = candidate
    if not extracted:
        if not _quote_is_anchored(quote_text, page_text):
            return None
        offsets = _find_offsets(quote_text, page_text)
        if offsets is None:
            return None
        begin, end = offsets
        extracted = page_text[begin:end]
    return CriterionCitation(
        url=url,
        title=title,
        text=extracted,
        begin=begin,
        end=end,
        anchored=True,
        deep_link=build_deep_link(url, extracted),
        source_type=classify_source(url),
        collected_at=date.today(),
    )
