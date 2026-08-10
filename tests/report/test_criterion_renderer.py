from io import BytesIO

from docx import Document

from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA
from policybot.models import (
    ArpRecord, CriterionCitation, CriterionFinding, InterviewState,
    RequestInfo, ToolRef,
)
from policybot.report.renderer import render_docx, render_pdf


def _state():
    category, criterion, question = ARP_CRITERIA[0]
    finding = CriterionFinding(
        id="A01", partie="A", category=category, criterion=criterion,
        question=question, answer="Réponse vérifiée.", inherent_risk="M",
        justification="Justification.", cost_dollars=0.02,
        citations=[CriterionCitation(
            url="https://vendor.test/page", text="Citation exacte",
            anchored=True,
            deep_link="https://vendor.test/page#:~:text=Citation%20exacte",
        )],
    )
    return InterviewState(
        interview_id="i", status="complete", request=RequestInfo(numero="REQ-1"),
        tools=[ToolRef(name="ToolX", iag_type="publique", arp=ArpRecord(
            tool_name="ToolX", iag_type="publique", findings=[finding],
            total_cost_dollars=0.02,
        ))],
    )


def test_pdf_and_docx_exports_use_historical_output_formats():
    assert render_pdf(_state()).startswith(b"%PDF")
    docx = render_docx(_state())
    assert docx.startswith(b"PK")
    document = Document(BytesIO(docx))
    assert len(document.tables) == 8
    assert [len(table.rows) for table in document.tables] == [7, 8, 21, 5, 6, 5, 5, 5]
    assert document.tables[0].cell(0, 1).text == "REQ-1"
    assert document.tables[1].cell(0, 1).text == "ToolX"
    # La recommandation demeure réservée à l'autorité désignée.
    assert document.tables[7].cell(3, 1).text == ""
