"""Contract facts loaded from the centralized YAML configuration.

One family represents one Tavily search followed by one LLM extraction. The
``keywords`` only select relevant excerpts from long evidence; they never
decide a verdict.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FACT_FAMILIES_PATH = _PROJECT_ROOT / "configs" / "fact_families.yaml"


@dataclass(frozen=True)
class FactField:
    name: str
    allowed_values: tuple[str, ...]
    hint: str


@dataclass(frozen=True)
class FactFamily:
    name: str
    query: str
    fields: tuple[FactField, ...]
    keywords: tuple[str, ...]


class _FactFieldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    allowed_values: tuple[str, ...] = Field(min_length=1)
    hint: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allowed_values(self) -> "_FactFieldConfig":
        if len(self.allowed_values) != len(set(self.allowed_values)):
            raise ValueError(f"duplicate allowed value for field {self.name}")
        if "unknown" not in self.allowed_values:
            raise ValueError(f"field {self.name} must allow unknown")
        return self


class _FactFamilyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    query: str = Field(min_length=1)
    fields: tuple[_FactFieldConfig, ...] = Field(min_length=1)
    keywords: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_query_and_keywords(self) -> "_FactFamilyConfig":
        if "{tool}" not in self.query or "{vendor}" not in self.query:
            raise ValueError(
                f"family {self.name} query must contain {{tool}} and {{vendor}}"
            )
        for keyword in self.keywords:
            try:
                re.compile(keyword)
            except re.error as exc:
                raise ValueError(
                    f"invalid keyword regex in family {self.name}: {keyword}"
                ) from exc
        return self


class _FactFamiliesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    families: tuple[_FactFamilyConfig, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_names(self) -> "_FactFamiliesConfig":
        family_names = [family.name for family in self.families]
        if len(family_names) != len(set(family_names)):
            raise ValueError("fact family names must be unique")

        field_names = [
            field.name for family in self.families for field in family.fields
        ]
        if len(field_names) != len(set(field_names)):
            raise ValueError("fact field names must be globally unique")
        return self


def load_fact_families(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[FactFamily, ...]:
    """Load, validate and freeze the configured contract fact families."""
    environment = os.environ if env is None else env
    configured_path = path or environment.get("POLICYBOT_FACT_FAMILIES_PATH")
    config_path = Path(configured_path) if configured_path else DEFAULT_FACT_FAMILIES_PATH
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.is_file():
        raise FileNotFoundError(f"PolicyBot fact families file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"PolicyBot fact families must be a YAML mapping: {config_path}")
    configured = _FactFamiliesConfig.model_validate(raw)

    return tuple(
        FactFamily(
            name=family.name,
            query=family.query,
            fields=tuple(
                FactField(
                    name=field.name,
                    allowed_values=field.allowed_values,
                    hint=field.hint,
                )
                for field in family.fields
            ),
            keywords=family.keywords,
        )
        for family in configured.families
    )


FACT_FAMILIES: tuple[FactFamily, ...] = load_fact_families()

ALL_FACT_FIELDS: tuple[FactField, ...] = tuple(
    field for family in FACT_FAMILIES for field in family.fields
)


def family_by_name(name: str) -> FactFamily | None:
    for family in FACT_FAMILIES:
        if family.name == name:
            return family
    return None
