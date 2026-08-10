"""Assemblage direct des constats recherchés vers les lignes du rapport."""
from __future__ import annotations

from datetime import date

from policybot.models import (
    ArpRecord,
    ContractOfferingIdentity,
    CriterionFinding,
    IagType,
)


CURRENT_ARP_SCHEMA_VERSION = 2


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
