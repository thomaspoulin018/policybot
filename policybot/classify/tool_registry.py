"""Les outils connus et leur type IAG.

Le registre ne porte que ce que le code lit : le fournisseur, qui alimente
l'identité d'offre et les requêtes de recherche, et le type IAG. Les champs
`terms_url` et `contract_sources` ont été retirés — aucun appelant ne les lisait
et leurs listes d'adresses vieillissaient sans que rien ne s'en aperçoive. Les
sources contractuelles retenues sont désormais celles que la recherche trouve
et qu'une citation ancrée valide.
"""
from policybot.models import IagType

REGISTRY: dict[str, dict] = {
    "chatgpt": {"iag_type": "publique", "vendor": "OpenAI"},
    "chatgpt pro": {"iag_type": "publique", "vendor": "OpenAI"},
    "claude.ai": {"iag_type": "publique", "vendor": "Anthropic"},
    "perplexity": {"iag_type": "publique", "vendor": "Perplexity"},
    "microsoft copilot entreprise": {
        "iag_type": "circuit_ferme", "vendor": "Microsoft",
    },
}


def lookup_tool(name: str) -> dict | None:
    return REGISTRY.get(name.strip().lower())


def classify_tool_type(name: str) -> IagType | None:
    """Le type IAG d'un outil connu, sinon None : le formulaire doit le fournir."""
    entry = lookup_tool(name)
    return entry["iag_type"] if entry else None
