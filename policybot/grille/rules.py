from __future__ import annotations
import os
import yaml
from pydantic import BaseModel, Field

RISK_ORDER = {"Faible": 0, "Modéré": 1, "Élevé": 2, "Critique": 3}
_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "grille.yaml")


class Rule(BaseModel):
    id: str
    when: dict[str, list[str]] = Field(default_factory=dict)
    then: dict = Field(default_factory=dict)


def load_rules(path: str | None = None) -> list[Rule]:
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return [Rule(**item) for item in raw]


def evaluate_rules(facts: dict, rules: list[Rule]) -> list[Rule]:
    """Return rules whose every `when` clause matches `facts` (file order)."""
    triggered = []
    for rule in rules:
        if all(str(facts.get(key)) in allowed for key, allowed in rule.when.items()):
            triggered.append(rule)
    return triggered


def highest_risk(levels: list[str]) -> str:
    if not levels:
        return "Faible"
    return max(levels, key=lambda lv: RISK_ORDER.get(lv, 0))
