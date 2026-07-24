from io import BytesIO

from bs4 import BeautifulSoup
from docx import Document

from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA
from policybot.models import (
    ArpRecord, CriterionCitation, CriterionFinding, InterviewState,
    RequestInfo, ToolRef,
)
from policybot.report.renderer import render_docx, render_html, render_pdf


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


def test_html_renders_full_historical_grid_part_c_and_cost():
    html = render_html(_state())
    assert "Risque inhérent" in html
    assert "Citation exacte" in html
    assert "0.0200" in html
    assert "Partie C" in html
    assert "Aucun résultat n'est calculé automatiquement" in html
    assert all(criterion in html for _, criterion, _ in USAGE_CRITERIA)
    soup = BeautifulSoup(html, "html.parser")
    empty_criterion = "Formation insuffisante du personnel"
    criterion_cell = next(
        cell for cell in soup.find_all("td")
        if cell.get_text(" ", strip=True) == empty_criterion
    )
    cells = criterion_cell.parent.find_all("td")
    assert cells[2].get_text(strip=True) == ""
    assert cells[3].get_text(strip=True) == ""
    assert cells[4].get_text(strip=True) == ""
    assert cells[5].get_text(strip=True) == ""
    assert cells[6].get_text(strip=True) == ""


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
