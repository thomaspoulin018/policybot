"""Écriture d'un export Microsoft Forms de démonstration.

Le fichier `tests/fixtures/reponses_forms.xlsx` est binaire, donc illisible
en diff : il est produit ici, en clair, par le code de test. Régénérer :

    python -m tests.helpers.forms
"""
from __future__ import annotations

from pathlib import Path

from policybot.intake.formulaire import formulaire


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "reponses_forms.xlsx"

# Colonnes que Microsoft Forms place avant les réponses, reprises telles quelles.
COLONNES_TECHNIQUES = ("ID", "Heure de début", "Heure de fin", "Adresse de courriel", "Nom")

# Une entrée par demande, indexée par champ de DemandeIAG. Les valeurs sont les
# LIBELLÉS de choix, comme Forms les exporte — pas les valeurs de schéma.
REPONSES: tuple[dict[str, str], ...] = (
    {
        "demandeur": "Marie Tremblay",
        "unite": "Direction des services administratifs",
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "deployment_mode": "Service public",
        "contract_type": "Conditions grand public",
        "contract_version": "Conditions d'utilisation - juillet 2026",
        "contract_effective_date": "2026-07-01",
        "jurisdiction": "Californie, États-Unis",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques et agents administratifs",
        "niveau_maitrise_ti": "Intermédiaire",
        "formation_iag_recue": "Partielle",
        "acces_protege_a_ou_plus": "Non",
        "data_checked": "Information déjà publique",
        "data_free_text": "articles et communiqués déjà publiés sur le Web",
        "usage_description": "Préparer une veille et résumer des sources publiques.",
        "mode": "Messages directs (prompt)",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "8",
        "systemes_api_cibles": "",
        "result_use_checked": "Aide à la rédaction / diffusion interne",
        "result_use_free_text": "validation humaine avant toute diffusion",
        "automated_decisions": "Non",
        "besoin_affaires": "réduire le temps de préparation des réponses récurrentes",
        "gains_qualitatifs": "meilleure cohérence des brouillons",
        "gains_quantitatifs": "environ 3 heures économisées par semaine",
        "alternatives_considerees": "gabarits Word existants et recherche manuelle",
        "urgence_percue": "Modérée",
        "cout_annuel_par_utilisateur": "300 $",
        "cout_total_annuel": "2400 $",
        "mode_acquisition": "Achat direct",
        "duree_contrat": "12 mois",
        "responsable_budgetaire": "Direction des services administratifs",
        "tool_type_override": "",
    },
    {
        "demandeur": "Jean Nadeau",
        "unite": "Direction des technologies de l'information",
        "tool_name": "Microsoft Copilot Entreprise",
        "version_plan_tarifaire": "Licence institutionnelle Entreprise",
        "deployment_mode": "Service institutionnel géré",
        "contract_type": "Contrat institutionnel",
        "contract_version": "Microsoft Customer Agreement - 2026",
        "contract_effective_date": "2026-01-01",
        "jurisdiction": "Québec, Canada",
        "nb_utilisateurs_vises": "120",
        "fonctions_roles": "personnel administratif et techniciens",
        "niveau_maitrise_ti": "Avancé",
        "formation_iag_recue": "Complète (MCN)",
        "acces_protege_a_ou_plus": "Oui",
        "data_checked": "Documents internes de travail",
        "data_free_text": "notes de travail internes non publiques, sans renseignement personnel",
        "usage_description": "Résumer des procédures administratives internes.",
        "mode": "Messages directs (prompt)",
        "frequence_utilisation": "quotidienne",
        "nb_utilisateurs": "40",
        "systemes_api_cibles": "",
        "result_use_checked": "Intrant dans un autre processus;Aide à la rédaction / diffusion interne",
        "result_use_free_text": "relecture systématique par une personne",
        "automated_decisions": "Non",
        "besoin_affaires": "faciliter la consultation des procédures internes",
        "gains_qualitatifs": "réponses plus homogènes entre équipes",
        "gains_quantitatifs": "environ 20 heures par mois",
        "alternatives_considerees": "intranet et recherche plein texte",
        "urgence_percue": "Faible",
        "cout_annuel_par_utilisateur": "420 $",
        "cout_total_annuel": "50400 $",
        "mode_acquisition": "Contrat existant",
        "duree_contrat": "36 mois",
        "responsable_budgetaire": "Direction des technologies de l'information",
        "tool_type_override": "",
    },
    {
        "demandeur": "Sophie Gagnon",
        "unite": "Bureau du registraire",
        "tool_name": "Gemini",
        "tool_type_override": "IAG publique",
        "version_plan_tarifaire": "Workspace Business",
        "deployment_mode": "Service institutionnel géré",
        "contract_type": "Entente de traitement des données",
        "contract_version": "Google Workspace DPA 2026",
        "contract_effective_date": "2026-03-15",
        "jurisdiction": "Québec, Canada",
        "nb_utilisateurs_vises": "12",
        "fonctions_roles": "agents de gestion des études",
        "niveau_maitrise_ti": "Débutant",
        "formation_iag_recue": "Aucune",
        "acces_protege_a_ou_plus": "À vérifier",
        "data_checked": "Information déjà publique;Documents internes de travail",
        "data_free_text": "calendriers publics et gabarits de correspondance interne",
        "usage_description": "Rédiger des accusés de réception à partir de gabarits.",
        "mode": "Intégration technique (API)",
        "frequence_utilisation": "en continu pendant les périodes d'admission",
        "nb_utilisateurs": "12",
        "systemes_api_cibles": "système de gestion des dossiers étudiants",
        "result_use_checked": "Aide à la rédaction / diffusion interne",
        "result_use_free_text": "révision par un agent avant envoi",
        "automated_decisions": "Non",
        "besoin_affaires": "absorber la pointe de demandes de la période d'admission",
        "gains_qualitatifs": "délais de réponse plus constants",
        "gains_quantitatifs": "environ 1 200 courriels traités par mois",
        "alternatives_considerees": "embauche temporaire",
        "urgence_percue": "Élevée",
        "cout_annuel_par_utilisateur": "180 $",
        "cout_total_annuel": "2160 $",
        "mode_acquisition": "Via SEAO",
        "duree_contrat": "24 mois",
        "responsable_budgetaire": "Bureau du registraire",
    },
)


