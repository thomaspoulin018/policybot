from __future__ import annotations
import json
from typing import Literal
from pydantic import BaseModel, Field
from policybot.models import IagType


class WizardUsageDraft(BaseModel):
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str = ""
    usage_description: str = ""
    mode: Literal["prompt", "api"] | None = None
    frequence_utilisation: str = ""
    nb_utilisateurs: str = ""
    systemes_api_cibles: str = ""
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False


class WizardState(BaseModel):
    tool_name: str = ""
    demandeur: str = ""
    unite: str = ""
    tool_type_override: IagType | None = None
    version_plan_tarifaire: str = ""
    deployment_mode: str = ""
    contract_type: str = ""
    contract_version: str = ""
    contract_effective_date: str = ""
    nb_utilisateurs_vises: str = ""
    fonctions_roles: str = ""
    niveau_maitrise_ti: str = ""
    formation_iag_recue: str = ""
    acces_protege_a_ou_plus: str = ""
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str = ""
    usage_description: str = ""
    mode: Literal["prompt", "api"] | None = None
    frequence_utilisation: str = ""
    nb_utilisateurs: str = ""
    systemes_api_cibles: str = ""
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: str = ""
    cout_annuel_par_utilisateur: str = ""
    cout_total_annuel: str = ""
    mode_acquisition: str = ""
    duree_contrat: str = ""
    responsable_budgetaire: str = ""
    saved_usages: list[WizardUsageDraft] = Field(default_factory=list)

    def to_hidden_fields(self) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        if self.tool_name:
            fields.append(("tool_name", self.tool_name))
        if self.demandeur:
            fields.append(("demandeur", self.demandeur))
        if self.unite:
            fields.append(("unite", self.unite))
        if self.tool_type_override:
            fields.append(("tool_type_override", self.tool_type_override))
        if self.version_plan_tarifaire:
            fields.append(("version_plan_tarifaire", self.version_plan_tarifaire))
        if self.deployment_mode:
            fields.append(("deployment_mode", self.deployment_mode))
        if self.contract_type:
            fields.append(("contract_type", self.contract_type))
        if self.contract_version:
            fields.append(("contract_version", self.contract_version))
        if self.contract_effective_date:
            fields.append(("contract_effective_date", self.contract_effective_date))
        if self.nb_utilisateurs_vises:
            fields.append(("nb_utilisateurs_vises", self.nb_utilisateurs_vises))
        if self.fonctions_roles:
            fields.append(("fonctions_roles", self.fonctions_roles))
        if self.niveau_maitrise_ti:
            fields.append(("niveau_maitrise_ti", self.niveau_maitrise_ti))
        if self.formation_iag_recue:
            fields.append(("formation_iag_recue", self.formation_iag_recue))
        if self.acces_protege_a_ou_plus:
            fields.append(("acces_protege_a_ou_plus", self.acces_protege_a_ou_plus))
        for label in self.data_checked:
            fields.append(("data_checked", label))
        if self.data_free_text:
            fields.append(("data_free_text", self.data_free_text))
        if self.usage_description:
            fields.append(("usage_description", self.usage_description))
        if self.mode:
            fields.append(("mode", self.mode))
        if self.frequence_utilisation:
            fields.append(("frequence_utilisation", self.frequence_utilisation))
        if self.nb_utilisateurs:
            fields.append(("nb_utilisateurs", self.nb_utilisateurs))
        if self.systemes_api_cibles:
            fields.append(("systemes_api_cibles", self.systemes_api_cibles))
        for label in self.result_use_checked:
            fields.append(("result_use_checked", label))
        if self.result_use_free_text:
            fields.append(("result_use_free_text", self.result_use_free_text))
        if self.automated_decisions:
            fields.append(("automated_decisions", "true"))
        if self.besoin_affaires:
            fields.append(("besoin_affaires", self.besoin_affaires))
        if self.gains_qualitatifs:
            fields.append(("gains_qualitatifs", self.gains_qualitatifs))
        if self.gains_quantitatifs:
            fields.append(("gains_quantitatifs", self.gains_quantitatifs))
        if self.alternatives_considerees:
            fields.append(("alternatives_considerees", self.alternatives_considerees))
        if self.urgence_percue:
            fields.append(("urgence_percue", self.urgence_percue))
        if self.cout_annuel_par_utilisateur:
            fields.append(("cout_annuel_par_utilisateur", self.cout_annuel_par_utilisateur))
        if self.cout_total_annuel:
            fields.append(("cout_total_annuel", self.cout_total_annuel))
        if self.mode_acquisition:
            fields.append(("mode_acquisition", self.mode_acquisition))
        if self.duree_contrat:
            fields.append(("duree_contrat", self.duree_contrat))
        if self.responsable_budgetaire:
            fields.append(("responsable_budgetaire", self.responsable_budgetaire))
        if self.saved_usages:
            fields.append((
                "saved_usages_json",
                json.dumps([usage.model_dump() for usage in self.saved_usages], ensure_ascii=False),
            ))
        return fields

    @classmethod
    def from_form(cls, form: dict) -> "WizardState":
        def as_list(key: str) -> list[str]:
            value = form.get(key, [])
            if isinstance(value, list):
                return value
            return [value] if value else []

        saved_usages = []
        saved_usages_json = form.get("saved_usages_json", "") or ""
        if saved_usages_json:
            try:
                parsed = json.loads(saved_usages_json)
                if isinstance(parsed, list):
                    saved_usages = [WizardUsageDraft(**item) for item in parsed if isinstance(item, dict)]
            except (TypeError, ValueError):
                saved_usages = []

        return cls(
            tool_name=form.get("tool_name", "") or "",
            demandeur=form.get("demandeur", "") or "",
            unite=form.get("unite", "") or "",
            tool_type_override=form.get("tool_type_override") or None,
            version_plan_tarifaire=form.get("version_plan_tarifaire", "") or "",
            deployment_mode=form.get("deployment_mode", "") or "",
            contract_type=form.get("contract_type", "") or "",
            contract_version=form.get("contract_version", "") or "",
            contract_effective_date=form.get("contract_effective_date", "") or "",
            nb_utilisateurs_vises=form.get("nb_utilisateurs_vises", "") or "",
            fonctions_roles=form.get("fonctions_roles", "") or "",
            niveau_maitrise_ti=form.get("niveau_maitrise_ti", "") or "",
            formation_iag_recue=form.get("formation_iag_recue", "") or "",
            acces_protege_a_ou_plus=form.get("acces_protege_a_ou_plus", "") or "",
            data_checked=as_list("data_checked"),
            data_free_text=form.get("data_free_text", "") or "",
            usage_description=form.get("usage_description", "") or "",
            mode=form.get("mode") or None,
            frequence_utilisation=form.get("frequence_utilisation", "") or "",
            nb_utilisateurs=form.get("nb_utilisateurs", "") or "",
            systemes_api_cibles=form.get("systemes_api_cibles", "") or "",
            result_use_checked=as_list("result_use_checked"),
            result_use_free_text=form.get("result_use_free_text", "") or "",
            automated_decisions=str(form.get("automated_decisions", "")).lower() == "true",
            besoin_affaires=form.get("besoin_affaires", "") or "",
            gains_qualitatifs=form.get("gains_qualitatifs", "") or "",
            gains_quantitatifs=form.get("gains_quantitatifs", "") or "",
            alternatives_considerees=form.get("alternatives_considerees", "") or "",
            urgence_percue=form.get("urgence_percue", "") or "",
            cout_annuel_par_utilisateur=form.get("cout_annuel_par_utilisateur", "") or "",
            cout_total_annuel=form.get("cout_total_annuel", "") or "",
            mode_acquisition=form.get("mode_acquisition", "") or "",
            duree_contrat=form.get("duree_contrat", "") or "",
            responsable_budgetaire=form.get("responsable_budgetaire", "") or "",
            saved_usages=saved_usages,
        )

    def current_usage_draft(self) -> WizardUsageDraft:
        return WizardUsageDraft(
            data_checked=list(self.data_checked),
            data_free_text=self.data_free_text,
            usage_description=self.usage_description,
            mode=self.mode,
            frequence_utilisation=self.frequence_utilisation,
            nb_utilisateurs=self.nb_utilisateurs,
            systemes_api_cibles=self.systemes_api_cibles,
            result_use_checked=list(self.result_use_checked),
            result_use_free_text=self.result_use_free_text,
            automated_decisions=self.automated_decisions,
        )

    def has_current_usage(self) -> bool:
        current = self.current_usage_draft()
        return any((
            current.data_checked,
            current.data_free_text,
            current.usage_description,
            current.mode,
            current.frequence_utilisation,
            current.nb_utilisateurs,
            current.systemes_api_cibles,
            current.result_use_checked,
            current.result_use_free_text,
            current.automated_decisions,
        ))

    def with_current_usage_saved(self) -> "WizardState":
        if not self.has_current_usage():
            return self
        state = self.model_copy(deep=True)
        state.saved_usages.append(self.current_usage_draft())
        return state

    def cleared_current_usage(self) -> "WizardState":
        state = self.model_copy(deep=True)
        state.data_checked = []
        state.data_free_text = ""
        state.usage_description = ""
        state.mode = None
        state.frequence_utilisation = ""
        state.nb_utilisateurs = ""
        state.systemes_api_cibles = ""
        state.result_use_checked = []
        state.result_use_free_text = ""
        state.automated_decisions = False
        return state


