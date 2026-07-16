import pytest

from policybot.contract.tavily import collect_evidence_from_tavily

CONFIG = {
    "tool": {"name": "ToolX"},
    "search_defaults": {"max_results": 5, "include_raw_content": True},
    "extract_defaults": {"extract_depth": "advanced", "format": "markdown", "max_urls": 20},
    "families": [
        {"name": "entrainement_reutilisation", "query": "ToolX training", "fields": []},
        {"name": "securite_technique", "query": "ToolX security", "fields": []},
    ],
}


def test_one_search_per_family_and_evidence_indexed_by_family():
    queries = []

    def search(**kwargs):
        queries.append(kwargs["query"])
        slug = "training" if "training" in kwargs["query"] else "security"
        return {"results": [{"url": f"https://example.test/{slug}", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [
            {"url": url, "raw_content": f"Contenu complet de {url}"} for url in urls
        ]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert queries == ["ToolX training", "ToolX security"]
    assert set(evidence.by_family) == {"entrainement_reutilisation", "securite_technique"}
    assert "Contenu complet de https://example.test/training" in (
        evidence.by_family["entrainement_reutilisation"].text
    )
    assert "security" not in evidence.by_family["entrainement_reutilisation"].text
    assert evidence.failed_families == ()


def test_a_url_found_by_two_families_is_extracted_once_and_feeds_both():
    extract_calls = []

    def search(**kwargs):
        return {"results": [{"url": "https://example.test/cgu", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        extract_calls.append(list(urls))
        return {"results": [{"url": "https://example.test/cgu", "raw_content": "CGU partagées"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert extract_calls == [["https://example.test/cgu"]]
    assert "CGU partagées" in evidence.by_family["entrainement_reutilisation"].text
    assert "CGU partagées" in evidence.by_family["securite_technique"].text


def test_extraction_budget_is_shared_round_robin_between_families():
    def search(**kwargs):
        slug = "t" if "training" in kwargs["query"] else "s"
        return {"results": [
            {"url": f"https://example.test/{slug}{index}", "content": "Snippet"}
            for index in range(10)
        ]}

    captured = {}

    def extract(urls, **kwargs):
        captured["urls"] = list(urls)
        return {"results": [{"url": url, "raw_content": f"Contenu {url}"} for url in urls]}

    collect_evidence_from_tavily(CONFIG, search, extract)

    urls = captured["urls"]
    assert len(urls) == 20
    assert sum(1 for url in urls if "/t" in url) == 10
    assert sum(1 for url in urls if "/s" in url) == 10
    assert urls[0].endswith("/t0") and urls[1].endswith("/s0")


def test_falls_back_to_search_content_when_extract_is_unavailable():
    def search(**kwargs):
        return {"results": [{
            "url": "https://example.test/terms",
            "title": "Terms",
            "content": "Évidence issue de la recherche, sans Extract.",
        }]}

    evidence = collect_evidence_from_tavily(CONFIG, search)

    terms = evidence.by_family["entrainement_reutilisation"]
    assert "Source recherche Tavily" in terms.text
    assert "Évidence issue de la recherche" in terms.text
    assert terms.source_url == "https://example.test/terms"


def test_a_family_without_results_is_absent_from_the_evidence():
    def search(**kwargs):
        if "training" in kwargs["query"]:
            return {"results": []}
        return {"results": [{"url": "https://example.test/security", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [{"url": urls[0], "raw_content": "Contenu sécurité"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert "entrainement_reutilisation" not in evidence.by_family
    assert "securite_technique" in evidence.by_family
    assert not evidence.is_empty()


def test_malformed_result_elements_do_not_raise():
    # Un résultat mal formé (chaîne au lieu de dict) ne doit pas remonter en
    # exception jusqu'à Interview.assess — il est simplement ignoré.
    def search(**kwargs):
        return {"results": ["oops-not-a-dict", {"url": "https://example.test/ok", "content": "Snippet"}]}

    def extract(urls, **kwargs):
        return {"results": [None, {"url": "https://example.test/ok", "raw_content": "Contenu"}]}

    evidence = collect_evidence_from_tavily(CONFIG, search, extract)

    assert "Contenu" in evidence.by_family["entrainement_reutilisation"].text


def test_writes_raw_search_and_extract_responses_to_markdown(tmp_path):
    output_path = tmp_path / "tavily.md"

    def search(**kwargs):
        return {"results": [{
            "url": "https://example.test/terms",
            "title": "Terms",
            "content": "Search result content",
        }]}

    def extract(urls, **kwargs):
        return {"results": [{
            "url": urls[0],
            "raw_content": "Extracted contract content",
        }]}

    collect_evidence_from_tavily(
        CONFIG, search, extract, markdown_output_path=output_path,
    )

    report = output_path.read_text(encoding="utf-8")
    assert "ToolX training" in report
    assert "Search result content" in report
    assert "Extracted contract content" in report
    assert "https://example.test/terms" in report


def test_source_policy_rejects_forums_archives_and_wrong_offers():
    config = {
        **CONFIG,
        "source_policy": {
            "priority_urls": ["https://example.test/legal/enterprise-terms"],
            "allowed_domains": ["example.test"],
            "allowed_path_prefixes": ["/legal", "/docs"],
            "excluded_path_patterns": ["/forum", "/archives"],
            "required_offer_terms": ["enterprise"],
            "excluded_offer_terms": ["consumer", "individual"],
        },
    }

    def search(**kwargs):
        return {"results": [
            {"url": "https://example.test/forum/enterprise", "title": "Enterprise forum", "content": "x"},
            {"url": "https://example.test/legal/archives/enterprise", "title": "Enterprise archive", "content": "x"},
            {"url": "https://example.test/legal/consumer-terms", "title": "Consumer terms", "content": "x"},
            {"url": "https://example.test/legal/team-terms", "title": "Team agreement", "content": "x"},
            {"url": "https://example.test/legal/enterprise-terms", "title": "Enterprise agreement", "content": "valid"},
        ]}

    evidence = collect_evidence_from_tavily(config, search)

    documents = evidence.documents_by_family["entrainement_reutilisation"]
    assert [document.url for document in documents] == [
        "https://example.test/legal/enterprise-terms"
    ]
    assert documents[0].source_type == "contractual"
    assert len(documents[0].sha256) == 64


def test_evidence_keeps_one_structured_document_per_url():
    def search(**kwargs):
        return {"results": [
            {"url": "https://example.test/legal/terms", "title": "Terms", "content": "snippet"},
            {"url": "https://example.test/docs/security", "title": "Security", "content": "snippet"},
        ]}

    evidence = collect_evidence_from_tavily(CONFIG, search)
    documents = evidence.documents_by_family["entrainement_reutilisation"]

    assert len(documents) == 2
    assert documents[0].url != documents[1].url
    assert all(document.content == "snippet" for document in documents)
