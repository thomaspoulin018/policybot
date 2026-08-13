import copy
from pathlib import Path

import pytest

from policybot.intake.formulaire import formulaire
from policybot.intake.reponses import FichierReponsesInvalideError, lire_reponses

from tests.helpers.forms import (
    configuration_mapping,
    document_reponses,
    ecrire_reponses,
    mapping_questions,
)


def _id(champ: str) -> str:
    return next(cle for cle, valeur in mapping_questions().items() if valeur == champ)


def _valeurs(document: dict, index: int, champ: str) -> list[dict]:
    return document["responses"][index]["answers"][_id(champ)]["textAnswers"]["answers"]


@pytest.fixture
def fichier(tmp_path: Path) -> Path:
    return ecrire_reponses(tmp_path / "reponses.json")


def test_le_json_fixe_donne_trois_demandes_sans_rejet(fichier):
    lot = lire_reponses(fichier, configuration_mapping())

    assert lot.reponses_lues == 3
    assert len(lot.demandes) == 3
    assert lot.rejets == []


def test_les_cases_a_cocher_restent_une_liste_native(fichier):
    lot = lire_reponses(fichier, configuration_mapping())

    assert lot.demandes[2].data_checked == [
        "Information déjà publique",
        "Documents internes de travail",
    ]


def test_les_libelles_et_descriptions_sont_traduits_en_valeurs_de_schema(fichier):
    premiere, _, troisieme = lire_reponses(fichier, configuration_mapping()).demandes

    assert premiere.frequence_utilisation == "hebdomadaire"
    assert premiere.contract_type == "consumer_terms"
    assert premiere.niveau_maitrise_ti == "intermédiaire"
    assert troisieme.mode == "api"
    assert troisieme.mode_acquisition == "seao"
    assert troisieme.tool_type_override == "publique"


def test_les_oui_non_deviennent_des_booleens(tmp_path):
    document = document_reponses()
    _valeurs(document, 0, "automated_decisions")[0]["value"] = "Oui"
    chemin = ecrire_reponses(tmp_path / "oui-non.json", document)

    lot = lire_reponses(chemin, configuration_mapping())

    assert lot.demandes[0].automated_decisions is True
    assert lot.demandes[1].automated_decisions is False


def test_les_nombres_sont_convertis(fichier):
    premiere = lire_reponses(fichier, configuration_mapping()).demandes[0]

    assert premiere.nb_utilisateurs_vises == 25


def test_une_reponse_vide_sur_l_hebergement_laisse_deduire_le_mode(fichier):
    """Le mode de déploiement n'est demandé que pour le cas « sur site »."""
    premiere = lire_reponses(fichier, configuration_mapping()).demandes[0]

    assert premiere.deployment_mode == ""
    assert premiere.vers_entrees_orchestrateur().offering.deployment_mode == "public_saas"


def test_l_hebergement_sur_site_ecrase_la_deduction(tmp_path):
    document = document_reponses()
    cle = _id("deployment_mode")
    document["responses"][0]["answers"][cle] = {
        "questionId": cle,
        "textAnswers": {"answers": [{
            "value": "Oui, installé sur des serveurs de l'UQAM — "
                     "Le logiciel tourne sur nos serveurs, pas chez le fournisseur"
        }]},
    }
    chemin = ecrire_reponses(tmp_path / "sur-site.json", document)

    demande = lire_reponses(chemin, configuration_mapping()).demandes[0]

    assert demande.deployment_mode == "on_premise"
    assert demande.vers_entrees_orchestrateur().offering.deployment_mode == "on_premise"


def test_reformuler_un_titre_ne_change_pas_l_appariement(fichier):
    catalogue = formulaire().model_copy(deep=True)
    catalogue.sections[0].questions[1].intitule = "Unité (titre reformulé)"

    lot = lire_reponses(fichier, configuration_mapping(), catalogue)

    assert lot.demandes[0].unite == "Direction des services administratifs"


def test_un_question_id_inconnu_rejette_une_reponse_et_laisse_passer_les_autres(tmp_path):
    document = document_reponses()
    document["responses"][1]["answers"]["question-inconnue"] = {
        "questionId": "question-inconnue",
        "textAnswers": {"answers": [{"value": "sans importance"}]},
    }
    chemin = ecrire_reponses(tmp_path / "derive.json", document)

    lot = lire_reponses(chemin, configuration_mapping())

    assert [demande.tool_name for demande in lot.demandes] == ["ChatGPT", "Gemini"]
    assert lot.question_ids_inconnus == ["question-inconnue"]
    assert lot.rejets[0].response_id == "response-2"
    assert "question-inconnue" in lot.rejets[0].motif


def test_un_choix_invalide_rejette_une_reponse(tmp_path):
    document = document_reponses()
    _valeurs(document, 1, "urgence_percue")[0]["value"] = "Bof"
    chemin = ecrire_reponses(tmp_path / "choix.json", document)

    lot = lire_reponses(chemin, configuration_mapping())

    assert len(lot.demandes) == 2
    assert lot.rejets[0].response_id == "response-2"
    assert "hors des choix proposés" in lot.rejets[0].motif


def test_une_reponse_obligatoire_vide_ne_cite_que_le_champ(tmp_path):
    document = document_reponses()
    document["responses"][0]["answers"].pop(_id("data_free_text"))
    chemin = ecrire_reponses(tmp_path / "obligatoire.json", document)

    lot = lire_reponses(chemin, configuration_mapping())

    assert len(lot.demandes) == 2
    assert lot.rejets[0].motif == "réponse invalide ou manquante pour : data_free_text"


def test_les_motifs_ne_citent_pas_les_reponses_libres(tmp_path):
    document = copy.deepcopy(document_reponses())
    secret = "prévisions budgétaires confidentielles"
    _valeurs(document, 0, "data_free_text")[0]["value"] = secret
    _valeurs(document, 0, "nb_utilisateurs_vises")[0]["value"] = "pas un nombre"
    chemin = ecrire_reponses(tmp_path / "secret.json", document)

    lot = lire_reponses(chemin, configuration_mapping())

    assert len(lot.rejets) == 1
    assert secret not in lot.rejets[0].motif
    assert "pas un nombre" not in lot.rejets[0].motif


def test_un_fichier_absent_est_signale_clairement(tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        lire_reponses(tmp_path / "aucun.json", configuration_mapping())


def test_un_document_malforme_est_signale(tmp_path):
    chemin = ecrire_reponses(tmp_path / "invalide.json", {"responses": {}})

    with pytest.raises(FichierReponsesInvalideError, match="responses"):
        lire_reponses(chemin, configuration_mapping())
