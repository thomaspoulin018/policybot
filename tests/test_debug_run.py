from __future__ import annotations

from policybot.contract.evidence import ContractEvidence, EvidenceDocument
from policybot.debug_run import LLMCallRecord, debug_run, record_contract_search, record_llm_call
from policybot.interview.orchestrator import Interview
from policybot.llm.debug_provider import DebugRecordingProvider
from policybot.llm.fake import FakeLLMProvider
from policybot.models import FactEvidence, RequestInfo
from policybot.preapproved.store import PreApprovedStore


def _evidence() -> ContractEvidence:
    document = EvidenceDocument(
        url="https://vendor.test/terms",
        title="Institutional terms",
        content="The provider does not train on institutional input by default.",
        source_type="contractual",
    )
    return ContractEvidence(
        documents_by_fact={"training_default": [document]},
        facts={"training_default": FactEvidence(
            value="no",
            source_url=document.url,
            quote="does not train on institutional input by default",
            outcome="accepted",
        )},
        failed_facts=("data_residency",),
    )


def test_debug_run_is_a_no_op_until_explicitly_enabled(tmp_path):
    output_dir = tmp_path / "runs"

    with debug_run("abc12345-0000", "ChatGPT", output_dir=output_dir):
        record_llm_call(LLMCallRecord(
            method="json", run_name="classify", tags=(), task=None,
            system="system prompt", user="user prompt", response="{}",
        ))

    assert not output_dir.exists()


def test_debug_run_writes_valid_fenced_markdown(tmp_path):
    output_dir = tmp_path / "runs"

    with debug_run("abc12345-0000", "ChatGPT", enabled=True, output_dir=output_dir):
        record_llm_call(LLMCallRecord(
            method="json", run_name="classify_data", tags=("classification",),
            task="data_classification", system="classify this description",
            user="employee notes", response='{"sensitive": true}',
        ))
        record_contract_search("ChatGPT", "exa", _evidence())

    content = next(output_dir.glob("*_abc12345/run.md")).read_text(encoding="utf-8")
    fence = "`" * 3
    assert fence + "json" + "\n{" in content
    assert fence + "\\n" not in content
    assert "https://vendor.test/terms" in content
    assert "does not train on institutional input by default" in content


def test_embedded_fence_uses_a_longer_markdown_delimiter(tmp_path):
    output_dir = tmp_path / "runs"
    embedded = "Example: " + ("`" * 3) + "code" + ("`" * 3)

    with debug_run("abc12345-0000", "ChatGPT", enabled=True, output_dir=output_dir):
        record_llm_call(LLMCallRecord(
            method="text", run_name=None, tags=(), task=None,
            system="system", user=embedded, response="answer",
        ))

    content = next(output_dir.glob("*_abc12345/run.md")).read_text(encoding="utf-8")
    assert ("`" * 4) + "\n" + embedded + "\n" + ("`" * 4) in content


def test_assessment_writes_llm_and_exa_diagnostics_end_to_end(tmp_path):
    output_dir = tmp_path / "runs"
    interview = Interview(
        llm=DebugRecordingProvider(FakeLLMProvider(json_responses=[{
            "already_public": True,
            "contains_personal_info": False,
            "strategic_sensitive": False,
            "internal_nonpublic": False,
            "highly_sensitive_secret": False,
            "confidence": 0.9,
        }])),
        store=PreApprovedStore(str(tmp_path / "policybot.db")),
        exa_search=lambda tool_name, offering: _evidence(),
        arp_cache_mode="disabled",
        debug_runs_enabled=True,
        debug_runs_output_dir=output_dir,
    )

    state = interview.assess(
        RequestInfo(numero="DEBUG-001"),
        "ChatGPT",
        [{
            "description": "summarize public content",
            "data_description": "already public information",
            "automated_decisions": False,
            "mode": ["prompt"],
            "result_use": [],
        }],
        tool_version_plan_tarifaire="Enterprise",
        contract_version="DPA-2026",
    )

    content = next(output_dir.glob(f"*_{state.interview_id[:8]}/run.md")).read_text(
        encoding="utf-8",
    )
    assert "already public information" in content
    assert "Recherche de contrat" in content
    assert "https://vendor.test/terms" in content
