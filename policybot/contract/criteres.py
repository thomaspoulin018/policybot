"""Chargement et validation de la recherche Exa, une configuration par critère."""
from __future__ import annotations

import os
from pathlib import Path
from string import Formatter
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA


EXA_SEARCH_TYPES = {
    "auto", "fast", "neural", "instant", "deep-lite", "deep", "deep-reasoning",
}
QUERY_FIELDS = {
    "tool", "vendor", "plan", "deployment_mode", "contract_type",
    "contract_version", "jurisdiction",
}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULTS_PATH = PROJECT_ROOT / "configs" / "recherche_defaults.yaml"
CRITERIA_DIR = PROJECT_ROOT / "configs" / "recherche_criteres"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class ExaCriterionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    type: str = "neural"
    num_results: int = Field(default=5, gt=0)
    include_domains: list[str] = Field(default_factory=list)
    contents: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_query(self):
        if self.type not in EXA_SEARCH_TYPES:
            raise ValueError(f"unsupported Exa search type: {self.type}")
        fields = {
            name for _, name, _, _ in Formatter().parse(self.query) if name
        }
        unknown = fields - QUERY_FIELDS
        if unknown:
            raise ValueError(f"unknown query placeholders: {sorted(unknown)}")
        return self


class CriterionSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2]
    id: str = Field(pattern=r"^[AB]\d{2}$")
    partie: Literal["A", "B"]
    category: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    question: str = Field(min_length=1)
    exa: ExaCriterionConfig

    def render_query(self, **values: str) -> str:
        rendered = self.exa.query.format(**{
            key: values.get(key, "") for key in QUERY_FIELDS
        })
        return " ".join(rendered.split())


class SearchDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2]
    exa: dict[str, Any]
    budget: dict[str, Any]
    schemas: dict[str, dict[str, Any]]
    prompts: dict[str, str]
    max_citations_per_criterion: int = Field(default=3, gt=0)
    observation_template: str
    citation_line_template: str
    citation_link_template: str


def _read_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"la configuration doit être un objet YAML: {path}")
    return raw


def load_criterion_searches(
    criteria_dir: str | Path | None = None,
    defaults_path: str | Path | None = None,
) -> tuple[SearchDefaults, tuple[CriterionSearchConfig, ...]]:
    defaults_file = Path(
        defaults_path or os.environ.get("POLICYBOT_SEARCH_DEFAULTS_PATH") or DEFAULTS_PATH
    )
    directory = Path(
        criteria_dir or os.environ.get("POLICYBOT_CRITERIA_DIR") or CRITERIA_DIR
    )
    defaults_raw = _read_yaml(defaults_file)
    defaults = SearchDefaults.model_validate(defaults_raw)
    shared_exa = defaults_raw["exa"]
    searches = []
    for path in sorted(directory.glob("*.yaml")):
        raw = _read_yaml(path)
        raw["exa"] = _deep_merge(shared_exa, raw.get("exa") or {})
        searches.append(CriterionSearchConfig.model_validate(raw))

    ids = [item.id for item in searches]
    if len(ids) != len(set(ids)):
        raise ValueError("les identifiants de critères doivent être uniques")
    expected_a = {(category, criterion) for category, criterion, _ in ARP_CRITERIA}
    usage_by_name = {criterion: (category, criterion) for category, criterion, _ in USAGE_CRITERIA}
    expected_b = {
        usage_by_name[name] for name in (
            "Utilisation de données pour entraînement",
            "Compatibilité avec la LAI/PRP",
            "Biais algorithmiques",
            "Image et réputation institutionnelle",
        )
    }
    actual_a = {(item.category, item.criterion) for item in searches if item.partie == "A"}
    actual_b = {(item.category, item.criterion) for item in searches if item.partie == "B"}
    if actual_a != expected_a:
        raise ValueError(f"les critères A ne correspondent pas à ARP_CRITERIA: {actual_a ^ expected_a}")
    if actual_b != expected_b:
        raise ValueError(f"les critères B ne correspondent pas à USAGE_CRITERIA: {actual_b ^ expected_b}")
    if len(searches) != 17:
        raise ValueError(f"17 configurations attendues, {len(searches)} trouvées")
    return defaults, tuple(searches)


SEARCH_DEFAULTS, CRITERIA_SEARCHES = load_criterion_searches()
CRITERIA_SEARCH_BY_ID = {item.id: item for item in CRITERIA_SEARCHES}
