"""Le schéma d'une demande, tel que Google Forms la remplit.

`DemandeIAG` est le contrat d'entrée de PolicyBot : c'est ce que le lecteur
d'un JSON de réponses produit et ce que l'orchestrateur consomme. Les
noms de champs sont ceux que `configs/formulaire.yaml` déclare, question
par question.
"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional
import uuid

from pydantic import BaseModel, Field, field_validator

from policybot.classify.tool_registry import lookup_tool
from policybot.classify.tool_registry import classify_tool_type
from policybot.contract.offering import build_offering_identity
from policybot.models import (
    ContractOfferingIdentity,
    IagType,
    QualificationProfile,
    RequestInfo,
)


class TypeIagInconnuError(ValueError):
    """L'outil n'est pas au registre et la demande ne précise pas son type."""

    def __init__(self, tool_name: str):
        super().__init__(
            f"Type IAG inconnu pour l'outil « {tool_name} » : "
            "précise le type d'outil dans le formulaire."
        )
        self.tool_name = tool_name


class EntreesOrchestrateur(BaseModel):
    """Les arguments d'un appel à `Interview.assess()`, déjà résolus."""

    request: RequestInfo
    tool_name: str
    usage_inputs: list[dict]
    iag_type: IagType
    iag_type_override: Optional[IagType] = None
    qualification: QualificationProfile
    offering: ContractOfferingIdentity


class DemandeIAG(BaseModel):
    """Une réponse au formulaire — un outil, un usage, un demandeur."""

    # Section 1 — la demande
    demandeur: str
    unite: str

    # Section 2 — l'outil et son offre contractuelle
    tool_name: str
    tool_type_override: Optional[IagType] = None
    version_plan_tarifaire: str = ""
    deployment_mode: str = ""
    contract_type: str = ""
    contract_version: str = ""
    # Pas de date d'effet : elle n'entrait dans aucune requête de recherche
    # (contract/criteres.py, QUERY_FIELDS) et ne servait qu'à l'étiquette
    # d'affichage de l'offre. `ContractOfferingIdentity.effective_date` reste
    # disponible pour un appelant qui la connaît par un autre chemin.
    jurisdiction: str = ""

    # Section 3 — qui utilisera l'outil
    nb_utilisateurs_vises: Optional[int] = None
    fonctions_roles: str = ""
    niveau_maitrise_ti: Optional[Literal["débutant", "intermédiaire", "avancé"]] = None
    formation_iag_recue: Optional[Literal["aucune", "partielle", "complète"]] = None
    acces_protege_a_ou_plus: Optional[Literal["oui", "non", "à vérifier"]] = None

    # Section 4 — les données soumises
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str

    # Section 5 — l'usage prévu
    usage_description: str
    mode: Optional[Literal["prompt", "api"]] = None
    frequence_utilisation: str = ""
    nb_utilisateurs: Optional[int] = None
    systemes_api_cibles: str = ""
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False

    # Section 6 — le contexte d'affaires
    besoin_affaires: str
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

    @field_validator(
        "demandeur", "unite", "tool_name", "data_free_text",
        "usage_description", "besoin_affaires",
    )
    @classmethod
    def _non_vide(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("réponse obligatoire manquante")
        return value.strip()

    def description_donnees(self) -> str:
        """La description soumise au classificateur : cases cochées puis texte."""
        parts = list(self.data_checked) + ([self.data_free_text] if self.data_free_text else [])
        return "; ".join(parts)

    def usage_input(self) -> dict:
        result_use = list(self.result_use_checked)
        if self.result_use_free_text:
            result_use.append(self.result_use_free_text)
        return {
            "description": self.usage_description,
            "data_description": self.description_donnees(),
            "automated_decisions": self.automated_decisions,
            "mode": [self.mode] if self.mode else ["prompt"],
            "result_use": result_use,
            "frequence_utilisation": self.frequence_utilisation,
            "nb_utilisateurs": self.nb_utilisateurs,
            "systemes_api_cibles": self.systemes_api_cibles,
        }

    def qualification(self) -> QualificationProfile:
        return QualificationProfile(
            nb_utilisateurs_vises=self.nb_utilisateurs_vises,
            fonctions_roles=self.fonctions_roles,
            niveau_maitrise_ti=self.niveau_maitrise_ti,
            formation_iag_recue=self.formation_iag_recue,
            acces_protege_a_ou_plus=self.acces_protege_a_ou_plus,
            besoin_affaires=self.besoin_affaires,
            gains_qualitatifs=self.gains_qualitatifs,
            gains_quantitatifs=self.gains_quantitatifs,
            alternatives_considerees=self.alternatives_considerees,
            urgence_percue=self.urgence_percue,
            cout_annuel_par_utilisateur=self.cout_annuel_par_utilisateur,
            cout_total_annuel=self.cout_total_annuel,
            mode_acquisition=self.mode_acquisition,
            duree_contrat=self.duree_contrat,
            responsable_budgetaire=self.responsable_budgetaire,
        )

    def numero(self, today: date | None = None) -> str:
        today = today or date.today()
        return f"IAG-{today:%Y}-{uuid.uuid4().hex[:6]}"

    def vers_entrees_orchestrateur(
        self,
        *,
        numero: str | None = None,
        today: date | None = None,
    ) -> EntreesOrchestrateur:
        """Résout l'identité d'offre et prépare l'appel à `Interview.assess()`.

        Aucun appel réseau : la résolution ne consulte que le registre local
        d'outils et les réponses du formulaire.
        """
        iag_type = classify_tool_type(self.tool_name) or self.tool_type_override
        if iag_type is None:
            raise TypeIagInconnuError(self.tool_name)
        entry = lookup_tool(self.tool_name) or {}
        offering = build_offering_identity(
            self.tool_name,
            iag_type,
            vendor=entry.get("vendor"),
            plan=self.version_plan_tarifaire,
            deployment_mode=self.deployment_mode or None,
            contract_type=self.contract_type or None,
            contract_version=self.contract_version or None,
            jurisdiction=self.jurisdiction or None,
        )
        today = today or date.today()
        return EntreesOrchestrateur(
            request=RequestInfo(
                numero=numero or self.numero(today),
                demandeur=self.demandeur,
                unite=self.unite,
                date=today,
            ),
            tool_name=self.tool_name,
            usage_inputs=[self.usage_input()],
            iag_type=iag_type,
            iag_type_override=self.tool_type_override,
            qualification=self.qualification(),
            offering=offering,
        )
