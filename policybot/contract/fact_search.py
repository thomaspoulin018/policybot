"""Definitions and validation for Exa contract-fact searches.

One YAML file describes one fact.  Keeping the search prompt, allowed values
and selection policy together makes each observation reviewable without an
additional PolicyBot LLM stage.
"""
from __future__ import annotations

import os
import string
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from policybot.models import ContractFacts


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FACT_SEARCH_DIR = _PROJECT_ROOT / "configs" / "recherche_des_faits"

_CONTRACT_FACT_METADATA = {
    "source_url", "fetched_at", "snapshot_ref", "extraction_confidence",
    "evidence", "sources",
}
CONTRACT_FACT_NAMES = tuple(
    name for name in ContractFacts.model_fields if name not in _CONTRACT_FACT_METADATA
)
_ALLOWED_PLACEHOLDERS = frozenset({
    "tool", "vendor", "plan", "deployment_mode", "contract_type",
    "contract_version", "jurisdiction",
})
_REQUIRED_QUERY_PLACEHOLDERS = frozenset({
    "tool", "vendor", "plan", "deployment_mode", "contract_type",
    "contract_version",
})
EXA_SEARCH_TYPES = frozenset({"auto", "neural", "keyword", "deep"})


def _placeholders(template: str, *, context: str) -> frozenset[str]:
    """Return and validate simple named placeholders in a YAML template."""
    found: set[str] = set()
    for _, field_name, format_spec, conversion in string.Formatter().parse(template):
        if field_name is None:
            continue
        if format_spec or conversion or not field_name.isidentifier():
            raise ValueError(f"{context} has an invalid placeholder: {field_name!r}")
        if field_name not in _ALLOWED_PLACEHOLDERS:
            raise ValueError(f"{context} has an unsupported placeholder: {field_name}")
        found.add(field_name)
    return frozenset(found)


class ExaTextConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_characters: int = Field(gt=0, le=50_000)


class ExaHighlightsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    num_sentences: int = Field(gt=0, le=10)


class ExaSummaryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    query: str = Field(min_length=1)
    schema_: dict = Field(alias="schema")

    @model_validator(mode="after")
    def validate_schema(self) -> "ExaSummaryConfig":
        required = set(self.schema_.get("required") or ())
        properties = self.schema_.get("properties") or {}
        if not {"value", "quote", "source_url"} <= required:
            raise ValueError("summary.schema must require value, quote and source_url")
        if not isinstance(properties, dict) or not {
            "value", "quote", "source_url",
        } <= set(properties):
            raise ValueError("summary.schema must define value, quote and source_url")
        return self


class ExaContentsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: ExaTextConfig
    highlights: ExaHighlightsConfig
    summary: ExaSummaryConfig


class ExaSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    type: Literal["auto", "neural", "keyword", "deep"] = "auto"
    num_results: int = Field(gt=0, le=20)
    include_domains: tuple[str, ...] = ()
    contents: ExaContentsConfig


class FactSelectionConfig(BaseModel):
    """Deterministic multi-result selection policy.

    ``source_rank`` is option A.  ``require_declared_source_url`` is option D:
    when enabled, Exa's declared URL must equal the URL of the result that
    supplied the summary and quote.  It is intentionally a per-fact setting so
    an officer can tighten or relax the guardrail without touching code.
    """

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["source_rank"] = "source_rank"
    require_declared_source_url: bool = False


class FactSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    fact: str = Field(min_length=1)
    category_arp: str = Field(min_length=1)
    allowed_values: tuple[str, ...] = Field(min_length=1)
    hint: str = Field(min_length=1)
    exa: ExaSearchConfig
    selection: FactSelectionConfig = Field(default_factory=FactSelectionConfig)

    @model_validator(mode="after")
    def validate_fact(self) -> "FactSearchConfig":
        if self.fact not in CONTRACT_FACT_NAMES:
            raise ValueError(f"unknown ContractFacts field: {self.fact}")
        if len(self.allowed_values) != len(set(self.allowed_values)):
            raise ValueError(f"duplicate allowed value for fact {self.fact}")
        if "unknown" not in self.allowed_values:
            raise ValueError(f"fact {self.fact} must allow unknown")
        invalid_values = []
        for value in self.allowed_values:
            try:
                ContractFacts.model_validate({self.fact: value})
            except Exception:  # validation message below identifies the YAML fact
                invalid_values.append(value)
        if invalid_values:
            raise ValueError(
                f"values not accepted by ContractFacts for {self.fact}: {invalid_values}"
            )
        placeholders = _placeholders(self.exa.query, context=f"fact {self.fact} exa.query")
        missing = _REQUIRED_QUERY_PLACEHOLDERS - placeholders
        if missing:
            raise ValueError(
                f"fact {self.fact} exa.query must contain offer placeholders: "
                f"{', '.join(sorted(missing))}"
            )
        for domain in self.exa.include_domains:
            _placeholders(domain, context=f"fact {self.fact} exa.include_domains")
        value_schema = (self.exa.contents.summary.schema_.get("properties") or {}).get("value")
        if not isinstance(value_schema, dict):
            raise ValueError("summary.schema.properties.value must be an object")
        if tuple(value_schema.get("enum") or ()) != self.allowed_values:
            raise ValueError(
                f"summary.schema value enum must match allowed_values for {self.fact}"
            )
        return self

    def placeholders(self) -> frozenset[str]:
        """Placeholders used by this fact's query and domain filters."""
        return _placeholders(self.exa.query, context=f"fact {self.fact} exa.query") | frozenset(
            placeholder
            for domain in self.exa.include_domains
            for placeholder in _placeholders(
                domain, context=f"fact {self.fact} exa.include_domains",
            )
        )

    def render(
        self,
        *,
        tool: str,
        vendor: str,
        plan: str = "",
        deployment_mode: str = "",
        contract_type: str = "",
        contract_version: str = "",
        jurisdiction: str = "",
    ) -> "RenderedFactSearch":
        values = {
            "tool": tool,
            "vendor": vendor,
            "plan": plan,
            "deployment_mode": deployment_mode,
            "contract_type": contract_type,
            "contract_version": contract_version,
            "jurisdiction": jurisdiction,
        }
        try:
            query = self.exa.query.format(**values)
            include_domains = tuple(
                domain.format(**values) for domain in self.exa.include_domains
            )
        except KeyError as exc:
            raise ValueError(
                f"unsupported placeholder in fact-search config {self.fact}: {exc.args[0]}"
            ) from exc
        return RenderedFactSearch(
            definition=self,
            query=query,
            include_domains=include_domains,
        )


@dataclass(frozen=True)
class RenderedFactSearch:
    definition: FactSearchConfig
    query: str
    include_domains: tuple[str, ...]


def _resolve_path(path: str | Path | None, environment: Mapping[str, str]) -> Path:
    selected = path or environment.get("POLICYBOT_FACT_SEARCH_DIR")
    if selected:
        resolved = Path(selected)
    elif DEFAULT_FACT_SEARCH_DIR.is_dir():
        resolved = DEFAULT_FACT_SEARCH_DIR
    else:
        # setuptools ``data-files`` places the shipped YAML beside the Python
        # installation rather than inside the package.  Editable installs keep
        # the repository path above, while a wheel uses this fallback.
        resolved = Path(sysconfig.get_path("data")) / "configs" / "recherche_des_faits"
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def load_fact_search_configs(
    directory: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> tuple[FactSearchConfig, ...]:
    """Load sorted, independently validated YAML definitions for contract facts."""
    environment = os.environ if env is None else env
    config_dir = _resolve_path(directory, environment)
    if not config_dir.is_dir():
        raise FileNotFoundError(f"PolicyBot fact-search directory not found: {config_dir}")

    configs: list[FactSearchConfig] = []
    for path in sorted(config_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"fact-search config must be a YAML mapping: {path}")
        try:
            configs.append(FactSearchConfig.model_validate(raw))
        except Exception as exc:  # pydantic error needs the actionable filename
            raise ValueError(f"invalid fact-search config {path}: {exc}") from exc
    if not configs:
        raise ValueError(f"no fact-search YAML files found in: {config_dir}")

    names = [config.fact for config in configs]
    if len(names) != len(set(names)):
        raise ValueError("fact-search config files must define unique facts")
    return tuple(configs)


def require_complete_fact_search_set(
    configs: tuple[FactSearchConfig, ...],
) -> tuple[FactSearchConfig, ...]:
    configured = {config.fact for config in configs}
    expected = set(CONTRACT_FACT_NAMES)
    missing = sorted(expected - configured)
    extra = sorted(configured - expected)
    if missing or extra:
        raise ValueError(
            "fact-search config set must match ContractFacts exactly "
            f"(missing={missing}, extra={extra})"
        )
    return configs


FACT_SEARCHES = require_complete_fact_search_set(load_fact_search_configs())
FACT_SEARCH_BY_NAME = {config.fact: config for config in FACT_SEARCHES}
