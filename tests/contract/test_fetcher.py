import os
import httpx
import pytest
from policybot.contract.fetcher import fetch_terms, fetch_offering_terms, html_to_text
from policybot.models import ContractOfferingIdentity

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "openai_terms.html")


def _fake_get(url):
    with open(FIX, encoding="utf-8") as fh:
        return fh.read()


def _blocked_get(url):
    request = httpx.Request("GET", url)
    response = httpx.Response(403, request=request)
    raise httpx.HTTPStatusError("blocked", request=request, response=response)


def test_html_to_text_strips_scripts_and_styles():
    text = html_to_text(open(FIX, encoding="utf-8").read())
    assert "train our models" in text
    assert "ignore me" not in text
    assert "color:red" not in text


def test_fetch_known_tool_returns_terms():
    res = fetch_terms("ChatGPT", http_get=_fake_get)
    assert res is not None
    assert "train our models" in res.text
    assert res.source_url.startswith("http")


def test_fetch_unknown_tool_returns_none():
    assert fetch_terms("OutilInconnu 9000", http_get=_fake_get) is None


def test_fetch_falls_back_to_none_when_vendor_blocks_the_request():
    assert fetch_terms("ChatGPT", http_get=_blocked_get) is None


def test_fetch_offering_terms_uses_only_the_matching_contract_source_set():
    requested = []

    def get(url):
        requested.append(url)
        return "<html><body>contract</body></html>"

    offering = ContractOfferingIdentity(
        vendor="OpenAI", product="ChatGPT", plan="Enterprise",
        deployment_mode="managed_saas", contract_type="institutional_agreement",
    )

    terms = fetch_offering_terms("ChatGPT", offering, http_get=get)

    assert requested
    assert all("terms-of-use" not in url for url in requested)
    assert any("business-terms" in url for url in requested)
    assert {item.source_url for item in terms} == set(requested)
