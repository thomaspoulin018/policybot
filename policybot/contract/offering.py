"""Construction et affichage de l'identité d'une offre contractuelle."""
from __future__ import annotations

from datetime import date

from policybot.classify.tool_registry import lookup_tool
from policybot.models import ContractOfferingIdentity, IagType


_DEPLOYMENT_BY_IAG_TYPE = {
    "publique": "public_saas",
    "circuit_ferme": "managed_saas",
    "souveraine": "sovereign_hosted",
    "gouvernementale": "government_hosted",
}

_CONTRACT_BY_IAG_TYPE = {
    "publique": "consumer_terms",
    "circuit_ferme": "institutional_agreement",
    "souveraine": "institutional_agreement",
    "gouvernementale": "government_agreement",
}


def build_offering_identity(
    tool_name: str,
    iag_type: IagType,
    *,
    vendor: str | None = None,
    plan: str | None = None,
    deployment_mode: str | None = None,
    contract_type: str | None = None,
    contract_version: str | None = None,
    jurisdiction: str | None = None,
    effective_date: date | None = None,
) -> ContractOfferingIdentity:
    entry = lookup_tool(tool_name) or {}
    normalized_plan = (plan or "").strip()
    plan_is_managed = any(marker in normalized_plan.casefold() for marker in (
        "enterprise", "entreprise", "education", "éducation", "edu", "team",
        "institution",
    ))
    resolved_deployment = deployment_mode
    resolved_contract = contract_type
    if plan_is_managed:
        resolved_deployment = resolved_deployment or "managed_saas"
        resolved_contract = resolved_contract or "institutional_agreement"
    return ContractOfferingIdentity(
        # Do not turn the product name into a presumed vendor: a contract
        # search must abstain when the assessed offering cannot be identified.
        vendor=(vendor or entry.get("vendor") or "").strip(),
        product=tool_name.strip(),
        plan=normalized_plan,
        deployment_mode=(resolved_deployment or _DEPLOYMENT_BY_IAG_TYPE[iag_type]).strip(),
        contract_type=(resolved_contract or _CONTRACT_BY_IAG_TYPE[iag_type]).strip(),
        contract_version=(contract_version or "").strip(),
        jurisdiction=(jurisdiction or "").strip(),
        effective_date=effective_date,
    )
