"""Diagnostic local d'une recherche réelle, avec réponse brute non masquée."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from policybot.contract.criteres import CRITERIA_SEARCH_BY_ID, SEARCH_DEFAULTS
from policybot.contract.offering import build_offering_identity
from policybot.contract.exa import _identity_values


def _as_dict(value):
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return {
            key: _as_dict(item) if not isinstance(item, (str, int, float, bool, type(None))) else item
            for key, item in vars(value).items()
        }
    if isinstance(value, (list, tuple)):
        return [_as_dict(item) for item in value]
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--critere", default="A04", choices=sorted(CRITERIA_SEARCH_BY_ID))
    parser.add_argument("--tool", default="ChatGPT")
    parser.add_argument("--vendor", default="OpenAI")
    parser.add_argument("--plan", default="Enterprise")
    parser.add_argument("--type")
    args = parser.parse_args()
    load_dotenv()
    key = os.environ.get("EXA_API_KEY")
    if not key:
        raise SystemExit("EXA_API_KEY est absent")
    from exa_py import Exa

    definition = CRITERIA_SEARCH_BY_ID[args.critere]
    offering = build_offering_identity(
        args.tool, "publique", vendor=args.vendor, plan=args.plan,
        deployment_mode="managed_saas", contract_type="institutional_agreement",
    )
    query = definition.render_query(
        **_identity_values(args.tool, args.vendor, offering)
    )
    contents = dict(definition.exa.contents)
    contents["summary"] = {
        "query": SEARCH_DEFAULTS.prompts["per_page_instruction"].format(
            question=definition.question
        ),
        "schema": SEARCH_DEFAULTS.schemas["per_page"],
    }
    response = Exa(key).search(
        query,
        num_results=definition.exa.num_results,
        type=args.type or definition.exa.type,
        output_schema=SEARCH_DEFAULTS.schemas["global"],
        contents=contents,
    )
    search_type = args.type or definition.exa.type
    target = Path("tmp") / f"exa_raw_{definition.id}_{search_type}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_as_dict(response), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(target)


if __name__ == "__main__":
    main()
