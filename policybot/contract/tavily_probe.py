from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from policybot.contract.arp import build_arp, extract_contract_facts
from policybot.contract.tavily import (
    ensure_contract_search_config,
    load_contract_search_config,
    search_contract_terms_with_tavily,
)
from policybot.llm.openrouter import OpenRouterProvider
from policybot.models import IagType

IAG_TYPES = ("publique", "circuit_ferme", "souveraine", "gouvernementale")


def _write_text(path: str | None, text: str) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _print_yaml(data: dict) -> None:
    print(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Teste la collecte contractuelle Tavily sans lancer PolicyBot: "
            "genere/charge le YAML, lance Tavily Search + Extract, et peut "
            "normaliser l'evidence en ContractFacts via OpenRouter."
        )
    )
    parser.add_argument("tool_name", help="Nom de l'outil a tester, ex: ChatGPT")
    parser.add_argument(
        "--config-dir",
        default="configs/tavily_contracts",
        help="Dossier ou creer/lire le YAML Tavily par outil.",
    )
    parser.add_argument(
        "--evidence-out",
        help="Chemin ou sauvegarder le texte complet retourne par Tavily Extract.",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Affiche aussi la config YAML utilisee.",
    )
    parser.add_argument(
        "--facts",
        action="store_true",
        help="Normalise l'evidence Tavily en ContractFacts avec OPENROUTER_API_KEY.",
    )
    parser.add_argument(
        "--arp",
        action="store_true",
        help="Avec --facts, construit aussi les criteres ARP Partie A.",
    )
    parser.add_argument(
        "--iag-type",
        choices=IAG_TYPES,
        default="publique",
        help="Type IAG utilise seulement pour construire l'ARP avec --arp.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _build_parser().parse_args(argv)

    config_path = ensure_contract_search_config(args.tool_name, config_dir=args.config_dir)
    config = load_contract_search_config(config_path)

    if args.show_config:
        _print_yaml({"config_path": str(config_path), "config": config})

    terms = search_contract_terms_with_tavily(args.tool_name, config_dir=args.config_dir)
    if terms is None:
        print(
            "Aucune evidence Tavily trouvee. Verifie TAVILY_API_KEY et la config YAML.",
            file=sys.stderr,
        )
        return 2

    _write_text(args.evidence_out, terms.text)

    result: dict = {
        "tool_name": args.tool_name,
        "config_path": str(config_path),
        "source_url": terms.source_url,
        "fetched_at": terms.fetched_at.isoformat(),
        "evidence_chars": len(terms.text),
    }
    if args.evidence_out:
        result["evidence_out"] = args.evidence_out
    else:
        result["evidence_preview"] = terms.text[:2000]

    if args.facts:
        import os

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            print(
                "--facts requiert OPENROUTER_API_KEY dans l'environnement ou .env.",
                file=sys.stderr,
            )
            return 3
        facts = extract_contract_facts(terms, OpenRouterProvider(api_key))
        result["contract_facts"] = facts.model_dump(mode="json")
        if args.arp:
            arp = build_arp(args.tool_name, args.iag_type, facts)
            result["arp"] = arp.model_dump(mode="json")

    _print_yaml(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
