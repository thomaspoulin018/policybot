"""La ligne de commande de PolicyBot.

Le téléchargement est séparé de l'ingestion pour que cette dernière reste
hors ligne et rejouable :

    policybot creer-formulaire
    policybot recuperer-reponses -o reponses.json
    policybot ingerer reponses.json --dry-run

`--dry-run` lit et valide le JSON, affiche l'identité d'offre résolue pour
chaque demande, et n'appelle rien : ni modèle, ni recherche, ni écriture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from policybot.config import CleApiManquante
from policybot.intake.formulaire import FormulaireInvalideError, devis
from policybot.intake.google_api import GoogleFormsError
from policybot.intake.google_forms import (
    ConfigurationGoogleFormsError,
    creer_formulaire_google,
    recuperer_reponses_google,
)
from policybot.intake.reponses import (
    FichierReponsesInvalideError,
    LotReponses,
    lire_reponses,
)
from policybot.intake.schema import DemandeIAG, TypeIagInconnuError


_LARGEUR_ETIQUETTE = 16


def _ecrire(flux, texte: str = "") -> None:
    print(texte, file=flux)


def _resume_lot(lot: LotReponses, flux) -> None:
    _ecrire(
        flux,
        f"{lot.reponses_lues} réponse(s) lue(s), {len(lot.demandes)} demande(s) valide(s), "
        f"{len(lot.rejets)} rejetée(s)",
    )
    for question_id in lot.question_ids_inconnus:
        _ecrire(flux, f"  questionId absent du mapping : {question_id}")
    _ecrire(flux)


def _afficher_offre(index: int, demande: DemandeIAG, flux) -> bool:
    """Affiche l'identité d'offre résolue. Rend False si elle ne l'est pas."""
    _ecrire(flux, f"{index:>3}. {demande.tool_name}")
    try:
        entrees = demande.vers_entrees_orchestrateur()
    except TypeIagInconnuError as erreur:
        _ecrire(flux, f"     non résolue : {erreur}")
        return False
    offre = entrees.offering
    champs = (
        ("vendor", offre.vendor or "(inconnu)"),
        ("product", offre.product),
        ("plan", offre.plan or "(non précisé)"),
        ("deployment_mode", offre.deployment_mode),
        ("contract_type", offre.contract_type),
        ("contract_version", offre.contract_version or "(non précisée)"),
        ("jurisdiction", offre.jurisdiction or "(non précisé)"),
    )
    for nom, valeur in champs:
        _ecrire(flux, f"     {nom:<{_LARGEUR_ETIQUETTE}}: {valeur}")
    manquants = offre.missing_search_identity_fields()
    if manquants:
        _ecrire(flux, f"     identité incomplète : {', '.join(manquants)}")
    _ecrire(flux)
    return True


def _afficher_rejets(lot: LotReponses, flux) -> None:
    for rejet in lot.rejets:
        _ecrire(flux, f"  réponse {rejet.response_id} rejetée : {rejet.motif}")
    if lot.rejets:
        _ecrire(flux)


def commande_devis(args: argparse.Namespace, flux) -> int:
    _ecrire(flux, devis())
    return 0


def commande_creer_formulaire(args: argparse.Namespace, flux) -> int:
    if args.force:
        _ecrire(
            flux,
            "AVERTISSEMENT — --force crée un nouveau formulaire : l'URL diffusée "
            "sera perdue et les réponses déjà collectées deviendront illisibles "
            "avec le nouveau mapping.",
        )
    configuration = creer_formulaire_google(force=args.force)
    _ecrire(flux, "Formulaire Google créé et publié.")
    _ecrire(flux, configuration["responder_uri"])
    return 0


def commande_recuperer_reponses(args: argparse.Namespace, flux) -> int:
    compte, chemin = recuperer_reponses_google(args.sortie)
    _ecrire(flux, f"{compte} réponse(s) téléchargée(s) dans {chemin}")
    return 0


def _ecrire_constats(state, repertoire: Path) -> Path:
    repertoire.mkdir(parents=True, exist_ok=True)
    tool = state.tools[0] if state.tools else None
    findings = [f.model_dump(mode="json") for f in (tool.findings if tool else [])]
    chemin = repertoire / f"{state.request.numero}.json"
    chemin.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chemin


