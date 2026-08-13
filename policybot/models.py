from __future__ import annotations

from datetime import date
from datetime import date as _date
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

    def missing_search_identity_fields(self) -> tuple[str, ...]:
        # `contract_version` est volontairement absent : la plupart des
        # demandeurs utilisent un outil aux conditions publiques de son site,
        # sans document signé. Un champ vide y est la réponse normale, pas le
        # signe d'une offre mal identifiée — le signaler noyait les vraies
        # lacunes sous une alerte permanente.
        values = {
            "vendor": self.vendor,
            "product": self.product,
            "plan": self.plan,
            "deployment_mode": self.deployment_mode,
            "contract_type": self.contract_type,
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
    """Un outil évalué et ses constats recherchés pour son offre.

    Les constats étaient auparavant enveloppés dans un `ArpRecord` porteur d'un
    numéro de schéma et d'une date de péremption. Ces champs n'existaient que
    pour le cache local, qui a été retiré : une recherche coûte moins cher que
    la maintenance d'un cache indexé par identité d'offre.
    """

    name: str
    vendor: Optional[str] = None
    iag_type: Optional[IagType] = None
    findings: list[CriterionFinding] = Field(default_factory=list)
    version_plan_tarifaire: str = ""
    offering: Optional[ContractOfferingIdentity] = None

    @property
    def total_cost_dollars(self) -> float:
        return round(sum(item.cost_dollars for item in self.findings), 8)


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
