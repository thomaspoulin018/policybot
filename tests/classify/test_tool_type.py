from policybot.classify.tool_registry import classify_tool_type, lookup_tool


def test_known_public_tool():
    assert classify_tool_type("ChatGPT") == "publique"
    assert classify_tool_type("claude.ai") == "publique"


def test_known_closed_circuit_tool():
    assert classify_tool_type("Microsoft Copilot Entreprise") == "circuit_ferme"


def test_unknown_tool_returns_none():
    assert classify_tool_type("OutilInconnu 9000") is None


def test_registry_only_carries_what_the_pipeline_reads():
    """`terms_url` et `contract_sources` n'avaient aucun lecteur : les garder
    revenait à entretenir des listes d'adresses que rien ne vérifiait."""
    assert lookup_tool("ChatGPT") == {"iag_type": "publique", "vendor": "OpenAI"}
