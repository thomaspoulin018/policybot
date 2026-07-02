import os
from policybot.contract.fetcher import fetch_terms, html_to_text

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "openai_terms.html")


def _fake_get(url):
    with open(FIX, encoding="utf-8") as fh:
        return fh.read()


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
