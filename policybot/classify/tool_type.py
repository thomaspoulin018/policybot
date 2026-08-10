from policybot.models import IagType
from policybot.classify.tool_registry import lookup_tool


def classify_tool_type(name: str) -> IagType | None:
    entry = lookup_tool(name)
    return entry["iag_type"] if entry else None
