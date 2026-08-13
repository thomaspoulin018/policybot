"""Réponses Google Forms figées, entièrement lisibles dans les tests."""
from __future__ import annotations

import json
from pathlib import Path

from policybot.intake.formulaire import formulaire

# Une entrée par demande, indexée par champ de DemandeIAG. Les valeurs sont les
# libellés affichés par Google Forms, pas les valeurs de schéma.
REPONSES: tuple[dict[str, str], ...] = (
    {
        "demandeur": "Marie Tremblay",
        "unite": "Direction des services administratifs",
        "tool_name": "ChatGPT",
        "version_plan_tarifaire": "Plan Plus",
        "contract_type": "Conditions grand public",
        "contract_version": "Conditions d'utilisation - juillet 2026",
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
        "frequence_utilisation": "Quelques fois par semaine",
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
        "contract_type": "Contrat institutionnel",
        "contract_version": "Microsoft Customer Agreement - 2026",
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
        "frequence_utilisation": "Tous les jours",
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
        "contract_type": "Entente de traitement des données",
        "contract_version": "Google Workspace DPA 2026",
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
        "frequence_utilisation": "En continu, intégré au travail courant",
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


def mapping_questions() -> dict[str, str]:
    return {f"q{question.numero:03d}": question.champ for question in formulaire().questions}


def configuration_mapping() -> dict:
    return {
        "form_id": "form-test",
        "responder_uri": "https://docs.google.test/forms/form-test/viewform",
        "created_at": "2026-08-12T12:00:00+00:00",
        "catalogue_version": formulaire().version,
        "questions": mapping_questions(),
    }


def _libelle_google(question, valeur: str) -> str:
    if question.type not in {"choix", "choix_multiple"}:
        return valeur
    cible = question.valeur_pour(valeur)
    for choix in question.choix:
        if choix.valeur == cible:
            return choix.libelle + (f" — {choix.description}" if choix.description else "")
    return valeur


def document_reponses(reponses_=None) -> dict:
    """Construit la représentation exacte de forms.responses.list()."""
    reponses_ = REPONSES if reponses_ is None else reponses_
    questions = {question.champ: question for question in formulaire().questions}
    ids = {champ: question_id for question_id, champ in mapping_questions().items()}
    resultat = []
    for index, reponse in enumerate(reponses_, start=1):
        inconnus = set(reponse) - set(questions)
        if inconnus:
            raise KeyError(f"champs inconnus dans la fixture : {sorted(inconnus)}")
        answers = {}
        for champ, valeur in reponse.items():
            if valeur == "":
                continue
            question = questions[champ]
            valeurs = valeur.split(";") if question.type == "choix_multiple" else [valeur]
            valeurs = [_libelle_google(question, item) for item in valeurs]
            question_id = ids[champ]
            answers[question_id] = {
                "questionId": question_id,
                "textAnswers": {"answers": [{"value": item} for item in valeurs]},
            }
        resultat.append(
            {
                "responseId": f"response-{index}",
                "createTime": f"2026-08-0{index}T13:00:00Z",
                "lastSubmittedTime": f"2026-08-0{index}T13:10:00Z",
                "answers": answers,
            }
        )
    return {"responses": resultat}


def ecrire_reponses(chemin: str | Path, document: dict | None = None) -> Path:
    chemin = Path(chemin)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(document or document_reponses(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chemin


if __name__ == "__main__":
    print(ecrire_reponses(Path("reponses-test.json")))