def entetes() -> list[str]:
    """Les colonnes de l'export : celles de Forms, puis les 35 questions."""
    return list(COLONNES_TECHNIQUES) + [q.intitule for q in formulaire().questions]


def lignes() -> list[list[str]]:
    par_champ = {q.champ: q for q in formulaire().questions}
    resultat: list[list[str]] = []
    for index, reponse in enumerate(REPONSES, start=1):
        inconnus = set(reponse) - set(par_champ)
        if inconnus:
            raise KeyError(f"champs inconnus dans la fixture : {sorted(inconnus)}")
        ligne = [
            str(index),
            f"2026-08-0{index} 09:0{index}:00",
            f"2026-08-0{index} 09:1{index}:00",
            f"demandeur{index}@example.org",
            reponse["demandeur"],
        ]
        ligne += [reponse.get(champ, "") for champ in par_champ]
        resultat.append(ligne)
    return resultat


def ecrire_export(chemin: str | Path, entetes_: list[str] | None = None,
                  lignes_: list[list[str]] | None = None) -> Path:
    """Écrit un classeur au format d'un export Forms."""
    from openpyxl import Workbook

    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    classeur = Workbook()
    feuille = classeur.active
    feuille.title = "Réponses 1"
    feuille.append(entetes_ if entetes_ is not None else entetes())
    for ligne in (lignes_ if lignes_ is not None else lignes()):
        feuille.append(ligne)
    classeur.save(chemin)
    return chemin


if __name__ == "__main__":
    print(ecrire_export(FIXTURE))
