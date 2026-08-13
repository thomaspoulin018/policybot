"""Lecture hors ligne des réponses JSON de Google Forms.

Une réponse illisible ne fait pas tomber le lot : elle est rejetée avec son
identifiant et les autres passent. L'appariement repose exclusivement sur le
questionId stable, jamais sur le titre affiché dans le formulaire.
"""
from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import re

from pydantic import BaseModel, Field, ValidationError

from policybot.intake.formulaire import (
    CatalogueFormulaire,
    QuestionFormulaire,
    formulaire,
)
from policybot.intake.google_forms import DEFAULT_MAPPING_PATH, charger_configuration
from policybot.intake.schema import DemandeIAG


_VRAI = {"oui", "yes", "true", "vrai", "1", "x"}
_FAUX = {"non", "no", "false", "faux", "0", ""}
_FORMATS_DATE = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")


class ReponseIllisibleError(ValueError):
    """Une réponse ne peut pas être traduite vers son champ de destination."""


class FichierReponsesInvalideError(ValueError):
    """Le document téléchargé n'a pas la structure de l'API Google Forms."""


class RejetDemande(BaseModel):
    response_id: str
    motif: str


class LotReponses(BaseModel):
    """Le résultat d'une lecture : demandes valides et rejets motivés."""

    demandes: list[DemandeIAG] = Field(default_factory=list)
    rejets: list[RejetDemande] = Field(default_factory=list)
    question_ids_inconnus: list[str] = Field(default_factory=list)
    reponses_lues: int = 0


def _chaine(valeur: object) -> str:
    return "" if valeur is None else str(valeur).strip()


def _entier(valeur: object, question: QuestionFormulaire) -> int | None:
    brut = _chaine(valeur)
    if not brut:
        return None
    trouve = re.search(r"-?\d+", brut)
    if trouve is None:
        raise ReponseIllisibleError(
            f"question {question.numero} : un nombre était attendu."
        )
    return int(trouve.group())


def _date(valeur: object, question: QuestionFormulaire) -> date | None:
    brut = _chaine(valeur)
    if not brut:
        return None
    for format_ in _FORMATS_DATE:
        try:
            return datetime.strptime(brut, format_).date()
        except ValueError:
            continue
    raise ReponseIllisibleError(
        f"question {question.numero} : date illisible (formats acceptés : "
        + ", ".join(_FORMATS_DATE)
        + ")."
    )


def _booleen(valeur: object, question: QuestionFormulaire) -> bool:
    brut = _chaine(valeur).casefold()
    if brut in _VRAI:
        return True
    if brut in _FAUX:
        return False
    traduit = question.valeur_pour(brut)
    if traduit is not None and traduit.casefold() in _VRAI:
        return True
    if traduit is not None and traduit.casefold() in _FAUX:
        return False
    raise ReponseIllisibleError(
        f"question {question.numero} : réponse hors des choix oui / non."
    )


def _choix(valeur: object, question: QuestionFormulaire) -> str | None:
    brut = _chaine(valeur)
    if not brut:
        return None
    traduit = question.valeur_pour(brut)
    if traduit is None:
        raise ReponseIllisibleError(
            f"question {question.numero} : réponse hors des choix proposés."
        )
    return traduit


def _valeurs_textuelles(reponse: object, question: QuestionFormulaire) -> list[str]:
    if not isinstance(reponse, dict):
        raise ReponseIllisibleError(
            f"question {question.numero} : structure de réponse invalide."
        )
    text_answers = reponse.get("textAnswers", {})
    answers = text_answers.get("answers", []) if isinstance(text_answers, dict) else []
    if not isinstance(answers, list):
        raise ReponseIllisibleError(
            f"question {question.numero} : structure textAnswers invalide."
        )
    valeurs: list[str] = []
    for answer in answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("value"), str):
            raise ReponseIllisibleError(
                f"question {question.numero} : valeur de réponse invalide."
            )
        valeurs.append(answer["value"])
    return valeurs


