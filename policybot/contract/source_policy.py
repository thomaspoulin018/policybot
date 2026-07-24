"""Politique déterministe de sélection et de classement des sources ARP."""
from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlparse

from typing import Literal
from policybot.classify.tool_registry import lookup_tool
from policybot.models import ContractOfferingIdentity

SourceType = Literal[
    "contractual", "dpa", "official_technical", "commercial", "secondary",
]


_FORUM_OR_ARCHIVE_PATTERNS = (
    r"/(?:community|forum|forums)(?:/|$)",
    r"/(?:answers|questions)(?:/|$)",
    r"/(?:archive|archives)(?:/|$)",
)

_SOURCE_TYPE_PATTERNS: tuple[tuple[SourceType, tuple[str, ...]], ...] = (
    ("dpa", ("data-processing", "data_processing", "dpa", "privacy-addendum")),
    ("contractual", ("terms", "agreement", "legal", "policies", "licensing")),
    ("official_technical", ("docs", "learn", "help", "support", "security", "trust", "privacy")),
    ("commercial", ("products", "solutions", "enterprise", "business", "education")),
)

_OFFER_MARKERS = (
    "consumer", "individual", "personal", "free", "plus", "pro", "team",
    "enterprise", "entreprise", "business", "education", "éducation", "edu",
)


def build_source_policy(
    offering: ContractOfferingIdentity,
    *,
    terms_url: str = "",
    priority_urls: list[str] | None = None,
    source_urls: list[str] | None = None,
) -> dict:
    known_urls = list(dict.fromkeys(source_urls or priority_urls or ([terms_url] if terms_url else [])))
    domains = []
    for url in known_urls:
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if domain:
            domains.append(domain)

    contract = offering.contract_type.casefold()
    if "institution" in contract or "enterprise" in offering.plan.casefold():
        excluded_offer_terms = ["consumer", "individual", "personal", "free"]
    elif "consumer" in contract or offering.deployment_mode == "public_saas":
        excluded_offer_terms = ["enterprise agreement", "business terms", "bedrock"]
    else:
        excluded_offer_terms = []

    plan_terms = [
        token.casefold()
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", offering.plan)
        if len(token) >= 4
    ]
    if "entreprise" in plan_terms:
        plan_terms.append("enterprise")
    if "éducation" in plan_terms:
        plan_terms.extend(["education", "edu"])
    return {
        "priority_urls": list(dict.fromkeys(priority_urls or known_urls)),
        "allowed_domains": list(dict.fromkeys(domains)),
        "excluded_domains": [
            value for value in (
                prefix + domain for domain in domains
                for prefix in ("community.", "forum.", "forums.")
            )
        ],
        "allowed_path_prefixes": ["/"],
        "excluded_path_patterns": list(_FORUM_OR_ARCHIVE_PATTERNS),
        "required_offer_terms": plan_terms,
        "excluded_offer_terms": excluded_offer_terms,
    }


def contract_source_urls(
    tool_name: str,
    offering: ContractOfferingIdentity,
) -> list[str]:
    """Return official URLs scoped to the assessed offering, if the registry has them."""
    entry = lookup_tool(tool_name) or {}
    source_sets = entry.get("contract_sources") or {}
    urls = list(source_sets.get(offering.contract_type) or ())
    if not urls and entry.get("terms_url"):
        urls.append(str(entry["terms_url"]))
    return list(dict.fromkeys(url for url in urls if url))


def classify_source(url: str) -> SourceType:
    lowered = url.casefold()
    for source_type, patterns in _SOURCE_TYPE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return source_type
    return "secondary"


def source_is_allowed(result: dict, policy: dict | None) -> bool:
    if not policy:
        return True
    url = str(result.get("url") or "")
    parsed = urlparse(url)
    domain = parsed.netloc.casefold()
    if domain.startswith("www."):
        domain = domain[4:]

    allowed_domains = {str(value).casefold() for value in policy.get("allowed_domains") or []}
    if allowed_domains and not any(
        domain == allowed or domain.endswith(f".{allowed}")
        for allowed in allowed_domains
    ):
        return False
    excluded_domains = {
        str(value).casefold() for value in policy.get("excluded_domains") or []
    }
    if domain in excluded_domains or domain.startswith(("community.", "forum.", "forums.")):
        return False

    path = parsed.path or "/"
    prefixes = tuple(str(value) for value in policy.get("allowed_path_prefixes") or [])
    if prefixes and not path.startswith(prefixes):
        return False
    if any(re.search(pattern, path, flags=re.IGNORECASE)
           for pattern in policy.get("excluded_path_patterns") or []):
        return False

    if url in set(policy.get("priority_urls") or []):
        return True

    scope_text = " ".join((
        url,
        str(result.get("title") or ""),
    )).casefold()
    if any(term.casefold() in scope_text
           for term in policy.get("excluded_offer_terms") or []):
        return False
    required_terms = [
        str(term).casefold() for term in policy.get("required_offer_terms") or []
    ]
    if (
        required_terms
        and any(marker in scope_text for marker in _OFFER_MARKERS)
        and not any(term in scope_text for term in required_terms)
    ):
        return False
    return True


def source_sort_key(result: dict, policy: dict | None) -> tuple[int, float, str]:
    """Option A: source type first, then Exa relevance, then a stable URL tie-break."""
    url = str(result.get("url") or "")
    type_order = {
        "contractual": 0,
        "dpa": 1,
        "official_technical": 2,
        "commercial": 3,
        "secondary": 4,
    }
    try:
        score = -float(result.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    return type_order[classify_source(url)], score, url


def source_effective_date(result: dict) -> date | None:
    for key in ("effective_date", "published_date"):
        raw = result.get(key)
        if not raw:
            continue
        try:
            return date.fromisoformat(str(raw)[:10])
        except ValueError:
            continue
    return None
