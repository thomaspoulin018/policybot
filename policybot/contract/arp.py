from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from policybot.models import ContractFacts, ArpRecord, RiskFactor, IagType
from policybot.contract.fetcher import FetchedTerms
from policybot.llm.provider import LLMProvider
from policybot.criteria import ARP_CRITERIA

CURRENT_ARP_SCHEMA_VERSION = 2


class ContractFactsExtraction(BaseModel):
    trains_on_input: Literal["yes", "no", "opt_out_available", "unknown"] = Field(
        "unknown",
        description="Whether submitted inputs may be used to train the model.",
    )
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = Field(
        "unknown",
        description="How long the vendor retains submitted data.",
    )
    data_residency: Literal["canada", "us", "eu", "other", "unknown"] = Field(
        "unknown",
        description="Where submitted data is hosted or processed.",
    )
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = Field(
        "unknown",
        description="Whether subprocessors are disclosed contractually.",
    )
    human_review: Literal["yes", "no", "unknown"] = Field(
        "unknown",
        description="Whether the vendor may manually review submitted data.",
    )
    encryption_standard: Literal["strong", "partial", "none", "unknown"] = Field(
        "unknown",
        description=(
            "strong means encryption in transit and at rest are both explicit; "
            "partial means only one is explicit or the statement is incomplete."
        ),
    )
    ip_ownership: Literal["customer", "vendor", "unclear", "unknown"] = Field(
        "unknown",
        description="Who owns generated content or submitted content rights.",
    )
    applicable_law: Literal["quebec_canada", "foreign", "unknown"] = Field(
        "unknown",
        description="Whether the contract is governed by Quebec/Canadian law or foreign law.",
    )
    foreign_vendor_dependency: Literal["yes", "no", "unknown"] = Field(
        "unknown",
        description="Whether using the tool creates dependency on a foreign vendor.",
    )
    contract_prohibits_reuse: Literal["yes", "no", "unknown"] = Field(
        "unknown",
        description="Whether the contract explicitly prohibits reuse of submitted data.",
    )
    reentraining_opt_out: Literal["yes", "no", "unknown"] = Field(
        "unknown",
        description=(
            "Whether there is a mechanism to prevent model retraining from submitted "
            "and generated data."
        ),
    )
    authentication_support: Literal["sso_mfa", "partial", "none", "unknown"] = Field(
        "unknown",
        description=(
            "Whether the tool supports strong authentication such as SSO/MFA and "
            "institutional identity-provider integration."
        ),
    )
    audit_logging: Literal[
        "prompt_output_accessible", "access_logs_only", "none", "unknown"
    ] = Field(
        "unknown",
        description=(
            "Whether access logs and prompt/output audit logs are generated and "
            "available to the organization."
        ),
    )
    institutional_terms: Literal["acceptable", "problematic", "unknown"] = Field(
        "unknown",
        description=(
            "Whether public terms appear acceptable for institutional use or contain "
            "problematic clauses."
        ),
    )
    quebec_higher_ed_license: Literal["yes", "no", "unknown"] = Field(
        "unknown",
        description=(
            "Whether the license appears to allow use by a Quebec higher-education "
            "institution."
        ),
    )
    incident_response: Literal[
        "documented_with_notice", "documented_no_notice", "none", "unknown"
    ] = Field(
        "unknown",
        description=(
            "Whether the vendor documents an incident response plan and breach "
            "notification commitment."
        ),
    )
    extraction_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the normalized extraction from 0 to 1.",
    )


_SYSTEM = (
    "You extract normalized contract facts for an AI tool. Return only one JSON "
    "object. Use only the allowed values listed in the prompt. Answer unknown "
    "when the evidence does not allow a conclusion. Do not infer guarantees "
    "that are not written in the evidence."
)

