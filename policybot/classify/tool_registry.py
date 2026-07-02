from policybot.models import IagType

REGISTRY: dict[str, dict] = {
    "chatgpt": {"iag_type": "publique", "vendor": "OpenAI",
                "terms_url": "https://openai.com/policies/terms-of-use"},
    "chatgpt pro": {"iag_type": "publique", "vendor": "OpenAI",
                    "terms_url": "https://openai.com/policies/terms-of-use"},
    "claude.ai": {"iag_type": "publique", "vendor": "Anthropic",
                  "terms_url": "https://www.anthropic.com/legal/consumer-terms"},
    "perplexity": {"iag_type": "publique", "vendor": "Perplexity",
                   "terms_url": "https://www.perplexity.ai/hub/legal/terms-of-service"},
    "microsoft copilot entreprise": {"iag_type": "circuit_ferme", "vendor": "Microsoft",
                                     "terms_url": "https://www.microsoft.com/licensing"},
}


def lookup_tool(name: str) -> dict | None:
    return REGISTRY.get(name.strip().lower())
