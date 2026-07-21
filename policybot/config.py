from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Mapping, TypeAlias

import yaml
from pydantic import BaseModel, ConfigDict, Field


LLMTask: TypeAlias = Literal[
    "data_classification",
    "tool_type_detection",
    "mode_detection",
    "form_suggestions",
]
ArpCacheMode: TypeAlias = Literal[
    "read_write",
    "refresh",
    "read_only",
    "disabled",
]

LLM_TASKS: tuple[LLMTask, ...] = (
    "data_classification",
    "tool_type_detection",
    "mode_detection",
    "form_suggestions",
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _PROJECT_ROOT / "configs" / "policybot.yaml"


class ModelTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    max_tokens: int = Field(gt=0)
    temperature: float = Field(ge=0.0, le=2.0)
    timeout: float = Field(gt=0.0, description="Maximum call duration in seconds")


class LLMTasksConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_classification: ModelTaskConfig
    tool_type_detection: ModelTaskConfig
    mode_detection: ModelTaskConfig
    form_suggestions: ModelTaskConfig


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["openrouter"] = "openrouter"
    tasks: LLMTasksConfig


class ArpCacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ArpCacheMode = "read_write"


class CacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    arp: ArpCacheConfig = Field(default_factory=ArpCacheConfig)


class PolicyBotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    llm: LLMConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)


_GLOBAL_ENV_FIELDS = {
    "model": "OPENROUTER_MODEL",
    "reasoning_effort": "OPENROUTER_REASONING_EFFORT",
    "max_tokens": "OPENROUTER_MAX_TOKENS",
    "temperature": "OPENROUTER_TEMPERATURE",
    "timeout": "OPENROUTER_TIMEOUT",
}


def _apply_environment_overrides(raw: dict, env: Mapping[str, str]) -> dict:
    """Apply global then task-specific environment overrides to YAML data."""
    tasks = raw.setdefault("llm", {}).setdefault("tasks", {})
    for task in LLM_TASKS:
        task_config = tasks.setdefault(task, {})
        task_prefix = f"POLICYBOT_LLM_{task.upper()}"
        for field, global_name in _GLOBAL_ENV_FIELDS.items():
            value = env.get(f"{task_prefix}_{field.upper()}")
            if value is None:
                value = env.get(global_name)
            if value is not None and value != "":
                task_config[field] = value

    cache_mode = env.get("POLICYBOT_ARP_CACHE_MODE")
    if cache_mode:
        raw.setdefault("cache", {}).setdefault("arp", {})["mode"] = cache_mode
    return raw


def load_config(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> PolicyBotConfig:
    """Load and validate PolicyBot's non-secret runtime configuration."""
    environment = os.environ if env is None else env
    configured_path = path or environment.get("POLICYBOT_CONFIG_PATH")
    config_path = Path(configured_path) if configured_path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    if not config_path.is_file():
        raise FileNotFoundError(f"PolicyBot config file not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"PolicyBot config must be a YAML mapping: {config_path}")
    return PolicyBotConfig.model_validate(
        _apply_environment_overrides(raw, environment)
    )
