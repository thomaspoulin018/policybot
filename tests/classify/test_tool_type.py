from policybot.classify.tool_type import classify_tool_type, tool_type_question
from policybot.classify.tool_registry import lookup_tool


def test_known_public_tool():
    assert classify_tool_type("ChatGPT") == "publique"
    assert classify_tool_type("claude.ai") == "publique"


def test_known_closed_circuit_tool():
    assert classify_tool_type("Microsoft Copilot Entreprise") == "circuit_ferme"


def test_unknown_tool_returns_none():
    assert classify_tool_type("OutilInconnu 9000") is None


def test_lookup_returns_terms_url():
    entry = lookup_tool("ChatGPT")
    assert entry["terms_url"].startswith("http")


def test_question_has_four_iag_options():
    q = tool_type_question()
    assert len(q.options) == 4
    assert q.multi_select is False
