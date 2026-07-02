from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def complete_json(self, system: str, user: str) -> dict:
        """Return a JSON object the model produced for the prompt."""

    @abstractmethod
    def draft_text(self, system: str, user: str) -> str:
        """Return free-form narrative text."""