_FIELD_INSTRUCTIONS = """
Required JSON keys and allowed values:
- trains_on_input: yes | no | opt_out_available | unknown
- data_retention: none | limited | indefinite | unknown
- data_residency: canada | us | eu | other | unknown
- sub_processors: disclosed | undisclosed | unknown
- human_review: yes | no | unknown
- encryption_standard: strong | partial | none | unknown
- ip_ownership: customer | vendor | unclear | unknown
- applicable_law: quebec_canada | foreign | unknown
- foreign_vendor_dependency: yes | no | unknown
- contract_prohibits_reuse: yes | no | unknown
- reentraining_opt_out: yes | no | unknown
- authentication_support: sso_mfa | partial | none | unknown
- audit_logging: prompt_output_accessible | access_logs_only | none | unknown
- institutional_terms: acceptable | problematic | unknown
- quebec_higher_ed_license: yes | no | unknown
- incident_response: documented_with_notice | documented_no_notice | none | unknown
- extraction_confidence: number from 0 to 1
- Do not return an empty object. Include every required key even when unknown.

Normalization hints:
- trains_on_input=opt_out_available when submitted content may be used for
  training by default but an opt-out control is explicitly available.
- data_retention=limited when retention exists but is bounded or reducible;
  indefinite only when no deletion/expiry limit is indicated.
- encryption_standard=strong only when both encryption in transit and at rest
  are explicit.
- applicable_law=foreign when the governing law is outside Quebec/Canada.
- authentication_support=sso_mfa only when SSO or SAML/OIDC and MFA support are explicit; partial when only one is explicit.
- audit_logging=prompt_output_accessible only when prompt/output auditability is explicit and organization-accessible; access_logs_only when only sign-in/admin logs are explicit.
- institutional_terms=problematic when evidence shows a clause that blocks or materially restricts institutional use; otherwise use unknown unless acceptability is explicit.
- quebec_higher_ed_license=yes only when education, enterprise, public-sector, or institutional use is explicitly allowed.
- incident_response=documented_with_notice only when both an incident response process and breach/security notification timing are documented.
""".strip()

_MAX_EVIDENCE_CHARS = 12000
_SOURCE_SEPARATOR = "\n\n---\n\n"
_KEYWORD_PATTERNS = (
    r"train(?:ing)?|model performance|opt[ -]?out|do not train",
    r"data retention|retention|retain|deleted?.{0,80}30 days|within 30 days",
    r"servers located|various jurisdictions|United States|residen|region|hosting",
    r"sub[- ]?processors?|service providers?|vendors?",
    r"human review|manual review|abuse monitoring|safety review|authorized personnel",
    r"encrypt|encryption|tls|aes",
    r"ownership|intellectual property|assign|right, title",
    r"governing law|California law|jurisdiction",
    r"confidential|reuse|disclosure|data sharing",
    r"sso|single sign-on|saml|oidc|mfa|multi-factor|identity provider",
    r"audit logs?|access logs?|prompt logs?|output logs?|admin console|organization logs?",
    r"institutional use|enterprise terms|education|higher education|public sector|acceptable use",
    r"license|licence|government|public sector|education institution|academic",
    r"incident response|security incident|breach notification|notify.{0,80}(hours|days)|sla",
)


def _select_evidence_text(text: str, max_chars: int = _MAX_EVIDENCE_CHARS) -> str:
    if len(text) <= max_chars:
        return text

    excerpts: list[str] = []
    seen: set[str] = set()
    used = 0

    def add_excerpt(excerpt: str, limit: int = max_chars) -> None:
        nonlocal used
        excerpt = excerpt.strip()
        if not excerpt or excerpt in seen or used >= limit:
            return
        remaining = limit - used
        if len(excerpt) > remaining:
            excerpt = excerpt[:remaining].rstrip()
        excerpts.append(excerpt)
        seen.add(excerpt)
        used += len(excerpt) + 7

    heading_budget = max_chars // 10
    for source in text.split(_SOURCE_SEPARATOR):
        if used >= heading_budget:
            break
        add_excerpt(source[:350], heading_budget)

    for pattern in _KEYWORD_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            start = max(0, match.start() - 250)
            end = min(len(text), match.end() + 500)
            add_excerpt(text[start:end])
            break
        if used >= max_chars:
            break

    return "\n\n...\n\n".join(excerpts) if excerpts else text[:max_chars]


