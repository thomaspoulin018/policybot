from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field
from policybot.models import IagType


class WizardState(BaseModel):
    tool_name: str = ""
    tool_type_override: IagType | None = None
    data_checked: list[str] = Field(default_factory=list)
    data_free_text: str = ""
    usage_description: str = ""
    mode: Literal["prompt", "api"] | None = None
    result_use_checked: list[str] = Field(default_factory=list)
    result_use_free_text: str = ""
    automated_decisions: bool = False

    def to_hidden_fields(self) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = []
        if self.tool_name:
            fields.append(("tool_name", self.tool_name))
        if self.tool_type_override:
            fields.append(("tool_type_override", self.tool_type_override))
        for label in self.data_checked:
            fields.append(("data_checked", label))
        if self.data_free_text:
            fields.append(("data_free_text", self.data_free_text))
        if self.usage_description:
            fields.append(("usage_description", self.usage_description))
        if self.mode:
            fields.append(("mode", self.mode))
        for label in self.result_use_checked:
            fields.append(("result_use_checked", label))
        if self.result_use_free_text:
            fields.append(("result_use_free_text", self.result_use_free_text))
        if self.automated_decisions:
            fields.append(("automated_decisions", "true"))
        return fields

    @classmethod
    def from_form(cls, form: dict) -> "WizardState":
        def as_list(key: str) -> list[str]:
            value = form.get(key, [])
            if isinstance(value, list):
                return value
            return [value] if value else []

        return cls(
            tool_name=form.get("tool_name", "") or "",
            tool_type_override=form.get("tool_type_override") or None,
            data_checked=as_list("data_checked"),
            data_free_text=form.get("data_free_text", "") or "",
            usage_description=form.get("usage_description", "") or "",
            mode=form.get("mode") or None,
            result_use_checked=as_list("result_use_checked"),
            result_use_free_text=form.get("result_use_free_text", "") or "",
            automated_decisions=str(form.get("automated_decisions", "")).lower() == "true",
        )


def compose_description(checked_labels: list[str], free_text: str) -> str:
    parts = list(checked_labels) + ([free_text] if free_text else [])
    return "; ".join(parts)
