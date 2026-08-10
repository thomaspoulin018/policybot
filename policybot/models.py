from __future__ import annotations

from datetime import date
from datetime import date as _date
import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field


IagType = Literal["publique", "circuit_ferme", "souveraine", "gouvernementale"]
DataClass = Literal["Non classifié", "Protégé A", "Protégé B", "Protégé C"]
RiskLetter = Literal["F", "M", "E"]


class ContractOfferingIdentity(BaseModel):
    vendor: str
    product: str
    plan: str = ""
    deployment_mode: str = "unknown"
    contract_type: str = "unknown"
    contract_version: str = ""
    jurisdiction: str = ""
    effective_date: Optional[date] = None

    def canonical_payload(self) -> dict[str, str]:
        return {
            "vendor": self.vendor.strip().casefold(),
            "product": self.product.strip().casefold(),
            "plan": self.plan.strip().casefold(),
            "deployment_mode": self.deployment_mode.strip().casefold(),
            "contract_type": self.contract_type.strip().casefold(),
            "contract_version": self.contract_version.strip().casefold(),
            "jurisdiction": self.jurisdiction.strip().casefold(),
            "effective_date": self.effective_date.isoformat() if self.effective_date else "",
        }

    def cache_key(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"offering:{hashlib.sha256(encoded).hexdigest()}"

    def missing_search_identity_fields(self) -> tuple[str, ...]:
        values = {
            "vendor": self.vendor,
            "product": self.product,
            "plan": self.plan,
            "deployment_mode": self.deployment_mode,
            "contract_type": self.contract_type,
            "contract_version": self.contract_version,
        }
        return tuple(
            name for name, value in values.items()
            if not value.strip() or value.strip().casefold() == "unknown"
        )

    def display_label(self) -> str:
        parts = [self.vendor, self.product, self.plan, self.deployment_mode,
                 self.contract_type, self.contract_version, self.jurisdiction]
        if self.effective_date:
            parts.append(self.effective_date.isoformat())
        return " — ".join(part for part in parts if part and part != "unknown")


class CriterionCitation(BaseModel):
    url: str
    title: str = ""
    text: str
    begin: int | None = None
    end: int | None = None
    anchored: bool = False
    deep_link: str = ""
    source_type: str = "unknown"
    collected_at: date = Field(default_factory=date.today)


class CriterionFinding(BaseModel):
    id: str
    partie: Literal["A", "B"]
    category: str
    criterion: str
    question: str
    answer: str = ""
    inherent_risk: RiskLetter | None = None
    justification: str = ""
    citations: list[CriterionCitation] = Field(default_factory=list)
    rejected_citations: int = 0
    exa_type: str = "neural"
    cost_dollars: float = 0.0
    outcome: Literal["ok", "no_answer", "search_failed"] = "ok"


class ArpRecord(BaseModel):
    tool_name: str
    iag_type: IagType
    offering: ContractOfferingIdentity | None = None
    findings: list[CriterionFinding] = Field(default_factory=list)
    total_cost_dollars: float = 0.0
    schema_version: int = 2
    fetched_at: date | None = None
    expires_at: date | None = None


class RequestInfo(BaseModel):
    numero: str
    demandeur: str = ""
    unite: str = ""
    # Le champ « date » masque le type « date » dans le corps de la classe :
    # sans l'alias, l'annotation se résout sur l'attribut et n'accepte que None.
    date: Optional[_date] = None


class QualificationProfile(BaseModel):
    nb_utilisateurs_vises: Optional[int] = None
    fonctions_roles: str = ""
    niveau_maitrise_ti: Optional[Literal["débutant", "intermédiaire", "avancé"]] = None
    formation_iag_recue: Optional[Literal["aucune", "partielle", "complète"]] = None
    acces_protege_a_ou_plus: Optional[Literal["oui", "non", "à vérifier"]] = None
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: Optional[Literal["faible", "modérée", "élevée"]] = None
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


class InterviewState(BaseModel):
    interview_id: str
    status: Literal["in_progress", "awaiting_terms", "complete"] = "in_progress"
    request: RequestInfo
    tools: list[ToolRef] = Field(default_factory=list)
    usages: list[Usage] = Field(default_factory=list)
    qualification: QualificationProfile = Field(default_factory=QualificationProfile)
    audit: dict = Field(default_factory=lambda: {"question_log": [], "timestamps": {}})