def _valeur_pour(question: QuestionFormulaire, valeurs: list[str]):
    if question.type == "choix_multiple":
        retenus: list[str] = []
        for valeur in valeurs:
            traduit = question.valeur_pour(valeur)
            if traduit is None:
                raise ReponseIllisibleError(
                    f"question {question.numero} : réponse hors des choix proposés."
                )
            retenus.append(traduit)
        return retenus
    if len(valeurs) > 1:
        raise ReponseIllisibleError(
            f"question {question.numero} : plusieurs valeurs reçues pour une réponse unique."
        )
    brut = valeurs[0] if valeurs else ""
    if question.type in ("texte", "texte_long"):
        return brut.strip()
    if question.type == "nombre":
        return _entier(brut, question)
    if question.type == "date":
        return _date(brut, question)
    if question.type == "oui_non":
        return _booleen(brut, question)
    return _choix(brut, question)


def _charger_mapping(mapping: dict | str | Path | None) -> dict[str, str]:
    if mapping is None:
        mapping = charger_configuration(DEFAULT_MAPPING_PATH)["questions"]
    elif isinstance(mapping, (str, Path)):
        mapping = charger_configuration(mapping)["questions"]
    elif "questions" in mapping:
        mapping = mapping["questions"]
    if not isinstance(mapping, dict) or not all(
        isinstance(cle, str) and isinstance(valeur, str)
        for cle, valeur in mapping.items()
    ):
        raise FichierReponsesInvalideError(
            "Le mapping doit associer chaque questionId à un champ de DemandeIAG."
        )
    return mapping


def lire_reponses(
    chemin: str | Path,
    mapping: dict | str | Path | None = None,
    catalogue: CatalogueFormulaire | None = None,
) -> LotReponses:
    """Traduit un document responses.list en demandes et rejets motivés."""
    catalogue = catalogue or formulaire()
    mapping_questions = _charger_mapping(mapping)
    path = Path(chemin)
    if not path.is_file():
        raise FileNotFoundError(f"Fichier de réponses Google Forms introuvable : {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as erreur:
        raise FichierReponsesInvalideError(
            f"Fichier de réponses Google Forms invalide ({path}) : {erreur}"
        ) from erreur
    if not isinstance(document, dict) or not isinstance(document.get("responses", []), list):
        raise FichierReponsesInvalideError(
            "Le document doit être un objet JSON contenant une liste « responses »."
        )

    questions_par_champ = {question.champ: question for question in catalogue.questions}
    lot = LotReponses()
    inconnus_lot: set[str] = set()
    for index, reponse in enumerate(document.get("responses", []), start=1):
        lot.reponses_lues += 1
        if not isinstance(reponse, dict):
            lot.rejets.append(
                RejetDemande(
                    response_id=f"réponse-{index}",
                    motif="structure de réponse invalide",
                )
            )
            continue
        response_id = reponse.get("responseId")
        if not isinstance(response_id, str) or not response_id:
            response_id = f"réponse-{index}"
        answers = reponse.get("answers", {})
        if not isinstance(answers, dict):
            lot.rejets.append(
                RejetDemande(response_id=response_id, motif="structure answers invalide")
            )
            continue

        ids_inconnus = sorted(set(answers) - set(mapping_questions))
        if ids_inconnus:
            inconnus_lot.update(ids_inconnus)
            lot.rejets.append(
                RejetDemande(
                    response_id=response_id,
                    motif="questionId absent du mapping : " + ", ".join(ids_inconnus),
                )
            )
            continue

        valeurs: dict[str, object] = {}
        motif: str | None = None
        for question_id, answer in answers.items():
            champ = mapping_questions[question_id]
            question = questions_par_champ.get(champ)
            if question is None:
                motif = f"mapping invalide : champ inconnu « {champ} »"
                break
            try:
                textes = _valeurs_textuelles(answer, question)
                valeurs[champ] = _valeur_pour(question, textes)
            except ReponseIllisibleError as erreur:
                motif = str(erreur)
                break
        if motif is not None:
            lot.rejets.append(RejetDemande(response_id=response_id, motif=motif))
            continue
        valeurs = {nom: valeur for nom, valeur in valeurs.items() if valeur is not None}
        try:
            lot.demandes.append(DemandeIAG.model_validate(valeurs))
        except ValidationError as erreur:
            champs = ", ".join(
                dict.fromkeys(
                    str(detail["loc"][0])
                    for detail in erreur.errors()
                    if detail.get("loc")
                )
            )
            lot.rejets.append(
                RejetDemande(
                    response_id=response_id,
                    motif=f"réponse invalide ou manquante pour : {champs}",
                )
            )
    lot.question_ids_inconnus = sorted(inconnus_lot)
    return lot
