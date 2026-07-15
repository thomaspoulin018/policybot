"""Traduit un dict plat de faits contractuels en réponses LLM par famille.

L'extraction ARP fait désormais un appel LLM par famille (5), chacun rendant
{value, source_url, quote, confidence} par champ. Les tests continuent d'écrire
`trains_on_input="no"` et ce helper fabrique les 5 payloads correspondants.

Depuis l'ajout de la vérification d'ancrage (`_quote_is_anchored`), une citation
qui n'apparaît pas dans la preuve fait retomber le fait à `unknown`. La fixture
doit donc citer un vrai extrait de la preuve : passe `evidence=` (le texte que le
test fournit) et la citation en sera un extrait ; sinon `DEFAULT_EVIDENCE` est
utilisée — les tests qui s'appuient sur les valeurs doivent alors fournir cette
même preuve à l'entrevue.
"""
from policybot.contract.families import FACT_FAMILIES

DEFAULT_URL = "https://example.test/evidence"

# Preuve canonique : contient une phrase par sujet, assez longue pour être une
# ancre valable (≥ 15 caractères normalisés). Les tests qui vérifient des valeurs
# doivent fournir CE texte comme preuve (via `http_get`, `from_single`, etc.).
DEFAULT_EVIDENCE = (
    "The vendor's terms of service and privacy policy describe this fact "
    "explicitly for institutional customers such as universities."
)

# Extrait effectivement présent dans DEFAULT_EVIDENCE, réutilisé comme citation.
_DEFAULT_QUOTE = "The vendor's terms of service and privacy policy describe this fact"


def arp_extraction_responses(_url: str = DEFAULT_URL, *, evidence: str | None = None,
                             **values) -> list[dict]:
    unknown_fields = set(values) - {
        field.name for family in FACT_FAMILIES for field in family.fields
    }
    if unknown_fields:
        raise AssertionError(f"champs inconnus dans la fixture ARP: {sorted(unknown_fields)}")

    # Une citation garantie présente dans la preuve : un extrait réel de
    # `evidence` si fourni, sinon l'extrait canonique.
    if evidence is not None:
        quote = " ".join(evidence.split())[:120] or _DEFAULT_QUOTE
    else:
        quote = _DEFAULT_QUOTE

    responses = []
    for family in FACT_FAMILIES:
        payload = {}
        for field in family.fields:
            value = values.get(field.name, "unknown")
            payload[field.name] = {
                "value": value,
                "source_url": _url,
                "quote": quote,
                "confidence": 0.9,
            }
        responses.append(payload)
    return responses
