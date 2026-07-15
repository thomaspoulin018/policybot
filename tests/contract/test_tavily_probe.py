from datetime import date

from policybot.contract.evidence import ContractEvidence
from policybot.contract.fetcher import FetchedTerms
from policybot.contract import tavily_probe


def test_probe_requires_tavily_evidence(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tavily_probe, "search_contract_terms_with_tavily", lambda *a, **k: None,
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    assert code == 2
    assert "Aucune evidence Tavily" in capsys.readouterr().err


def test_probe_reports_evidence_per_family(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        tavily_probe,
        "search_contract_terms_with_tavily",
        lambda *a, **k: ContractEvidence.from_single(FetchedTerms(
            text="Evidence from Tavily Extract",
            source_url="https://example.test/terms",
            fetched_at=date(2026, 7, 14),
        )),
    )

    code = tavily_probe.main(["ChatGPT", "--config-dir", str(tmp_path)])

    out = capsys.readouterr().out
    assert code == 0
    assert "https://example.test/terms" in out
    assert "entrainement_reutilisation" in out
    assert "Evidence from Tavily Extract" in out
