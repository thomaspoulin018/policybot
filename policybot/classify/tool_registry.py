from policybot.models import IagType

REGISTRY: dict[str, dict] = {
    "chatgpt": {"iag_type": "publique", "vendor": "OpenAI",
                "terms_url": "https://openai.com/policies/terms-of-use",
                "contract_sources": {
                    "consumer_terms": [
                        "https://openai.com/policies/terms-of-use",
                        "https://openai.com/policies/privacy-policy",
                    ],
                    "institutional_agreement": [
                        "https://openai.com/policies/business-terms",
                        "https://openai.com/policies/data-processing-addendum",
                        "https://openai.com/enterprise-privacy",
                    ],
                }},
    "chatgpt pro": {"iag_type": "publique", "vendor": "OpenAI",
                    "terms_url": "https://openai.com/policies/terms-of-use",
                    "contract_sources": {
                        "consumer_terms": [
                            "https://openai.com/policies/terms-of-use",
                            "https://openai.com/policies/privacy-policy",
                        ],
                    }},
    "claude.ai": {"iag_type": "publique", "vendor": "Anthropic",
                  "terms_url": "https://www.anthropic.com/legal/consumer-terms",
                  "contract_sources": {
                      "consumer_terms": [
                          "https://www.anthropic.com/legal/consumer-terms",
                          "https://www.anthropic.com/legal/privacy",
                      ],
                      "institutional_agreement": [
                          "https://www.anthropic.com/legal/commercial-terms",
                          "https://www.anthropic.com/legal/data-processing-addendum",
                      ],
                  }},
    "perplexity": {"iag_type": "publique", "vendor": "Perplexity",
                   "terms_url": "https://www.perplexity.ai/hub/legal/terms-of-service"},
    "microsoft copilot entreprise": {"iag_type": "circuit_ferme", "vendor": "Microsoft",
                                     "terms_url": "https://www.microsoft.com/licensing",
                                     "contract_sources": {
                                         "institutional_agreement": [
                                             "https://learn.microsoft.com/en-us/microsoft-365/copilot/microsoft-365-copilot-privacy",
                                             "https://learn.microsoft.com/en-us/microsoft-365/copilot/enterprise-data-protection",
                                             "https://www.microsoft.com/licensing",
                                         ],
                                     }},
}


def lookup_tool(name: str) -> dict | None:
    return REGISTRY.get(name.strip().lower())