def _build_extraction_prompt(text: str) -> str:
    return (
        f"{_FIELD_INSTRUCTIONS}\n\n"
        "Evidence:\n"
        f"{_select_evidence_text(text)}"
    )


def _require_non_empty_extraction(extracted: ContractFactsExtraction) -> None:
    populated = set(extracted.model_fields_set)
    populated.discard("extraction_confidence")
    if not populated:
        raise ValueError(
            "LLM returned no contract fact fields. Check the model/output; an "
            "empty JSON object would otherwise be accepted as all unknown."
        )


def extract_contract_facts(terms: FetchedTerms, llm: LLMProvider) -> ContractFacts:
    extracted = llm.complete_structured(
        _SYSTEM,
        _build_extraction_prompt(terms.text),
        ContractFactsExtraction,
        run_name="extract_contract_facts",
        tags=["arp_extraction"],
    )
    _require_non_empty_extraction(extracted)
    return ContractFacts(
        **extracted.model_dump(),
        source_url=terms.source_url,
        fetched_at=terms.fetched_at,
    )


def build_arp(tool_name: str, iag_type: IagType, facts: ContractFacts) -> ArpRecord:
    """Produce the 8 Partie A criteria PolicyBot can derive automatically."""
    criteria: list[RiskFactor] = []

    residency_risk = "F" if facts.data_residency == "canada" else "M"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Localisation des serveurs",
        inherent=residency_risk, residual=residency_risk, origin="rule",
        observations=f"data_residency={facts.data_residency}",
    ))

    law_risk = "F" if facts.applicable_law == "quebec_canada" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Juridiction applicable",
        inherent=law_risk, residual=law_risk, origin="rule",
        observations=f"applicable_law={facts.applicable_law}",
    ))

    dependency_risk = "F" if facts.foreign_vendor_dependency == "no" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données", criterion="Dépendance technologique",
        inherent=dependency_risk, residual=dependency_risk, origin="rule",
        observations=f"foreign_vendor_dependency={facts.foreign_vendor_dependency}",
    ))

    training_risk = "E" if facts.trains_on_input in ("yes", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Données soumises utilisées pour entraînement du modèle",
        inherent=training_risk, residual=training_risk, origin="rule",
        observations=f"trains_on_input={facts.trains_on_input}",
    ))

    reuse_risk = "F" if facts.contract_prohibits_reuse == "yes" else "E"
    criteria.append(RiskFactor(
        category="Souveraineté et hébergement des données",
        criterion="Garanties contractuelles de non-divulgation",
        inherent=reuse_risk, residual=reuse_risk, origin="rule",
        observations=f"contract_prohibits_reuse={facts.contract_prohibits_reuse}",
    ))

    encryption_risk = "E" if facts.encryption_standard in ("none", "partial", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Chiffrement des données",
        inherent=encryption_risk, residual=encryption_risk, origin="rule",
        observations=f"encryption_standard={facts.encryption_standard}",
    ))

    opt_out_risk = "F" if facts.reentraining_opt_out == "yes" else "E"
    criteria.append(RiskFactor(
        category="Sécurité de l'information", criterion="Utilisation des entrées et des sorties",
        inherent=opt_out_risk, residual=opt_out_risk, origin="rule",
        observations=f"reentraining_opt_out={facts.reentraining_opt_out}",
    ))

    ip_risk = "E" if facts.ip_ownership in ("vendor", "unclear", "unknown") else "F"
    criteria.append(RiskFactor(
        category="Conformité légale et contractuelle", criterion="Propriété intellectuelle",
        inherent=ip_risk, residual=ip_risk, origin="rule",
        observations=f"ip_ownership={facts.ip_ownership}",
    ))

    assert {factor.criterion for factor in criteria} <= {
        name for _, name, _ in ARP_CRITERIA
    }

    return ArpRecord(
        tool_name=tool_name, iag_type=iag_type, contract_facts=facts,
        criteria=criteria, schema_version=CURRENT_ARP_SCHEMA_VERSION, terms_snapshot=facts.source_url,
        fetched_at=facts.fetched_at,
    )
