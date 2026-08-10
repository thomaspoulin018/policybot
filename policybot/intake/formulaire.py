"""Le catalogue de questions, validé contre `DemandeIAG` à l'import.

Même principe que `contract/criteres.py` pour les 17 critères : le fichier
`configs/formulaire.yaml` et le schéma se contrôlent mutuellement. Une
question qui pointe vers un champ inexistant, un champ obligatoire que le
formulaire ne demande pas, ou une valeur de choix que le schéma refuse font
échouer le chargement — jamais une demande mal remplie plus tard.
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import types
import typing
import unicodedata

import yaml
from pydantic import BaseModel, ConfigDict, Field

from policybot.intake.schema import DemandeIAG


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FORMULAIRE_PATH = _PROJECT_ROOT / "configs" / "formulaire.yaml"

TYPES_QUESTION = (
    "texte",
    "texte_long",
    "nombre",
    "date",
    "choix",
    "choix_multiple",
    "oui_non",
)

# Colonnes que Microsoft Forms ajoute d'office à tout export.
COLONNES_TECHNIQUES: tuple[str, ...] = (
    "ID",
    "Heure de début",
    "Heure de fin",
    "Adresse de courriel",
    "Nom",
    "Heure de la dernière modification",
    "Start time",
    "Completion time",
    "Email",
    "Name",
    "Last modified time",
)

_PONCTUATION_FINALE = " \t.:;!?…*"


class FormulaireInvalideError(ValueError):
    """Le catalogue et le schéma ne se recouvrent pas."""


def normaliser_intitule(valeur: str) -> str:
    """Réduit un intitulé à sa forme comparable.

    Casse, accents, apostrophes typographiques, espaces multiples et
    ponctuation finale sont neutralisés : c'est cette forme qui apparie une
    colonne d'export avec une question du catalogue.
    """
    texte = unicodedata.normalize("NFKD", valeur or "")
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    texte = texte.replace("’", "'").replace("ʼ", "'")
    texte = texte.replace(" ", " ").replace(" ", " ")
    texte = re.sub(r"\s+", " ", texte).strip()
    return texte.strip(_PONCTUATION_FINALE).casefold()


class ChoixFormulaire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    libelle: str = Field(min_length=1)
    valeur: str = Field(min_length=1)
    description: str = ""


class QuestionFormulaire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero: int = Field(gt=0)
    intitule: str = Field(min_length=1)
    type: str
    obligatoire: bool = False
    champ: str = Field(min_length=1)
    aide: str = ""
    choix: list[ChoixFormulaire] = Field(default_factory=list)

    @property
    def intitule_normalise(self) -> str:
        return normaliser_intitule(self.intitule)

    def valeur_pour(self, libelle: str) -> str | None:
        """Traduit un libellé de choix en valeur de schéma."""
        cible = normaliser_intitule(libelle)
        for choix in self.choix:
            if normaliser_intitule(choix.libelle) == cible:
                return choix.valeur
            if normaliser_intitule(choix.valeur) == cible:
                return choix.valeur
        return None


class SectionFormulaire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titre: str = Field(min_length=1)
    aide: str = ""
    questions: list[QuestionFormulaire] = Field(min_length=1)


class CatalogueFormulaire(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: typing.Literal[1] = 1
    titre: str = Field(min_length=1)
    introduction: str = ""
    sections: list[SectionFormulaire] = Field(min_length=1)

    @property
    def questions(self) -> list[QuestionFormulaire]:
        return [question for section in self.sections for question in section.questions]

    def par_intitule(self) -> dict[str, QuestionFormulaire]:
        return {question.intitule_normalise: question for question in self.questions}

    def champs_obligatoires(self) -> tuple[str, ...]:
        return tuple(q.champ for q in self.questions if q.obligatoire)


def _deplier(annotation) -> tuple[set, tuple]:
    """Rend les types de base d'une annotation et ses valeurs littérales."""
    bases: set = set()
    litteraux: list = []
    a_traiter = [annotation]
    while a_traiter:
        courant = a_traiter.pop()
        origine = typing.get_origin(courant)
        if origine in (typing.Union, types.UnionType):
            a_traiter.extend(typing.get_args(courant))
        elif origine is typing.Literal:
            valeurs = typing.get_args(courant)
            litteraux.extend(valeurs)
            bases.update(type(valeur) for valeur in valeurs)
        elif origine is list:
            bases.add(list)
        elif courant is type(None):
            continue
        else:
            bases.add(courant)
    return bases, tuple(litteraux)


_TYPE_ATTENDU = {
    "texte": str,
    "texte_long": str,
    "choix": str,
    "choix_multiple": list,
    "oui_non": bool,
    "nombre": int,
}


