from policybot.models import IagType, QuestionSpec, QuestionOption
from policybot.classify.tool_registry import lookup_tool


def classify_tool_type(name: str) -> IagType | None:
    entry = lookup_tool(name)
    return entry["iag_type"] if entry else None


def tool_type_question() -> QuestionSpec:
    return QuestionSpec(
        id="tool_type",
        header="Type d'outil",
        question="Quel type d'outil d'IA générative est-ce ?",
        multi_select=False,
        allow_other=False,
        options=[
            QuestionOption(label="IAG publique",
                           description="Ex. ChatGPT, Claude.ai, Perplexity"),
            QuestionOption(label="IAG circuit fermé",
                           description="Ex. Microsoft Copilot Entreprise"),
            QuestionOption(label="IAG souveraine",
                           description="Hébergée au Québec"),
            QuestionOption(label="IAG gouvernementale",
                           description="Hébergée par l'UQAM / le gouvernement"),
        ],
    )
