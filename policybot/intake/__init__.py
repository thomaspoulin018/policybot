"""Contrat d'entrée de PolicyBot : le formulaire, son schéma et son lecteur."""

from policybot.intake.formulaire import (
    CatalogueFormulaire,
    QuestionFormulaire,
    SectionFormulaire,
    charger_formulaire,
    devis,
    formulaire,
)
from policybot.intake.schema import DemandeIAG

__all__ = [
    "CatalogueFormulaire",
    "DemandeIAG",
    "QuestionFormulaire",
    "SectionFormulaire",
    "charger_formulaire",
    "devis",
    "formulaire",
]
