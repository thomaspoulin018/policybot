from __future__ import annotations

from datetime import date
from io import StringIO

import pytest

from policybot.contract.extraction_eval import (
    FieldResult,
    GoldenCase,
    Verdict,
    RecordingTavilyClient,
    SnapshotTavilyClient,
    collect_cases,
    discover_golden_cases,
    format_report,
    has_wrong_value,
    load_golden_case,
    main,
    score_case,
    score_field,
    validate_complete_case,
    MetricCategory,
)
from policybot.contract.evidence import ContractEvidence
from policybot.contract.families import ALL_FACT_FIELDS, FACT_FAMILIES
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.fake import FakeLLMProvider
from policybot.models import ContractFacts, FactEvidence


def _write_case(case_dir, expected: str = "training_default: unknown\n"):
    case_dir.mkdir()
    (case_dir / "evidence.txt").write_text(
        "# source: https://example.test/terms\n"
        "# fetched_at: 2026-07-15\n"
        "\n"
        "Synthetic terms evidence.\n",
        encoding="utf-8",
    )
    (case_dir / "expected.yaml").write_text(expected, encoding="utf-8")


def _synthetic_case(tool_slug: str = "tool") -> GoldenCase:
    terms = FetchedTerms(
        text="This deliberately long synthetic sentence supports every test value.",
        source_url="https://example.test/terms",
        fetched_at=date(2026, 7, 15),
    )
    return GoldenCase(
        tool_slug=tool_slug,
        evidence=ContractEvidence.from_single(terms),
        expected={field.name: "unknown" for field in ALL_FACT_FIELDS},
    )


def _unknown_family_responses() -> list[dict]:
    return [
        {
            field.name: {
                "value": "unknown",
                "source_url": None,
                "quote": None,
                "confidence": 0.0,
            }
            for field in family.fields
        }
        for family in FACT_FAMILIES
    ]


def test_load_golden_case_builds_single_page_evidence(tmp_path):
    case_dir = tmp_path / "example_tool"
    _write_case(
        case_dir,
        "training_default: no\n"
        "data_retention: limited\n"
        "ip_ownership: customer\n",
    )

    case = load_golden_case(case_dir)

    assert case.tool_slug == "example_tool"
    assert case.expected == {
        "training_default": "no",
        "data_retention": "limited",
        "ip_ownership": "customer",
    }
    assert set(case.evidence.by_family) == {family.name for family in FACT_FAMILIES}
    document = case.evidence.documents_by_family[FACT_FAMILIES[0].name][0]
    assert document.url == "https://example.test/terms"
    assert document.collected_at == date(2026, 7, 15)
    assert document.content == "Synthetic terms evidence."


def test_load_golden_case_rejects_unknown_field(tmp_path):
    case_dir = tmp_path / "typo"
    _write_case(case_dir, "training_defaults: no\n")

    with pytest.raises(ValueError, match="Unknown ContractFacts field"):
        load_golden_case(case_dir)


def test_discover_golden_cases_is_sorted_and_ignores_files(tmp_path):
    _write_case(tmp_path / "z_tool")
    _write_case(tmp_path / "a_tool")
    (tmp_path / "README.md").write_text("not a case", encoding="utf-8")

    cases = discover_golden_cases(tmp_path)

    assert [case.tool_slug for case in cases] == ["a_tool", "z_tool"]


class _TinyTavilyClient:
    def search(self, *, query, **kwargs):
        return {
            "results": [
                {"url": "https://openai.com/policies/terms-of-use", "content": f"hit for {query}"}
            ]
        }

    def extract(self, urls, **kwargs):
        return {
            "results": [
                {
                    "url": urls[0],
                    "raw_content": "Stable extracted contract evidence.",
                }
            ]
        }


def test_live_snapshot_round_trip_replays_raw_tavily_without_network(tmp_path):
    case = _synthetic_case("chatgpt")

    live = collect_cases(
        [case], source="live", run_dir=tmp_path, tavily_client=_TinyTavilyClient()
    )
    replay = collect_cases([case], source="snapshot", run_dir=tmp_path)

    assert replay[0].evidence.by_family == live[0].evidence.by_family
    snapshot = tmp_path / "snapshots" / "chatgpt.json"
    payload = __import__("json").loads(snapshot.read_text(encoding="utf-8"))
    assert len(payload["calls"]["search"]) == len(FACT_FAMILIES)
    assert len(payload["calls"]["extract"]) == 1


def test_snapshot_replay_rejects_changed_query():
    client = SnapshotTavilyClient(
        {
            "calls": {
                "search": [{"query": "old", "kwargs": {}, "response": {}}],
                "extract": [],
            }
        }
    )

    with pytest.raises(ValueError, match="incompatible"):
        client.search(query="new")


@pytest.mark.parametrize(
    ("expected", "got", "verdict"),
    [
        ("unknown", "unknown", Verdict.MATCH),
        ("yes", "yes", Verdict.MATCH),
        ("yes", "no", Verdict.WRONG_VALUE),
        ("unknown", "yes", Verdict.WRONG_VALUE),
        ("yes", "unknown", Verdict.WRONG_ABSTAIN),
    ],
)
def test_score_field(expected, got, verdict):
    assert score_field(expected, FactEvidence(value=got)) is verdict


