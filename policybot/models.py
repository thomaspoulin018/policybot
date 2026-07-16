from __future__ import annotations
from datetime import date
import hashlib
import json
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

IagType = Literal["publique", "circuit_ferme", "souveraine", "gouvernementale"]
DataClass = Literal["Non classifié", "Protégé A", "Protégé B", "Protégé C"]
MatrixResult = Literal["PERMIS", "INTERDIT", "OBLIGATOIRE"]
RiskLetter = Literal["F", "M", "E", "C"]
RiskLevel = Literal["Faible", "Modéré", "Élevé", "Critique"]
Recommendation = Literal[
    "Autoriser", "Autoriser_avec_conditions", "Refuser", "Escalader"
]

EvidenceOutcome = Literal[
    "accepted",
    "collection_failure",
    "evidence_missing",
    "llm_failure",
    "model_abstention",
    "citation_rejected",
    "invalid_value",
]


class ContractOfferingIdentity(BaseModel):
    """Identité stable de l'offre dont les garanties contractuelles s'appliquent.

    Un nom de produit ne suffit pas : les garanties de ChatGPT grand public,
    Enterprise et Edu ne sont pas interchangeables. Cette identité est donc la
    frontière de collecte, de rapport et de cache de l'ARP.
    """

    vendor: str
    product: str
    plan: str = ""
    deployment_mode: str = "unknown"
    contract_type: str = "unknown"
    contract_version: str = ""
    effective_date: Optional[date] = None

    def canonical_payload(self) -> dict[str, str]:
        return {
            "vendor": self.vendor.strip().casefold(),
            "product": self.product.strip().casefold(),
            "plan": self.plan.strip().casefold(),
            "deployment_mode": self.deployment_mode.strip().casefold(),
            "contract_type": self.contract_type.strip().casefold(),
            "contract_version": self.contract_version.strip().casefold(),
            "effective_date": self.effective_date.isoformat() if self.effective_date else "",
        }

    def cache_key(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        return f"offering:{digest}"

    def display_label(self) -> str:
        parts = [self.vendor, self.product]
        if self.plan:
            parts.append(self.plan)
        parts.extend([self.deployment_mode, self.contract_type])
        if self.contract_version:
            parts.append(self.contract_version)
        if self.effective_date:
            parts.append(self.effective_date.isoformat())
        return " — ".join(part for part in parts if part)


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


class FactEvidence(BaseModel):
    """La preuve d'un fait contractuel : sa valeur, sa source, sa citation.

    `note` explique une valeur `unknown` non concluante (collecte échouée,
    citation manquante) — c'est ce que l'officier lit dans le rapport.
    """
    value: str = "unknown"
    source_url: Optional[str] = None
    quote: Optional[str] = None
    confidence: float = 0.0
    note: Optional[str] = None
    outcome: Optional[EvidenceOutcome] = None
    source_type: Optional[str] = None
    source_effective_date: Optional[date] = None
    source_collected_at: Optional[date] = None
    source_sha256: Optional[str] = None


class ContractSource(BaseModel):
    url: str
    title: str = ""
    source_type: str
    effective_date: Optional[date] = None
    collected_at: date
    sha256: str


class ContractFacts(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_semantics(cls, data):
        """Relire les ARP antérieures sans transformer une option en garantie.

        Les caches schema v2 confondaient entraînement par défaut, disponibilité
        d'un opt-out et activation de cet opt-out. La migration est volontairement
        conservatrice : aucune ancienne valeur ne confirme une activation réelle.
        """
        if not isinstance(data, dict):
            return data
        values = dict(data)

        legacy_training = values.pop("trains_on_input", None)
        legacy_opt_out = values.pop("reentraining_opt_out", None)
        if "training_default" not in values and legacy_training is not None:
            values["training_default"] = {
                "yes": "yes", "no": "no", "opt_out_available": "yes",
                "unknown": "unknown",
            }.get(legacy_training, "unknown")
        if "opt_out_available" not in values:
            if legacy_training == "opt_out_available" or legacy_opt_out == "yes":
                values["opt_out_available"] = "yes"
            elif legacy_opt_out == "no":
                values["opt_out_available"] = "no"
        values.setdefault("opt_out_confirmed_enabled", "unknown")

        legacy_human_review = values.pop("human_review", None)
        if "provider_human_access" not in values and legacy_human_review is not None:
            values["provider_human_access"] = legacy_human_review

        legacy_terms = values.pop("institutional_terms", None)
        if legacy_terms is not None:
            values.setdefault(
                "institutional_terms_available",
                "yes" if legacy_terms in ("acceptable", "problematic") else "unknown",
            )
            values.setdefault(
                "institutional_use_restricted",
                "yes" if legacy_terms == "problematic" else (
                    "no" if legacy_terms == "acceptable" else "unknown"
                ),
            )
            values.setdefault("dpa_available", "unknown")

        legacy_residency = values.get("data_residency")
        values["data_residency"] = {
            # "canada" ne prouvait pas que l'hébergement était au Québec.
            "canada": "canada_outside_quebec",
            "us": "us",
            "eu": "eu",
            "other": "unknown",
        }.get(legacy_residency, legacy_residency or "unknown")

        # Conserver l'ancrage URL/citation des caches historiques en renommant
        # aussi leurs preuves. La valeur confirmée de l'opt-out n'est jamais
        # créée ici : l'ancienne preuve démontrait au mieux sa disponibilité.
        evidence = dict(values.get("evidence") or {})

        def copy_proof(old_name: str, new_name: str, new_value: str) -> None:
            if new_name in evidence or old_name not in evidence:
                return
            raw_proof = evidence[old_name]
            if isinstance(raw_proof, BaseModel):
                raw_proof = raw_proof.model_dump(mode="json")
            if isinstance(raw_proof, dict):
                migrated = dict(raw_proof)
                migrated["value"] = new_value
                evidence[new_name] = migrated

        copy_proof("trains_on_input", "training_default", values.get("training_default", "unknown"))
        copy_proof("reentraining_opt_out", "opt_out_available", values.get("opt_out_available", "unknown"))
        if legacy_training == "opt_out_available":
            copy_proof("trains_on_input", "opt_out_available", values.get("opt_out_available", "unknown"))
        copy_proof("human_review", "provider_human_access", values.get("provider_human_access", "unknown"))
        copy_proof("institutional_terms", "institutional_terms_available", values.get("institutional_terms_available", "unknown"))
        copy_proof("institutional_terms", "institutional_use_restricted", values.get("institutional_use_restricted", "unknown"))
        for legacy_name in (
            "trains_on_input", "reentraining_opt_out", "human_review",
            "institutional_terms",
        ):
            evidence.pop(legacy_name, None)
        if legacy_residency is not None and "data_residency" in evidence:
            raw_residency_proof = evidence["data_residency"]
            if isinstance(raw_residency_proof, BaseModel):
                raw_residency_proof = raw_residency_proof.model_dump(mode="json")
            if isinstance(raw_residency_proof, dict):
                migrated = dict(raw_residency_proof)
                migrated["value"] = values["data_residency"]
                evidence["data_residency"] = migrated
        values["evidence"] = evidence
        return values

    training_default: Literal["yes", "no", "unknown"] = "unknown"
    opt_out_available: Literal["yes", "no", "unknown"] = "unknown"
    opt_out_confirmed_enabled: Literal["yes", "no", "unknown"] = "unknown"
    data_retention: Literal["none", "limited", "indefinite", "unknown"] = "unknown"
    data_residency: Literal[
        "quebec", "canada_outside_quebec", "us", "eu", "multi_region",
        "configurable", "unknown",
    ] = "unknown"
    sub_processors: Literal["disclosed", "undisclosed", "unknown"] = "unknown"
    provider_human_access: Literal["yes", "no", "unknown"] = "unknown"
    encryption_standard: Literal["strong", "partial", "none", "unknown"] = "unknown"
    ip_ownership: Literal["customer", "vendor", "unclear", "unknown"] = "unknown"
    applicable_law: Literal["quebec_canada", "foreign", "unknown"] = "unknown"
    foreign_vendor_dependency: Literal["yes", "no", "unknown"] = "unknown"
    contract_prohibits_reuse: Literal["yes", "no", "unknown"] = "unknown"
    authentication_support: Literal["sso_mfa", "partial", "none", "unknown"] = "unknown"
    audit_logging: Literal[
        "prompt_output_accessible", "access_logs_only", "none", "unknown"
    ] = "unknown"
    institutional_terms_available: Literal["yes", "no", "unknown"] = "unknown"
    dpa_available: Literal["yes", "no", "unknown"] = "unknown"
    institutional_use_restricted: Literal["yes", "no", "unknown"] = "unknown"
    quebec_higher_ed_license: Literal["yes", "no", "unknown"] = "unknown"
    incident_response: Literal[
        "documented_with_notice", "documented_no_notice", "none", "unknown"
    ] = "unknown"
    source_url: Optional[str] = None
    fetched_at: Optional[date] = None
    snapshot_ref: Optional[str] = None
    extraction_confidence: float = 0.0
    evidence: dict[str, FactEvidence] = Field(default_factory=dict)
    sources: list[ContractSource] = Field(default_factory=list)


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
    offering: Optional[ContractOfferingIdentity] = None
    contract_facts: ContractFacts
    criteria: list[RiskFactor] = Field(default_factory=list)
    schema_version: int = 1
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


class QualificationProfile(BaseModel):
    # Section 4 — Profil des utilisateurs
    nb_utilisateurs_vises: Optional[int] = None
    fonctions_roles: str = ""
    niveau_maitrise_ti: Optional[Literal["débutant", "intermédiaire", "avancé"]] = None
    formation_iag_recue: Optional[Literal["aucune", "partielle", "complète"]] = None
    acces_protege_a_ou_plus: Optional[Literal["oui", "non", "à vérifier"]] = None

    # Section 6 — Valeur attendue et bénéfices
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: Optional[Literal["faible", "modérée", "élevée"]] = None

    # Section 7 — Informations contractuelles et financières
    cout_annuel_par_utilisateur: str = ""
    cout_total_annuel: str = ""
    mode_acquisition: Optional[Literal[
        "achat_direct", "seao", "appel_offres", "contrat_existant"
    ]] = None
    duree_contrat: str = ""
    responsable_budgetaire: str = ""


class ToolRef(BaseModel):
    name: str
    vendor: Optional[str] = None
    iag_type: Optional[IagType] = None
    arp: Optional[ArpRecord] = None
    version_plan_tarifaire: str = ""
    offering: Optional[ContractOfferingIdentity] = None


class Usage(BaseModel):
    description: str = ""
    tool_ref: str = ""
    raw_answers: dict = Field(default_factory=dict)
    data_classification: Optional[DataClass] = None
    rens_personnels: bool = False
    efvpr_required: bool = False
    mode: list[Literal["prompt", "api"]] = Field(default_factory=list)
    frequence_utilisation: str = ""
    nb_utilisateurs: Optional[int] = None
    systemes_api_cibles: str = ""
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
    qualification: QualificationProfile = Field(default_factory=QualificationProfile)
    result_global: GlobalResult = Field(default_factory=GlobalResult)
    audit: dict = Field(default_factory=lambda: {"question_log": [], "timestamps": {}})