def compose_description(checked_labels: list[str], free_text: str) -> str:
    parts = list(checked_labels) + ([free_text] if free_text else [])
    return "; ".join(parts)


class DemoWizardScenario(BaseModel):
    id: str
    title: str
    description: str
    expected_result: str
    state: WizardState


def _demo_state(**overrides) -> WizardState:
    values = {
        "tool_name": "ChatGPT",
        "demandeur": "Marie Tremblay",
        "unite": "Direction des services administratifs",
        "version_plan_tarifaire": "Plan Plus",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques et agents administratifs",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
        "data_checked": ["Information déjà publique"],
        "data_free_text": "articles et communiqués déjà publiés sur le Web",
        "usage_description": "Préparer une veille et résumer des sources publiques.",
        "mode": "prompt",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "8",
        "systemes_api_cibles": "aucun système cible pour ce test",
        "result_use_checked": ["Aide à la rédaction / diffusion interne"],
        "result_use_free_text": "validation humaine avant toute diffusion",
        "automated_decisions": False,
        "besoin_affaires": "réduire le temps de préparation des réponses récurrentes",
        "gains_qualitatifs": "meilleure cohérence des brouillons et démarrage plus rapide",
        "gains_quantitatifs": "environ 3 heures économisées par semaine",
        "alternatives_considerees": "gabarits Word existants et recherche manuelle",
        "urgence_percue": "modérée",
        "cout_annuel_par_utilisateur": "300 $",
        "cout_total_annuel": "2400 $",
        "mode_acquisition": "achat_direct",
        "duree_contrat": "12 mois",
        "responsable_budgetaire": "Direction des services administratifs",
    }
    values.update(overrides)
    return WizardState(**values)


