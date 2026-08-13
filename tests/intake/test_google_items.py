import json

from policybot.intake.formulaire import QuestionFormulaire, formulaire
from policybot.intake.google_items import item_question, requetes_formulaire


def _question(champ: str):
    return next(question for question in formulaire().questions if question.champ == champ)


def test_le_catalogue_produit_toutes_les_questions_obligatoires_sans_autre():
    requetes = requetes_formulaire(formulaire())
    items = [
        requete["createItem"]["item"]
        for requete in requetes
        if "createItem" in requete
    ]
    questions = [item for item in items if "questionItem" in item]

    assert len(questions) == len(formulaire().questions)
    assert sum(
        item["questionItem"]["question"]["required"] for item in questions
    ) == len(formulaire().champs_obligatoires())
    assert "isOther" not in json.dumps(requetes)


def test_les_sept_types_produisent_les_structures_google_attendues():
    assert item_question(_question("demandeur"))["questionItem"]["question"][
        "textQuestion"
    ] == {"paragraph": False}
    assert item_question(_question("fonctions_roles"))["questionItem"]["question"][
        "textQuestion"
    ] == {"paragraph": True}
    assert item_question(_question("nb_utilisateurs"))["questionItem"]["question"][
        "textQuestion"
    ] == {"paragraph": False}
    # Le catalogue ne pose plus aucune question de type date, mais le type
    # reste supporté : on le vérifie sur une question construite ici.
    question_date = QuestionFormulaire(
        intitule="Date d'effet", type="date", champ="contract_version"
    )
    assert item_question(question_date)["questionItem"]["question"][
        "dateQuestion"
    ] == {"includeYear": True, "includeTime": False}
    assert item_question(_question("mode"))["questionItem"]["question"][
        "choiceQuestion"
    ]["type"] == "RADIO"
    assert item_question(_question("data_checked"))["questionItem"]["question"][
        "choiceQuestion"
    ]["type"] == "CHECKBOX"
    oui_non = item_question(_question("automated_decisions"))["questionItem"][
        "question"
    ]["choiceQuestion"]
    assert oui_non == {
        "type": "RADIO",
        "options": [{"value": "Oui"}, {"value": "Non"}],
        "shuffle": False,
    }


def test_le_lot_commence_par_l_info_puis_la_page_de_la_premiere_section():
    catalogue = formulaire()
    requetes = requetes_formulaire(catalogue)

    assert requetes[0]["updateFormInfo"]["info"]["description"] == catalogue.introduction
    assert requetes[1]["createItem"]["item"]["textItem"] == {}
    assert requetes[2]["createItem"]["item"]["pageBreakItem"] == {}
    assert requetes[2]["createItem"]["item"]["title"] == catalogue.sections[0].titre


def test_la_description_d_un_choix_est_concatenee_au_libelle():
    question = _question("formation_iag_recue")
    options = item_question(question)["questionItem"]["question"]["choiceQuestion"][
        "options"
    ]

    assert options[0]["value"].startswith("Aucune — Aucune formation")
