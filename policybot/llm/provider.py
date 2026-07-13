from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str, *,
                      run_name: str | None = None,
                      tags: list[str] | None = None) -> dict:
        """Return a JSON object the model produced for the prompt.

        `run_name` and `tags` are optional LangSmith trace annotations; providers
        that don't trace ignore them.
        """

    @abstractmethod
    def complete_structured(self, system: str, user: str,
                            schema: type[StructuredModel], *,
                            run_name: str | None = None,
                            tags: list[str] | None = None) -> StructuredModel:
        """Return a pydantic model produced through structured output."""

    @abstractmethod
    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None) -> str:
        """Return free-form narrative text.

        `run_name` and `tags` are optional LangSmith trace annotations; providers
        that don't trace ignore them.
        """
