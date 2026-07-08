from policybot.preapproved.known_tools import load_known_tools


def test_load_known_tools_returns_default_list():
    tools = load_known_tools()
    assert "ChatGPT" in tools
    assert "Claude.ai" in tools
    assert len(tools) >= 5


def test_load_known_tools_reads_custom_path(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text("- Outil A\n- Outil B\n", encoding="utf-8")
    assert load_known_tools(str(custom)) == ["Outil A", "Outil B"]
