from __future__ import annotations
from typing import Literal
from policybot.llm.provider import LLMProvider
from policybot.models import QuestionSpec, QuestionOption, IagType

IAG_TYPE_LABELS: dict[str, str] = {
    "publique": "IAG publique",
    "circuit_ferme": "IAG circuit fermé",
    "souveraine": "IAG souveraine",
    "gouvernementale": "IAG gouvernementale",
}
LABEL_TO_IAG_TYPE: dict[str, str] = {v: k for k, v in IAG_TYPE_LABELS.items()}

_TOOL_TYPE_SYSTEM = (
    "Tu classes un outil d'IA générative nommé par un employé, parmi 4 "
    "catégories de gouvernance : 'publique' (accessible à tous, ex. ChatGPT, "
    "Claude.ai), 'circuit_ferme' (offre entreprise avec contrat, ex. Copilot "
    "Entreprise), 'souveraine' (hébergée au Québec), 'gouvernementale' "
    "(hébergée par l'UQAM ou le gouvernement). Réponds en JSON avec les clés "
    "iag_type_guess (une des 4 valeurs exactes ci-dessus) et confidence (0-1)."
)

_MODE_SYSTEM = (
    "Tu déduis si un employé va utiliser un outil d'IA générative en tapant "
    "des messages directement ('prompt') ou via une intégration technique/API "
    "dans un autre système ('api'), à partir de sa description d'usage en "
    "langage clair. Réponds en JSON avec les clés mode_guess ('prompt' ou "
    "'api') et confidence (0-1)."
)

_SUGGEST_SYSTEM_TEMPLATE = (
    "Un employé répond à la question suivante dans un formulaire : \"{question}\". "
    "Les choix déjà proposés sont : {existing}. L'employé a écrit un texte libre "
    "qui ne correspond à aucun choix existant : \"{free_text}\". Propose entre 2 "
    "et 4 nouveaux choix courts et précis, adaptés à ce texte, qui ne répètent "
    "pas les choix déjà proposés. Réponds en JSON avec la clé options : une "
    "liste d'objets avec les clés label et description."
)


def guess_tool_type(name: str, llm: LLMProvider) -> IagType | None:
    result = llm.complete_json(_TOOL_TYPE_SYSTEM, name)
    guess = result.get("iag_type_guess")
    return guess if guess in IAG_TYPE_LABELS else None


def guess_mode(description: str, llm: LLMProvider) -> Literal["prompt", "api"]:
    result = llm.complete_json(_MODE_SYSTEM, description)
    guess = result.get("mode_guess")
    return guess if guess in ("prompt", "api") else "prompt"


def suggest_options(question: QuestionSpec, free_text: str, llm: LLMProvider) -> list[QuestionOption]:
    existing_labels = {opt.label for opt in question.options}
    system = _SUGGEST_SYSTEM_TEMPLATE.format(
        question=question.question,
        existing=", ".join(existing_labels) or "aucun",
        free_text=free_text,
    )
    result = llm.complete_json(system, free_text)
    raw_options = result.get("options", [])
    return [
        QuestionOption(label=o["label"], description=o.get("description", ""))
        for o in raw_options
        if o.get("label") and o["label"] not in existing_labels
    ]