def _valider(catalogue: CatalogueFormulaire, chemin: Path) -> CatalogueFormulaire:
    from datetime import date as _date

    champs_schema = DemandeIAG.model_fields
    questions = catalogue.questions

    numeros = [q.numero for q in questions]
    if numeros != list(range(1, len(numeros) + 1)):
        raise FormulaireInvalideError(
            f"{chemin} : les numéros de questions doivent être consécutifs à partir de 1."
        )

    vus: dict[str, QuestionFormulaire] = {}
    for question in questions:
        if question.type not in TYPES_QUESTION:
            raise FormulaireInvalideError(
                f"{chemin} : type « {question.type} » inconnu pour la question "
                f"{question.numero} (attendus : {', '.join(TYPES_QUESTION)})."
            )
        if question.intitule_normalise in vus:
            raise FormulaireInvalideError(
                f"{chemin} : deux questions portent le même intitulé une fois "
                f"normalisé — « {question.intitule} »."
            )
        vus[question.intitule_normalise] = question

        if question.champ not in champs_schema:
            raise FormulaireInvalideError(
                f"{chemin} : la question {question.numero} alimente le champ "
                f"« {question.champ} », absent de DemandeIAG."
            )
        if question.type in ("choix", "choix_multiple") and not question.choix:
            raise FormulaireInvalideError(
                f"{chemin} : la question {question.numero} est de type "
                f"« {question.type} » mais ne propose aucun choix."
            )

        bases, litteraux = _deplier(champs_schema[question.champ].annotation)
        attendu = _TYPE_ATTENDU.get(question.type, _date)
        if attendu not in bases:
            raise FormulaireInvalideError(
                f"{chemin} : la question {question.numero} est de type "
                f"« {question.type} » mais le champ « {question.champ} » "
                f"n'accepte pas {attendu.__name__}."
            )
        if litteraux:
            for choix in question.choix:
                if choix.valeur not in litteraux:
                    raise FormulaireInvalideError(
                        f"{chemin} : la valeur « {choix.valeur} » de la question "
                        f"{question.numero} est refusée par le champ "
                        f"« {question.champ} »."
                    )

    champs_couverts = {q.champ for q in questions}
    manquants = [nom for nom in champs_schema if nom not in champs_couverts]
    if manquants:
        raise FormulaireInvalideError(
            f"{chemin} : aucun formulaire ne remplit " + ", ".join(manquants) + "."
        )

    obligatoires_schema = {
        nom for nom, champ in champs_schema.items() if champ.is_required()
    }
    obligatoires_formulaire = set(catalogue.champs_obligatoires())
    oublis = sorted(obligatoires_schema - obligatoires_formulaire)
    if oublis:
        raise FormulaireInvalideError(
            f"{chemin} : champs obligatoires de DemandeIAG non marqués obligatoires "
            "dans le formulaire — " + ", ".join(oublis) + "."
        )
    return catalogue


def charger_formulaire(path: str | Path | None = None) -> CatalogueFormulaire:
    """Charge et valide le catalogue de questions."""
    configure = path or os.environ.get("POLICYBOT_FORMULAIRE_PATH")
    chemin = Path(configure) if configure else DEFAULT_FORMULAIRE_PATH
    if not chemin.is_absolute():
        chemin = Path.cwd() / chemin
    if not chemin.is_file():
        raise FileNotFoundError(f"Catalogue de formulaire introuvable : {chemin}")
    raw = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise FormulaireInvalideError(
            f"Le catalogue de formulaire doit être un mappage YAML : {chemin}"
        )
    return _valider(CatalogueFormulaire.model_validate(raw), chemin)


@lru_cache(maxsize=1)
def formulaire() -> CatalogueFormulaire:
    """Le catalogue par défaut, chargé une seule fois par processus."""
    return charger_formulaire()


def devis(catalogue: CatalogueFormulaire | None = None) -> str:
    """Le formulaire à recopier dans Microsoft Forms, question par question."""
    catalogue = catalogue or formulaire()
    lignes: list[str] = [catalogue.titre, "=" * len(catalogue.titre), ""]
    if catalogue.introduction:
        lignes.extend(catalogue.introduction.rstrip().splitlines())
        lignes.append("")
    for section in catalogue.sections:
        lignes.append(section.titre)
        lignes.append("-" * len(section.titre))
        if section.aide:
            for ligne in section.aide.rstrip().splitlines():
                lignes.append(f"  {ligne}" if ligne else "")
        lignes.append("")
        for question in section.questions:
            marque = " [obligatoire]" if question.obligatoire else ""
            lignes.append(f"{question.numero:>2}. {question.intitule}{marque}")
            lignes.append(f"    type   : {question.type}")
            lignes.append(f"    champ  : {question.champ}")
            for choix in question.choix:
                suffixe = f" — {choix.description}" if choix.description else ""
                lignes.append(f"    choix  : {choix.libelle}{suffixe}")
            for index, ligne in enumerate(question.aide.rstrip().splitlines()):
                etiquette = "    aide   : " if index == 0 else "             "
                lignes.append(f"{etiquette}{ligne}" if ligne else "")
            lignes.append("")
    lignes.append(f"{len(catalogue.questions)} questions.")
    return "\n".join(lignes)
