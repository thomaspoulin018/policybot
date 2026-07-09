from __future__ import annotations
from datetime import date
from typing import Literal, Optional
from pydantic import BaseModel, Field

IagType = Literal["publique", "circuit_ferme", "souveraine", "gouvernementale"]
DataClass = Literal["Non classifié", "Protégé A", "Protégé B", "Protégé C"]
MatrixResult = Literal["PERMIS", "INTERDIT", "OBLIGATOIRE"]
RiskLetter = Literal["F", "M", "E", "C"]
RiskLevel = Literal["Faible", "Modéré", "Élevé", "Critique"]
Recommendation = Literal[
    "Autoriser", "Autoriser_avec_conditions", "Refuser", "Escalader"
]


class QuestionOption(BaseModel):
    label: str
    description: str = ""


class QuestionSpec(BaseModel):
    id: str
    header: str
    question: str
    options: list[QuestionOption] = Field(default_factory=list)
    multi_select: bool = False
    allow_other: bool = True


class ContractFacts(BaseModel):
    trains_on_input: Literal["yes", "no", "opt_out_available", "unknown"] = "unknown"
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = "unknown"
    data_residency: Literal["canada", "us", "eu", "other", "unknown"] = "unknown"
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = "unknown"
    human_review: Literal["yes", "no", "unknown"] = "unknown"
    encryption_standard: Literal["strong", "partial", "none", "unknown"] = "unknown"
    ip_ownership: Literal["customer", "vendor", "unclear", "unknown"] = "unknown"
    applicable_law: Literal["quebec_canada", "foreign", "unknown"] = "unknown"
    foreign_vendor_dependency: Literal["yes", "no", "unknown"] = "unknown"
    contract_prohibits_reuse: Literal["yes", "no", "unknown"] = "unknown"
    reentraining_opt_out: Literal["yes", "no", "unknown"] = "unknown"
    source_url: Optional[str] = None
    fetched_at: Optional[date] = None
    snapshot_ref: Optional[str] = None
    extraction_confidence: float = 0.0


class RiskFactor(BaseModel):
    category: str
    criterion: str
    inherent: RiskLetter
    mitigation: str = ""
    residual: RiskLetter
    responsable: str = ""
    observations: str = ""
    origin: Literal["rule", "llm_proposed"]
    proposed: bool = True


class ArpRecord(BaseModel):
    tool_name: str
    iag_type: IagType
    contract_facts: ContractFacts
    criteria: list[RiskFactor] = Field(default_factory=list)
    terms_snapshot: Optional[str] = None
    fetched_at: Optional[date] = None
    expires_at: Optional[date] = None
    approved_by: Optional[str] = None


class PreApprovedRecord(BaseModel):
    id: str
    tool_name: str
    data_classification: DataClass
    iag_type: IagType
    verdict: Recommendation
    risk_level: RiskLevel
    conditions: list[str] = Field(default_factory=list)
    arp_ref: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[date] = None
    expires_at: Optional[date] = None


class RequestInfo(BaseModel):
    numero: str
    demandeur: str = ""
    unite: str = ""
    date: Optional[date] = None


class ToolRef(BaseModel):
    name: str
    vendor: Optional[str] = None
    iag_type: Optional[IagType] = None
    arp: Optional[ArpRecord] = None


class Usage(BaseModel):
    description: str = ""
    tool_ref: str = ""
    raw_answers: dict = Field(default_factory=dict)
    data_classification: Optional[DataClass] = None
    rens_personnels: bool = False
    efvpr_required: bool = False
    mode: list[Literal["prompt", "api"]] = Field(default_factory=list)
    result_use: list[str] = Field(default_factory=list)
    automated_decisions: bool = False
    classifier_confidence: float = 0.0
    needs_officer_confirmation: bool = False
    matrix_result: Optional[MatrixResult] = None
    partie_b: list[RiskFactor] = Field(default_factory=list)
    verdict: Optional[Recommendation] = None
    risk_level: Optional[RiskLevel] = None
    conditions: list[str] = Field(default_factory=list)


class GlobalResult(BaseModel):
    risk_level: Optional[RiskLevel] = None
    efvpr_required: bool = False
    recommendation: Optional[Recommendation] = None
    conditions: list[str] = Field(default_factory=list)
    rationale_narrative: str = ""


class InterviewState(BaseModel):
    interview_id: str
    status: Literal["in_progress", "awaiting_terms", "complete"] = "in_progress"
    request: RequestInfo
    tools: list[ToolRef] = Field(default_factory=list)
    usages: list[Usage] = Field(default_factory=list)
    result_global: GlobalResult = Field(default_factory=GlobalResult)
    audit: dict = Field(default_factory=lambda: {"question_log": [], "timestamps": {}})
