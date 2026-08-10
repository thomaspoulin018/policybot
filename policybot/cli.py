"""La ligne de commande de PolicyBot.

Deux verbes, aucune dépendance nouvelle :

    policybot devis-formulaire            imprime le formulaire à recopier
    policybot ingerer reponses.xlsx       traite un export Microsoft Forms

`--dry-run` lit et valide l'export, affiche l'identité d'offre résolue pour
chaque demande, et n'appelle rien : ni modèle, ni recherche, ni écriture.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from policybot.intake.formulaire import devis
from policybot.intake.reponses import LotReponses, lire_export
from policybot.intake.schema import DemandeIAG, TypeIagInconnuError


_LARGEUR_ETIQUETTE = 16


def _ecrire(flux, texte: str = "") -> None:
    print(texte, file=flux)


def _resume_lot(lot: LotReponses, flux) -> None:
    _ecrire(
        flux,
        f"{lot.lignes_lues} réponse(s) lue(s), {len(lot.demandes)} demande(s) valide(s), "
        f"{len(lot.rejets)} rejetée(s)",
    )
    for colonne in lot.colonnes_ignorees:
        _ecrire(flux, f"  colonne ignorée : {colonne}")
    for colonne in lot.colonnes_manquantes:
        _ecrire(flux, f"  colonne absente de l'export : {colonne}")
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
        _ecrire(flux, f"  ligne {rejet.ligne} rejetée : {rejet.motif}")
    if lot.rejets:
        _ecrire(flux)


def commande_devis(args: argparse.Namespace, flux) -> int:
    _ecrire(flux, devis())
    return 0


def _ecrire_constats(state, repertoire: Path) -> Path:
    repertoire.mkdir(parents=True, exist_ok=True)
    tool = state.tools[0] if state.tools else None
    findings = [f.model_dump(mode="json") for f in (tool.arp.findings if tool and tool.arp else [])]
    chemin = repertoire / f"{state.request.numero}.json"
    chemin.write_text(
        json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chemin


def commande_ingerer(args: argparse.Namespace, flux) -> int:
    lot = lire_export(args.fichier)
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
    from policybot.report.renderer import write_docx, write_pdf

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
        except Exception as erreur:  # une demande en échec n'arrête pas le lot
            echecs += 1
            _ecrire(flux, f"     échec : {type(erreur).__name__} — {erreur}")
            continue
        findings = state.tools[0].arp.findings if state.tools[0].arp else []
        cout = state.tools[0].arp.total_cost_dollars if state.tools[0].arp else 0.0
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
            write_pdf(state, args.sortie_pdf),
            _ecrire_constats(state, Path(args.sortie_json or "output/json")),
        ):
            _ecrire(flux, f"     {chemin}")
        _ecrire(flux)
    _ecrire(flux, f"coût Exa total : {cout_total:.2f} $")
    return 1 if lot.rejets or echecs else 0


def construire_parseur() -> argparse.ArgumentParser:
    parseur = argparse.ArgumentParser(
        prog="policybot",
        description="Transforme un export Microsoft Forms en dossiers de constats sourcés.",
    )
    sous = parseur.add_subparsers(dest="commande", required=True)

    devis_ = sous.add_parser(
        "devis-formulaire",
        help="imprime les questions à recopier dans Microsoft Forms",
    )
    devis_.set_defaults(fonction=commande_devis)

    ingerer = sous.add_parser(
        "ingerer",
        help="lit un export .xlsx de réponses et produit un dossier par demande",
    )
    ingerer.add_argument("fichier", help="export Microsoft Forms au format .xlsx")
    ingerer.add_argument(
        "--dry-run",
        action="store_true",
        help="lit et valide sans lancer aucune recherche",
    )
    ingerer.add_argument("--sortie-docx", default=None, help="répertoire des .docx")
    ingerer.add_argument("--sortie-pdf", default=None, help="répertoire des .pdf")
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
    args = construire_parseur().parse_args(argv)
    try:
        return args.fonction(args, flux)
    except FileNotFoundError as erreur:
        print(str(erreur), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