def commande_ingerer(args: argparse.Namespace, flux) -> int:
    lot = lire_reponses(args.fichier)
    _resume_lot(lot, flux)
    _afficher_rejets(lot, flux)

    non_resolues = 0
    if args.dry_run:
        for index, demande in enumerate(lot.demandes, start=1):
            if not _afficher_offre(index, demande, flux):
                non_resolues += 1
        _ecrire(flux, "--dry-run : aucune recherche lancée, aucun coût engagé.")
        return 1 if lot.rejets or non_resolues else 0

    from policybot.interview.factory import default_interview
    from policybot.report.grille import write_grille
    from policybot.report.renderer import write_docx

    itv = default_interview()
    cout_total = 0.0
    echecs = 0
    for index, demande in enumerate(lot.demandes, start=1):
        _ecrire(flux, f"{index:>3}. {demande.tool_name}")
        try:
            entrees = demande.vers_entrees_orchestrateur()
            state = itv.assess(
                request=entrees.request,
                tool_name=entrees.tool_name,
                usage_inputs=entrees.usage_inputs,
                iag_type_override=entrees.iag_type_override,
                qualification=entrees.qualification,
                offering_override=entrees.offering,
            )
        except CleApiManquante:
            # Une clé absente ne concerne pas cette demande-là : elle vaut pour
            # tout le lot. Poursuivre produirait des dossiers sans constats.
            raise
        except Exception as erreur:  # une demande en échec n'arrête pas le lot
            echecs += 1
            _ecrire(flux, f"     échec : {type(erreur).__name__} — {erreur}")
            continue
        findings = state.tools[0].findings
        cout = state.tools[0].total_cost_dollars
        cout_total += cout
        compte = {"ok": 0, "no_answer": 0, "search_failed": 0}
        for finding in findings:
            compte[finding.outcome] = compte.get(finding.outcome, 0) + 1
        _ecrire(
            flux,
            f"     {len(findings)} constats · {compte['ok']} ok · "
            f"{compte['no_answer']} sans réponse · {compte['search_failed']} échec · "
            f"{cout:.2f} $",
        )
        for chemin in (
            write_docx(state, args.sortie_docx),
            write_grille(state, args.sortie_docx),
            _ecrire_constats(state, Path(args.sortie_json or "output/json")),
        ):
            _ecrire(flux, f"     {chemin}")
        _ecrire(flux)
    _ecrire(flux, f"coût Exa total : {cout_total:.2f} $")
    return 1 if lot.rejets or echecs else 0


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(
        prog="policybot",
        description="Transforme les réponses Google Forms en dossiers de constats sourcés.",
    )
    sous = parseur.add_subparsers(dest="commande", required=True)

    devis_ = sous.add_parser(
        "devis-formulaire",
        help="imprime un aperçu hors ligne des questions",
    )
    devis_.set_defaults(fonction=commande_devis)

    creer = sous.add_parser(
        "creer-formulaire",
        help="crée et publie le formulaire Google depuis le catalogue YAML",
    )
    creer.add_argument(
        "--force",
        action="store_true",
        help="crée une nouvelle URL même si un mapping existe déjà",
    )
    creer.set_defaults(fonction=commande_creer_formulaire)

    recuperer = sous.add_parser(
        "recuperer-reponses",
        help="télécharge les réponses Google Forms dans un JSON local",
    )
    recuperer.add_argument(
        "-o", "--sortie", required=True, help="fichier JSON de destination"
    )
    recuperer.set_defaults(fonction=commande_recuperer_reponses)

    ingerer = sous.add_parser(
        "ingerer",
        help="lit un JSON de réponses et produit un dossier par demande",
    )
    ingerer.add_argument("fichier", help="réponses Google Forms au format JSON")
    ingerer.add_argument(
        "--dry-run",
        action="store_true",
        help="lit et valide sans lancer aucune recherche",
    )
    ingerer.add_argument("--sortie-docx", default=None, help="répertoire des .docx")
    ingerer.add_argument("--sortie-json", default=None, help="répertoire des constats .json")
    ingerer.set_defaults(fonction=commande_ingerer)
    return parseur


def main(argv: Sequence[str] | None = None, flux=None) -> int:
    if flux is None:
        # La console Windows n'est pas en UTF-8 par défaut : sans cela, le
        # premier accent du formulaire fait tomber la commande.
        for canal in (sys.stdout, sys.stderr):
            reconfigure = getattr(canal, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="replace")
        flux = sys.stdout
        # Rien ne lisait `.env` : les clés n'atteignaient le pipeline que si
        # elles étaient exportées à la main. La suite de tests appelle `main`
        # avec un flux explicite et reste donc hors ligne.
        from dotenv import load_dotenv
        load_dotenv()
    args = construire_parseur().parse_args(argv)
    try:
        return args.fonction(args, flux)
    except FileNotFoundError as erreur:
        print(str(erreur), file=sys.stderr)
        return 2
    except FormulaireInvalideError as erreur:
        _ecrire(flux, str(erreur))
        return 2
    except (
        ConfigurationGoogleFormsError,
        FichierReponsesInvalideError,
        GoogleFormsError,
    ) as erreur:
        print(str(erreur), file=sys.stderr)
        return 2
    except CleApiManquante as erreur:
        print(str(erreur), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
