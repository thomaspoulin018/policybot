"""Traduction pure du catalogue PolicyBot vers les requêtes Google Forms."""
from __future__ import annotations

from policybot.intake.formulaire import CatalogueFormulaire, QuestionFormulaire


def libelle_option(question: QuestionFormulaire, index: int) -> str:
    choix = question.choix[index]
    if choix.description:
        return f"{choix.libelle} — {choix.description}"
    return choix.libelle


def item_question(question: QuestionFormulaire) -> dict:
    """Rend l'item correspondant à l'un des sept types du catalogue."""
    if question.type in {"texte", "texte_long", "nombre"}:
        kind = {"textQuestion": {"paragraph": question.type == "texte_long"}}
    elif question.type == "date":
        kind = {"dateQuestion": {"includeYear": True, "includeTime": False}}
    elif question.type in {"choix", "choix_multiple"}:
        kind = {
            "choiceQuestion": {
                "type": "CHECKBOX" if question.type == "choix_multiple" else "RADIO",
                "options": [
                    {"value": libelle_option(question, index)}
                    for index in range(len(question.choix))
                ],
                "shuffle": False,
            }
        }
    elif question.type == "oui_non":
        kind = {
            "choiceQuestion": {
                "type": "RADIO",
                "options": [{"value": "Oui"}, {"value": "Non"}],
                "shuffle": False,
            }
        }
    else:  # Le catalogue validé rend cette branche impossible.
        raise ValueError(f"Type de question Google Forms inconnu : {question.type}")
    item = {
        "title": question.intitule,
        "questionItem": {
            "question": {"required": question.obligatoire, **kind}
        },
    }
    if question.aide:
        item["description"] = question.aide
    return item


def requetes_formulaire(catalogue: CatalogueFormulaire) -> list[dict]:
    """Construit un lot ordonné, directement envoyable à batchUpdate."""
    requetes: list[dict] = [
        {
            "updateFormInfo": {
                "info": {
                    "title": catalogue.titre,
                    "description": catalogue.introduction,
                },
                "updateMask": "title,description",
            }
        }
    ]
    index = 0

    def ajouter_item(item: dict) -> None:
        nonlocal index
        requetes.append({"createItem": {"item": item, "location": {"index": index}}})
        index += 1

    approuves = catalogue.outils_approuves
    if approuves is not None:
        outils = "\n".join(
            f"• {outil.nom}" + (f" — {outil.precision}" if outil.precision else "")
            for outil in approuves.outils
        )
        description = approuves.consigne.rstrip()
        if outils:
            description += "\n\n" + outils
        ajouter_item(
            {
                "title": approuves.titre,
                "description": description,
                "textItem": {},
            }
        )

    for section in catalogue.sections:
        page = {"title": section.titre, "pageBreakItem": {}}
        if section.aide:
            page["description"] = section.aide
        ajouter_item(page)
        for question in section.questions:
            ajouter_item(item_question(question))
    return requetes
