from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from policybot.config import LLMTask


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPTS_PATH = _PROJECT_ROOT / "configs" / "prompts.yaml"


class PromptDefinition(BaseModel):
    """System and user messages for one configured LLM task."""

    model_config = ConfigDict(extra="forbid")

    system: str = Field(min_length=1)
    user_template: str = Field(min_length=1)

    def render_system(self, **values: object) -> str:
        return _render(self.system, values)

    def render_user(self, **values: object) -> str:
        return _render(self.user_template, values)


class PromptTasks(BaseModel):
    """Prompts grouped by the same task names used by the LLM router."""

    model_config = ConfigDict(extra="forbid")

    data_classification: PromptDefinition
    tool_type_detection: PromptDefinition
    mode_detection: PromptDefinition
    form_suggestions: PromptDefinition
    contract_extraction: PromptDefinition


class PromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    prompts: PromptTasks


def _render(template: str, values: Mapping[str, object]) -> str:
    """Render $variables while preserving dollar signs found in user values."""
    return Template(template).substitute({key: str(value) for key, value in values.items()})


def load_prompts(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> PromptConfig:
    """Load and validate the centralized prompt catalogue."""
    environment = os.environ if env is None else env
    configured_path = path or environment.get("POLICYBOT_PROMPTS_PATH")
    prompts_path = Path(configured_path) if configured_path else DEFAULT_PROMPTS_PATH
    if not prompts_path.is_absolute():
        prompts_path = Path.cwd() / prompts_path
    if not prompts_path.is_file():
        raise FileNotFoundError(f"PolicyBot prompts file not found: {prompts_path}")

    raw = yaml.safe_load(prompts_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"PolicyBot prompts must be a YAML mapping: {prompts_path}")
    return PromptConfig.model_validate(raw)


@lru_cache(maxsize=1)
def default_prompts() -> PromptConfig:
    """Load the default catalogue once per process."""
    return load_prompts()


def get_prompt(task: LLMTask) -> PromptDefinition:
    return getattr(default_prompts().prompts, task)
