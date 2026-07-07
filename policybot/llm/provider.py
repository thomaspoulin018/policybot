from abc import ABC, abstractmethod


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
    def draft_text(self, system: str, user: str, *,
                   run_name: str | None = None,
                   tags: list[str] | None = None) -> str:
        """Return free-form narrative text.

        `run_name` and `tags` are optional LangSmith trace annotations; providers
        that don't trace ignore them.
        """