def test_score_case_uses_contract_fact_evidence():
    case = _synthetic_case()
    case.expected.clear()
    case.expected.update({"training_default": "no", "data_retention": "limited"})
    facts = ContractFacts(
        training_default="no",
        data_retention="unknown",
        evidence={
            "training_default": FactEvidence(value="no"),
            "data_retention": FactEvidence(value="unknown"),
        },
    )

    assert score_case(case, facts) == [
        FieldResult("training_default", "no", "no", Verdict.MATCH),
        FieldResult(
            "data_retention", "limited", "unknown", Verdict.WRONG_ABSTAIN,
            (MetricCategory.MODEL_ABSTENTION,),
        ),
    ]


def test_format_report_and_wrong_value_gate():
    results = {
        "chatgpt": [
            FieldResult("training_default", "no", "no", Verdict.MATCH),
            FieldResult("data_retention", "limited", "none", Verdict.WRONG_VALUE),
        ],
        "claude_ai": [
            FieldResult(
                "ip_ownership", "customer", "unknown", Verdict.WRONG_ABSTAIN
            )
        ],
    }

    report = format_report(results)

    assert "## chatgpt" in report
    assert "## claude_ai" in report
    assert "data_retention | limited | none | WRONG_VALUE" in report
    assert "**Taux WRONG_VALUE: 33.3%**" in report
    assert has_wrong_value(results) is True
    assert has_wrong_value({"tool": results["claude_ai"]}) is False


def test_metrics_separate_pipeline_failures_and_false_reassurance():
    case = _synthetic_case()
    case.expected.clear()
    case.expected.update({
        "data_residency": "unknown",
        "sub_processors": "undisclosed",
        "provider_human_access": "yes",
        "encryption_standard": "strong",
        "ip_ownership": "customer",
    })
    facts = ContractFacts(evidence={
        "data_residency": FactEvidence(
            value="unknown", outcome="collection_failure",
        ),
        "sub_processors": FactEvidence(
            value="unknown", outcome="evidence_missing",
        ),
        "provider_human_access": FactEvidence(
            value="unknown", outcome="llm_failure",
        ),
        "encryption_standard": FactEvidence(
            value="unknown", outcome="model_abstention",
        ),
        "ip_ownership": FactEvidence(
            value="vendor", outcome="accepted",
        ),
    })

    results = score_case(case, facts)
    categories = {result.field: set(result.metrics) for result in results}

    assert MetricCategory.COLLECTION_FAILURE in categories["data_residency"]
    assert MetricCategory.FACT_ABSENT in categories["sub_processors"]
    assert MetricCategory.LLM_FAILURE in categories["provider_human_access"]
    assert MetricCategory.MODEL_ABSTENTION in categories["encryption_standard"]
    assert MetricCategory.INCORRECT_VALUE in categories["ip_ownership"]


def test_false_reassuring_is_reported_in_addition_to_incorrect_value():
    case = _synthetic_case()
    case.expected.clear()
    case.expected["sub_processors"] = "undisclosed"
    facts = ContractFacts(
        sub_processors="disclosed",
        evidence={"sub_processors": FactEvidence(value="disclosed", outcome="accepted")},
    )

    result = score_case(case, facts)[0]

    assert result.verdict is Verdict.WRONG_VALUE
    assert result.metrics == (
        MetricCategory.INCORRECT_VALUE,
        MetricCategory.FALSE_REASSURING,
    )


def test_validate_complete_case_checks_coverage_and_allowed_values():
    case = _synthetic_case()
    validate_complete_case(case)

    incomplete = _synthetic_case("incomplete")
    incomplete.expected.pop("provider_human_access")
    with pytest.raises(ValueError, match="missing"):
        validate_complete_case(incomplete)

    invalid = _synthetic_case("invalid")
    invalid.expected["training_default"] = "sometimes"
    with pytest.raises(ValueError, match="Invalid expected value"):
        validate_complete_case(invalid)


def test_main_returns_zero_when_only_matches_and_abstains():
    case = _synthetic_case()
    case.expected["training_default"] = "yes"
    llm = FakeLLMProvider(json_responses=_unknown_family_responses())
    output = StringIO()

    exit_code = main(llm, [case], output=output)

    assert exit_code == 0
    assert "WRONG_ABSTAIN: 1" in output.getvalue()


def test_main_returns_one_for_wrong_value():
    case = _synthetic_case()
    responses = _unknown_family_responses()
    responses[0]["training_default"] = {
        "value": "yes",
        "source_url": "https://example.test/terms",
        "quote": "This deliberately long synthetic sentence supports every test value.",
        "confidence": 1.0,
    }
    llm = FakeLLMProvider(json_responses=responses)

    exit_code = main(llm, [case], output=StringIO())

    assert exit_code == 1


@pytest.mark.parametrize(
    "case",
    discover_golden_cases(),
    ids=lambda case: case.tool_slug,
)
def test_real_golden_expected_is_well_formed(case):
    validate_complete_case(case)