def demo_wizard_scenarios() -> list[DemoWizardScenario]:
    return [
        DemoWizardScenario(
            id="public_permitted",
            title="Usage public — parcours permis",
            description="ChatGPT traite uniquement des sources déjà publiques.",
            expected_result="Cible : matrice PERMIS et analyse ARP de l'outil.",
            state=_demo_state(),
        ),
        DemoWizardScenario(
            id="mcn_blocked",
            title="Blocage par la matrice MCN",
            description="Une IAG publique reçoit des données stratégiques et personnelles.",
            expected_result="Cible : INTERDIT et recommandation Refuser, sans analyse ARP.",
            state=_demo_state(
                data_checked=[
                    "Renseignements personnels",
                    "Données stratégiques / confidentielles",
                ],
                data_free_text=(
                    "prévisions budgétaires confidentielles avec les noms et coordonnées "
                    "des personnes responsables"
                ),
                usage_description="Résumer des rapports financiers stratégiques internes.",
                result_use_checked=["Prise de décision"],
                besoin_affaires="accélérer l'analyse de rapports financiers confidentiels",
            ),
        ),
        DemoWizardScenario(
            id="arp_closed_circuit",
            title="Analyse ARP — circuit fermé",
            description="Copilot Entreprise traite des documents internes Protégé A.",
            expected_result="Cible : matrice PERMIS, collecte contractuelle et grille ARP.",
            state=_demo_state(
                tool_name="Microsoft Copilot Entreprise",
                version_plan_tarifaire="Licence institutionnelle Entreprise",
                acces_protege_a_ou_plus="oui",
                data_checked=["Documents internes de travail"],
                data_free_text="notes de travail internes non publiques, sans renseignement personnel",
                usage_description="Résumer des procédures administratives internes.",
                besoin_affaires="faciliter la consultation des procédures internes",
                mode_acquisition="contrat_existant",
            ),
        ),
        DemoWizardScenario(
            id="protege_c_governmental",
            title="Protégé C — IAG gouvernementale",
            description="Une plateforme gouvernementale contrôlée traite un secret hautement sensible.",
            expected_result="Cible : cellule MCN OBLIGATOIRE et ÉFVP-R requise.",
            state=_demo_state(
                tool_name="Assistant gouvernemental sécurisé",
                tool_type_override="gouvernementale",
                version_plan_tarifaire="Environnement gouvernemental contrôlé",
                acces_protege_a_ou_plus="oui",
                data_checked=[
                    "Renseignements personnels",
                    "Données stratégiques / confidentielles",
                ],
                data_free_text=(
                    "secrets de sécurité hautement sensibles, clés cryptographiques et "
                    "renseignements personnels à accès extrêmement restreint"
                ),
                usage_description="Analyser un dossier de sécurité hautement sensible.",
                result_use_checked=["Prise de décision"],
                besoin_affaires="appuyer une analyse gouvernementale à accès restreint",
                mode_acquisition="contrat_existant",
            ),
        ),
        DemoWizardScenario(
            id="automated_decision",
            title="Décision automatisée",
            description="Des données publiques alimentent une décision sans révision humaine.",
            expected_result="Cible : risque élevé et recommandation Escalader.",
            state=_demo_state(
                usage_description="Classer automatiquement les demandes reçues selon leur priorité.",
                result_use_checked=["Prise de décision"],
                result_use_free_text="déclenchement automatique du prochain traitement",
                automated_decisions=True,
                besoin_affaires="réduire le délai de triage des demandes",
            ),
        ),
        DemoWizardScenario(
            id="multiple_usages",
            title="Plusieurs usages — pire verdict",
            description="Un usage public permis et un usage stratégique interdit partagent le même outil.",
            expected_result="Cible : la synthèse globale conserve Refuser.",
            state=_demo_state(
                data_checked=["Données stratégiques / confidentielles"],
                data_free_text="prévisions financières internes confidentielles",
                usage_description="Résumer les prévisions budgétaires stratégiques.",
                result_use_checked=["Prise de décision"],
                saved_usages=[
                    WizardUsageDraft(
                        data_checked=["Information déjà publique"],
                        data_free_text="communiqués publiés sur le site institutionnel",
                        usage_description="Préparer une veille à partir de sources publiques.",
                        mode="prompt",
                        frequence_utilisation="hebdomadaire",
                        nb_utilisateurs="8",
                        result_use_checked=["Aide à la rédaction / diffusion interne"],
                        result_use_free_text="validation humaine avant diffusion",
                    )
                ],
                besoin_affaires="comparer une veille publique aux prévisions internes",
            ),
        ),
    ]


def demo_wizard_state(scenario_id: str = "public_permitted") -> WizardState:
    for scenario in demo_wizard_scenarios():
        if scenario.id == scenario_id:
            return scenario.state.model_copy(deep=True)
    raise KeyError(scenario_id)

