from policybot.contract import tavily_probe


def test_probe_requires_tavily_evidence(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tavily_probe,
        "search_contract_terms_with_tavily",
        lambda tool_name, config_dir: None,
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    assert code == 2
    assert "Aucune evidence Tavily" in capsys.readouterr().err


def test_probe_outputs_evidence_preview(monkeypatch, tmp_path, capsys):
    from datetime import date
    from policybot.contract.fetcher import FetchedTerms

    monkeypatch.setattr(
        tavily_probe,
        "search_contract_terms_with_tavily",
        lambda tool_name, config_dir: FetchedTerms(
            text="Evidence from Tavily Extract",
            source_url="https://example.test/terms",
            fetched_at=date(2026, 7, 9),
        ),
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    assert code == 0
    out = capsys.readouterr().out
    assert "evidence_preview" in out
    assert "Evidence from Tavily Extract" in out
