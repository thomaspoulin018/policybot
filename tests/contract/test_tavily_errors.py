from datetime import date

import httpx
import pytest

from policybot.contract.tavily import (
    _error_kind,
    collect_evidence_from_tavily,
    search_contract_terms_with_tavily,
)
from policybot.contract.evidence import ContractEvidence
from policybot.contract.fetcher import FetchedTerms
from policybot.interview.orchestrator import Interview
from policybot.llm.fake import FakeLLMProvider
from policybot.models import RequestInfo
from policybot.preapproved.store import PreApprovedStore
from tests.helpers.arp_fixtures import arp_extraction_responses

CONFIG = {
    "tool": {"name": "ToolX"},
    "search_defaults": {"max_results": 5},
    "extract_defaults": {"max_urls": 20},
    "families": [
        {"name": "entrainement_reutilisation", "query": "ToolX training", "fields": []},
        {"name": "securite_technique", "query": "ToolX security", "fields": []},
    ],
}


def test_a_failed_family_search_degrades_only_that_family():
    def search(**kwargs):
        if "training" in kwargs["query"]:
            raise httpx.ConnectError("tavily unreachable")
        return {"results": [{"url": "https://example.test/security", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [{"url": urls[0], "raw_content": "Contenu sécurité"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert evidence.failed_families == ("entrainement_reutilisation",)
    assert "entrainement_reutilisation" not in evidence.by_family
    assert "Contenu sécurité" in evidence.by_family["securite_technique"].text


def test_a_failed_extract_falls_back_to_search_content():
    def search(**kwargs):
        return {"results": [{
            "url": "https://example.test/terms",
            "content": "Évidence de recherche conservée malgré l'échec d'Extract.",
        }]}

    def extract(urls, **kwargs):
        raise httpx.ReadTimeout("extract timed out")

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert evidence.failed_families == ()
    assert "Évidence de recherche conservée" in (
        evidence.by_family["entrainement_reutilisation"].text
    )


def test_every_family_failing_yields_empty_evidence():
    def search(**kwargs):
        raise httpx.ConnectError("tavily unreachable")

    evidence = collect_evidence_from_tavily(CONFIG, search)

    assert evidence.is_empty()
    assert set(evidence.failed_families) == {"entrainement_reutilisation", "securite_technique"}


def test_error_kind_distinguishes_auth_quota_and_network():
    class InvalidAPIKeyError(Exception):
        pass

    class UsageLimitExceededError(Exception):
        pass

    assert _error_kind(InvalidAPIKeyError("bad key")) == "auth"
    assert _error_kind(UsageLimitExceededError("plan limit")) == "quota"
    assert _error_kind(httpx.ConnectError("boom")) == "network"


def test_search_returns_none_without_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    assert search_contract_terms_with_tavily("ChatGPT", config_dir=tmp_path) is None


def test_search_returns_none_when_all_families_fail(tmp_path):
    class BrokenClient:
        def search(self, **kwargs):
            raise httpx.ConnectError("tavily unreachable")

        def extract(self, urls, **kwargs):
            raise AssertionError("extract should not run when every search failed")

    assert search_contract_terms_with_tavily(
        "ChatGPT", api_key="unused", config_dir=tmp_path, client=BrokenClient(),
    ) is None


def test_interview_uses_injected_tavily_terms_before_direct_fetch(tmp_path):
    tavily_evidence_text = "Tavily evidence: customer content is not used for training."
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(trains_on_input="no", evidence=tavily_evidence_text),
    ])

    def tavily_search(tool_name):
        assert tool_name == "ChatGPT"
        return ContractEvidence.from_single(FetchedTerms(
            text=tavily_evidence_text,
            source_url="https://example.test/tavily",
            fetched_at=date.today(),
        ))

    def direct_fetch_should_not_run(url):
        raise AssertionError("direct fetch should not run when Tavily returns terms")

    itv = Interview(
        llm=llm,
        store=PreApprovedStore(str(tmp_path / "pb.db")),
        http_get=direct_fetch_should_not_run,
        tavily_search=tavily_search,
    )
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-TAVILY"),
        tool_name="ChatGPT",
        usage_inputs=[{
            "description": "Recherche publique",
            "data_description": "information publique",
            "automated_decisions": False,
            "mode": ["prompt"],
            "result_use": [],
        }],
    )

    assert state.tools[0].arp is not None
    assert state.tools[0].arp.contract_facts.source_url == "https://example.test/tavily"
    assert state.tools[0].arp.contract_facts.trains_on_input == "no"
