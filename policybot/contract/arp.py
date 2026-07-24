"""Assemblage direct des constats recherchés vers les lignes du rapport."""
from __future__ import annotations

from datetime import date

from policybot.contract.criteres import SEARCH_DEFAULTS
from policybot.models import (
    ArpRecord,
    ContractOfferingIdentity,
    CriterionFinding,
    IagType,
    RiskFactor,
)


CURRENT_ARP_SCHEMA_VERSION = 2
NO_EVIDENCE = "Aucune source probante trouvée."


def finding_observation(finding: CriterionFinding) -> str:
    if finding.outcome != "ok" or not finding.answer:
        suffix = (
            f" ({finding.rejected_citations} citation(s) rejetée(s) car non ancrée(s).)"
            if finding.rejected_citations else ""
        )
        return NO_EVIDENCE + suffix
    citations = "\n".join(
        SEARCH_DEFAULTS.citation_line_template.format(
            source_type=item.source_type,
            text=item.text,
            deep_link=item.deep_link or item.url,
        )
        for item in finding.citations
    ) or NO_EVIDENCE
    return SEARCH_DEFAULTS.observation_template.format(
        answer=finding.answer,
        inherent_risk=finding.inherent_risk or "Non déterminé",
        justification=finding.justification,
        citations=citations,
    ).strip()


def finding_to_risk_factor(finding: CriterionFinding) -> RiskFactor:
    return RiskFactor(
        category=finding.category,
        criterion=finding.criterion,
        inherent=finding.inherent_risk,
        observations=finding_observation(finding),
        origin="llm_proposed",
        proposed=True,
    )


def build_arp(
    tool_name: str,
    iag_type: IagType,
    findings: list[CriterionFinding],
    offering: ContractOfferingIdentity | None = None,
) -> ArpRecord:
    return ArpRecord(
        tool_name=tool_name,
        iag_type=iag_type,
        offering=offering,
        findings=findings,
        total_cost_dollars=round(sum(item.cost_dollars for item in findings), 8),
        schema_version=CURRENT_ARP_SCHEMA_VERSION,
        fetched_at=date.today(),
    )
