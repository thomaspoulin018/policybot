from __future__ import annotations
from typing import Literal
from policybot.llm.provider import LLMProvider
from policybot.models import QuestionSpec, QuestionOption, IagType
from policybot.prompts import get_prompt

IAG_TYPE_LABELS: dict[str, str] = {
    "publique": "IAG publique",
    "circuit_ferme": "IAG circuit fermé",
    "souveraine": "IAG souveraine",
    "gouvernementale": "IAG gouvernementale",
}
LABEL_TO_IAG_TYPE: dict[str, str] = {v: k for k, v in IAG_TYPE_LABELS.items()}

def guess_tool_type(name: str, llm: LLMProvider) -> IagType | None:
    prompt = get_prompt("tool_type_detection")
    result = llm.complete_json(
        prompt.render_system(), prompt.render_user(tool_name=name),
        task="tool_type_detection",
    )
    guess = result.get("iag_type_guess")
    return guess if guess in IAG_TYPE_LABELS else None


def guess_mode(description: str, llm: LLMProvider) -> Literal["prompt", "api"]:
    prompt = get_prompt("mode_detection")
    result = llm.complete_json(
        prompt.render_system(), prompt.render_user(description=description),
        task="mode_detection",
    )
    guess = result.get("mode_guess")
    return guess if guess in ("prompt", "api") else "prompt"


def suggest_options(question: QuestionSpec, free_text: str, llm: LLMProvider) -> list[QuestionOption]:
    existing_labels = {opt.label for opt in question.options}
    prompt = get_prompt("form_suggestions")
    values = dict(
        question=question.question,
        existing=", ".join(existing_labels) or "aucun",
        free_text=free_text,
    )
    result = llm.complete_json(
        prompt.render_system(**values), prompt.render_user(**values),
        task="form_suggestions",
    )
    raw_options = result.get("options", [])
    return [
        QuestionOption(label=o["label"], description=o.get("description", ""))
        for o in raw_options
        if o.get("label") and o["label"] not in existing_labels
    ]
