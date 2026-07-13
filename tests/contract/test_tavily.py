from datetime import date

from policybot.contract.fetcher import FetchedTerms
from policybot.contract.tavily import (
    FACT_FIELDS,
    build_contract_search_config,
    collect_terms_from_tavily,
    ensure_contract_search_config,
    load_contract_search_config,
    search_contract_terms_with_tavily,
)
from policybot.interview.orchestrator import Interview
from policybot.llm.fake import FakeLLMProvider
from policybot.models import RequestInfo
from policybot.preapproved.store import PreApprovedStore


def test_build_contract_search_config_covers_all_contract_fact_fields():
    config = build_contract_search_config("ChatGPT")

    assert config["tool"]["name"] == "ChatGPT"
    assert config["tool"]["vendor"] == "OpenAI"
    assert config["search_defaults"]["include_domains"] == ["openai.com"]
    assert config["extract_defaults"]["format"] == "markdown"
    assert {field["name"] for field in config["fields"]} == {
        field["name"] for field in FACT_FIELDS
    }
    assert all("ChatGPT" in field["query"] for field in config["fields"])
    queries_by_field = {field["name"]: field["query"].lower() for field in config["fields"]}
    assert "sso" in queries_by_field["authentication_support"]
    assert "audit logs" in queries_by_field["audit_logging"]
    assert "institutional use" in queries_by_field["institutional_terms"]
    assert "higher education" in queries_by_field["quebec_higher_ed_license"]
    assert "breach notification" in queries_by_field["incident_response"]


def test_ensure_contract_search_config_writes_yaml_once(tmp_path):
    path = ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path)
    loaded = load_contract_search_config(path)

    assert path.name == "chatgpt-pro.yaml"
    assert loaded["tool"]["name"] == "ChatGPT Pro"
    assert len(loaded["fields"]) == len(FACT_FIELDS)
    assert loaded["extract_defaults"]["extract_depth"] == "advanced"

    path.write_text("fields: []\n", encoding="utf-8")
    assert ensure_contract_search_config("ChatGPT Pro", config_dir=tmp_path) == path
    assert load_contract_search_config(path)["fields"] == []


def test_collect_terms_from_tavily_searches_then_extracts_unique_urls():
    config = {
        "tool": {"name": "ToolX"},
        "search_defaults": {"max_results": 2, "include_raw_content": True},
        "extract_defaults": {"extract_depth": "advanced", "format": "markdown"},
        "fields": [
            {"name": "trains_on_input", "query": "ToolX training"},
            {"name": "data_retention", "query": "ToolX retention"},
        ],
    }
    search_calls = []
    extract_calls = []

    def search(**kwargs):
        search_calls.append(kwargs)
        return {
            "results": [
                {"url": "https://example.test/legal", "title": "Terms", "content": "Snippet"},
                {"url": "https://example.test/legal", "title": "Duplicate", "content": "Duplicate"},
            ]
        }

    def extract(urls, **kwargs):
        extract_calls.append((urls, kwargs))
        return {
            "results": [{
                "url": "https://example.test/legal",
                "raw_content": "Full extracted legal/security/privacy content.",
            }]
        }

    terms = collect_terms_from_tavily(config, search, extract)

    assert terms is not None
    assert terms.source_url == "https://example.test/legal"
    assert "Source extraite Tavily" in terms.text
    assert "Full extracted legal/security/privacy content." in terms.text
    assert "Snippet" not in terms.text
    assert search_calls[0]["max_results"] == 2
    assert extract_calls == [(["https://example.test/legal"], {"extract_depth": "advanced", "format": "markdown"})]


def test_collect_terms_from_tavily_caps_extract_urls_at_tavily_limit():
    config = {
        "tool": {"name": "ToolX"},
        "extract_defaults": {"max_urls": 50},
        "fields": [{"name": "trains_on_input", "query": "ToolX legal"}],
    }
    captured = {}

    def search(**kwargs):
        return {
            "results": [
                {"url": f"https://example.test/{index}", "content": "Snippet"}
                for index in range(25)
            ]
        }

    def extract(urls, **kwargs):
        captured["urls"] = urls
        return {
            "results": [{
                "url": urls[0],
                "raw_content": "Extracted content from capped URL list.",
            }]
        }

    terms = collect_terms_from_tavily(config, search, extract)

    assert terms is not None
    assert len(captured["urls"]) == 20
    assert captured["urls"][0] == "https://example.test/0"
    assert captured["urls"][-1] == "https://example.test/19"

def test_collect_terms_from_tavily_falls_back_to_search_content_without_extract():
    config = {
        "tool": {"name": "ToolX"},
        "fields": [{"name": "trains_on_input", "query": "ToolX training"}],
    }

    def search(**kwargs):
        return {
            "results": [{
                "url": "https://example.test/terms",
                "title": "Terms",
                "content": "Search-result evidence when Extract is unavailable.",
            }]
        }

    terms = collect_terms_from_tavily(config, search)

    assert terms is not None
    assert terms.source_url == "https://example.test/terms"
    assert "Source recherche Tavily" in terms.text
    assert "Search-result evidence" in terms.text


def test_search_contract_terms_with_tavily_uses_generated_config_and_client(tmp_path):
    class FakeTavilyClient:
        def __init__(self):
            self.queries = []
            self.extracted_urls = []
            self.closed = False

        def search(self, **kwargs):
            self.queries.append(kwargs["query"])
            return {
                "results": [{
                    "url": "https://example.test/security",
                    "content": "Snippet: Customer data is encrypted.",
                }]
            }

        def extract(self, urls, **kwargs):
            self.extracted_urls.append((urls, kwargs))
            return {
                "results": [{
                    "url": "https://example.test/security",
                    "raw_content": "Customer data is encrypted at rest and in transit.",
                }]
            }

        def close(self):
            self.closed = True

    client = FakeTavilyClient()
    terms = search_contract_terms_with_tavily(
        "ChatGPT",
        api_key="not-used-with-injected-client",
        config_dir=tmp_path,
        client=client,
    )

    assert terms is not None
    assert (tmp_path / "chatgpt.yaml").exists()
    assert len(client.queries) == len(FACT_FIELDS)
    assert client.extracted_urls
    assert "Customer data is encrypted" in terms.text
    assert "Snippet" not in terms.text


def test_interview_uses_injected_tavily_terms_before_direct_fetch(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes",
         "encryption_standard": "strong", "ip_ownership": "customer",
         "extraction_confidence": 0.9},
    ])

    def tavily_search(tool_name):
        assert tool_name == "ChatGPT"
        return FetchedTerms(
            text="Tavily evidence: customer content is not used for training.",
            source_url="https://example.test/tavily",
            fetched_at=date.today(),
        )

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
