import pytest

from policybot.intake.formulaire import (
    FormulaireInvalideError,
    charger_formulaire,
    devis,
    formulaire,
    normaliser_intitule,
)
from policybot.intake.schema import DemandeIAG

from tests.intake.conftest import question_par_champ


def test_les_champs_de_questions_sont_uniques():
    champs = [question.champ for question in formulaire().questions]
    assert len(champs) == len(set(champs))


def test_chaque_question_alimente_un_champ_du_schema():
    champs = {question.champ for question in formulaire().questions}
    assert champs == set(DemandeIAG.model_fields)


def test_les_champs_obligatoires_du_schema_sont_demandes():
    obligatoires_schema = {
        nom for nom, champ in DemandeIAG.model_fields.items() if champ.is_required()
    }
    assert obligatoires_schema <= set(formulaire().champs_obligatoires())


def test_un_champ_inconnu_fait_echouer_le_chargement(catalogue_brut, ecrire_catalogue):
    question_par_champ(catalogue_brut, "unite")["champ"] = "champ_fantome"
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(
        FormulaireInvalideError,
        match='champ_fantome: str = ""',
    ):
        charger_formulaire(chemin)


def test_un_champ_obligatoire_non_marque_fait_echouer(catalogue_brut, ecrire_catalogue):
    question_par_champ(catalogue_brut, "data_free_text")["obligatoire"] = False
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(FormulaireInvalideError, match="data_free_text"):
        charger_formulaire(chemin)


def test_une_question_sans_champ_correspondant_fait_echouer(catalogue_brut, ecrire_catalogue):
    catalogue_brut["sections"][0]["questions"] = [
        catalogue_brut["sections"][0]["questions"][0]
    ]
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(FormulaireInvalideError, match="unite"):
        charger_formulaire(chemin)


def test_les_numeros_sont_derives_de_l_ordre_des_blocs(catalogue_brut, ecrire_catalogue):
    questions = [q for section in catalogue_brut["sections"] for q in section["questions"]]
    for question in questions:
        question.pop("numero", None)
    questions[0]["numero"] = 999

    catalogue = charger_formulaire(ecrire_catalogue(catalogue_brut))

    assert [question.numero for question in catalogue.questions] == list(
        range(1, len(catalogue.questions) + 1)
    )


def test_une_valeur_de_choix_refusee_par_le_schema_fait_echouer(
    catalogue_brut, ecrire_catalogue
):
    question_par_champ(catalogue_brut, "urgence_percue")["choix"][0]["valeur"] = "moderee"
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(FormulaireInvalideError, match="moderee"):
        charger_formulaire(chemin)


def test_deux_intitules_identiques_une_fois_normalises_font_echouer(
    catalogue_brut, ecrire_catalogue
):
    question_par_champ(catalogue_brut, "unite")["intitule"] = "  NOM DU DEMANDEUR ?  "
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(FormulaireInvalideError, match="intitulé"):
        charger_formulaire(chemin)


def test_un_type_de_question_inconnu_fait_echouer(catalogue_brut, ecrire_catalogue):
    question_par_champ(catalogue_brut, "unite")["type"] = "curseur"
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(FormulaireInvalideError, match="curseur"):
        charger_formulaire(chemin)


def test_normalisation_neutralise_casse_accents_espaces_et_ponctuation():
    assert normaliser_intitule("  Unité   administrative  ") == normaliser_intitule(
        "UNITE ADMINISTRATIVE"
    )
    assert normaliser_intitule("Comment vas-tu utiliser cet outil ?") == normaliser_intitule(
        "Comment vas-tu utiliser cet outil"
    )
    assert normaliser_intitule("Quel besoin d’affaires") == normaliser_intitule(
        "Quel besoin d'affaires"
    )


def test_traduction_d_un_libelle_de_choix_vers_la_valeur_du_schema():
    question = next(q for q in formulaire().questions if q.champ == "mode_acquisition")
    assert question.valeur_pour("Via SEAO") == "seao"
    assert question.valeur_pour("contrat_existant") == "contrat_existant"
    assert question.valeur_pour("Troc") is None


def test_devis_imprime_chaque_question_avec_son_champ():
    sortie = devis()
    for question in formulaire().questions:
        assert question.intitule in sortie
        assert f"champ  : {question.champ}" in sortie
    assert f"{len(formulaire().questions)} questions." in sortie


def test_devis_ouvre_sur_les_outils_deja_approuves():
    sortie = devis()
    approuves = formulaire().outils_approuves

    assert approuves is not None
    debut = sortie.index(approuves.titre)
    assert debut < sortie.index(formulaire().sections[0].titre)
    for ligne in approuves.consigne.strip().splitlines():
        assert ligne.strip() in sortie
    for outil in approuves.outils:
        assert f"- {outil.nom}" in sortie


def test_une_liste_d_outils_approuves_sans_consigne_fait_echouer(
    catalogue_brut, ecrire_catalogue
):
    catalogue_brut["outils_approuves"]["consigne"] = ""
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(ValueError, match="consigne"):
        charger_formulaire(chemin)


def test_une_consigne_sans_aucun_outil_fait_echouer(catalogue_brut, ecrire_catalogue):
    catalogue_brut["outils_approuves"]["outils"] = []
    chemin = ecrire_catalogue(catalogue_brut)

    with pytest.raises(ValueError, match="outils"):
        charger_formulaire(chemin)


def test_le_catalogue_reste_valide_sans_page_d_outils_approuves(
    catalogue_brut, ecrire_catalogue
):
    catalogue_brut.pop("outils_approuves")
    chemin = ecrire_catalogue(catalogue_brut)
    catalogue = charger_formulaire(chemin)

    assert catalogue.outils_approuves is None
    assert "Outils déjà approuvés" not in devis(catalogue)
