"""Orchestration de la création d'un formulaire et de ses réponses."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from policybot.intake.formulaire import CatalogueFormulaire, formulaire
from policybot.intake.google_api import GoogleFormsClient
from policybot.intake.google_items import requetes_formulaire


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_MAPPING_PATH = _PROJECT_ROOT / "configs" / "formulaire-google.json"


class ConfigurationGoogleFormsError(ValueError):
    """Le mapping local est absent ou incohérent."""


class FormulaireGoogleExistantError(ConfigurationGoogleFormsError):
    """La création écraserait la trace d'un formulaire existant."""


def charger_configuration(
    chemin: str | Path = DEFAULT_MAPPING_PATH,
) -> dict:
    path = Path(chemin)
    if not path.is_file():
        raise FileNotFoundError(
            f"Configuration Google Forms introuvable : {path}. "
            "Lance d'abord « policybot creer-formulaire »."
        )
    try:
        configuration = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as erreur:
        raise ConfigurationGoogleFormsError(
            f"Configuration Google Forms invalide ({path}) : {erreur}"
        ) from erreur
    if not isinstance(configuration, dict):
        raise ConfigurationGoogleFormsError(
            f"Configuration Google Forms invalide ({path}) : un objet JSON est attendu."
        )
    form_id = configuration.get("form_id")
    questions = configuration.get("questions")
    if not isinstance(form_id, str) or not form_id.strip():
        raise ConfigurationGoogleFormsError(
            f"Configuration Google Forms invalide ({path}) : « form_id » est absent."
        )
    if not isinstance(questions, dict) or not all(
        isinstance(cle, str) and isinstance(valeur, str)
        for cle, valeur in questions.items()
    ):
        raise ConfigurationGoogleFormsError(
            f"Configuration Google Forms invalide ({path}) : « questions » doit "
            "associer chaque questionId à un champ."
        )
    return configuration


def _question_ids(requetes: list[dict], resultat: dict) -> list[str]:
    """Extrait les identifiants des réponses createItem, dans l'ordre du lot."""
    replies = resultat.get("replies", [])
    if not isinstance(replies, list):
        replies = []
    ids: list[str] = []
    for index, requete in enumerate(requetes):
        item = requete.get("createItem", {}).get("item", {})
        if "questionItem" not in item:
            continue
        reply = replies[index] if index < len(replies) else {}
        trouve = reply.get("createItem", {}).get("questionId", [])
        if isinstance(trouve, str):
            trouve = [trouve]
        if isinstance(trouve, list) and trouve and isinstance(trouve[0], str):
            ids.append(trouve[0])
    # Certains transports rendent le formulaire inclus plutôt que tous les
    # CreateItemResponse. Préférer cette vue si elle est plus complète.
    form = resultat.get("form", {})
    ids_formulaire: list[str] = []
    for item in form.get("items", []) if isinstance(form, dict) else []:
        question = item.get("questionItem", {}).get("question", {})
        question_id = question.get("questionId")
        if isinstance(question_id, str):
            ids_formulaire.append(question_id)
    return ids_formulaire if len(ids_formulaire) > len(ids) else ids


def creer_formulaire_google(
    *,
    catalogue: CatalogueFormulaire | None = None,
    client: GoogleFormsClient | None = None,
    chemin_mapping: str | Path = DEFAULT_MAPPING_PATH,
    force: bool = False,
) -> dict:
    """Crée, remplit, publie, puis écrit le mapping questionId → champ."""
    catalogue = catalogue or formulaire()
    client = client or GoogleFormsClient()
    path = Path(chemin_mapping)
    if path.exists() and not force:
        uri = "(URL inconnue)"
        try:
            ancien = json.loads(path.read_text(encoding="utf-8"))
            uri = ancien.get("responder_uri") or uri
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        raise FormulaireGoogleExistantError(
            f"Un formulaire est déjà configuré : {uri}. "
            "Relance avec --force pour créer une nouvelle URL."
        )

    cree = client.creer_formulaire(catalogue.titre)
    form_id = cree.get("formId")
    if not isinstance(form_id, str) or not form_id:
        raise ConfigurationGoogleFormsError(
            "Google Forms n'a pas rendu de formId après la création."
        )
    requetes = requetes_formulaire(catalogue)
    resultat_lot = client.appliquer_lot(form_id, requetes)
    ids = _question_ids(requetes, resultat_lot)
    if len(ids) != len(catalogue.questions):
        raise ConfigurationGoogleFormsError(
            "Impossible d'apparier les questionId : "
            f"{len(ids)} reçu(s) pour {len(catalogue.questions)} question(s)."
        )

    # La publication est volontairement dans cette séquence, avant toute URL
    # écrite ou affichée : un formulaire non publié ne doit jamais être diffusé.
    client.publier(form_id)

    form_resultat = resultat_lot.get("form", {})
    responder_uri = None
    if isinstance(form_resultat, dict):
        responder_uri = form_resultat.get("responderUri")
    responder_uri = responder_uri or cree.get("responderUri")
    if not isinstance(responder_uri, str) or not responder_uri:
        raise ConfigurationGoogleFormsError(
            "Le formulaire a été publié, mais Google n'a rendu aucune URL répondant."
        )
    configuration = {
        "form_id": form_id,
        "responder_uri": responder_uri,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "catalogue_version": catalogue.version,
        "questions": {
            question_id: question.champ
            for question_id, question in zip(ids, catalogue.questions, strict=True)
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(configuration, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as erreur:
        raise ConfigurationGoogleFormsError(
            f"Formulaire publié, mais mapping impossible à écrire dans {path} : {erreur}"
        ) from erreur
    return configuration


def recuperer_reponses_google(
    sortie: str | Path,
    *,
    client: GoogleFormsClient | None = None,
    chemin_mapping: str | Path = DEFAULT_MAPPING_PATH,
) -> tuple[int, Path]:
    """Télécharge les réponses brutes agrégées et les écrit sans interprétation."""
    configuration = charger_configuration(chemin_mapping)
    client = client or GoogleFormsClient()
    contenu = client.lister_reponses(configuration["form_id"])
    responses = contenu.get("responses")
    if not isinstance(responses, list):
        raise ConfigurationGoogleFormsError(
            "Google Forms n'a pas rendu une liste de réponses."
        )
    path = Path(sortie)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(contenu, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as erreur:
        raise ConfigurationGoogleFormsError(
            f"Impossible d'écrire les réponses dans {path} : {erreur}"
        ) from erreur
    return len(responses), path
