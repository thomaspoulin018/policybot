"""Test manuel de Tavily Extract via un fichier YAML.

Usage:
    python scripts/test_extract.py [configs/tavily_extract/test.yaml]
"""

from pathlib import Path
import os
import sys

from dotenv import load_dotenv
from tavily import TavilyClient
import yaml

DEFAULT_CONFIG_PATH = Path("configs/tavily_extract/test.yaml")
EXTRACT_CONFIG_KEYS = (
    "query",
    "chunks_per_source",
    "extract_depth",
    "include_images",
    "include_favicon",
    "format",
    "timeout",
    "include_usage",
)


def load_config(config_path: Path) -> dict:
    """Charge une configuration Tavily Extract depuis un fichier YAML."""
    with config_path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    if not isinstance(config, dict):
        raise ValueError("La configuration YAML doit contenir un objet cle/valeur.")

    urls = config.get("urls")
    if isinstance(urls, str):
        if not urls.strip():
            raise ValueError("La configuration YAML doit contenir au minimum: urls")
    elif (
        not isinstance(urls, list)
        or not urls
        or not all(isinstance(url, str) and url.strip() for url in urls)
    ):
        raise ValueError("La configuration YAML doit contenir au minimum: urls")

    return config


def build_extract_kwargs(config: dict) -> dict:
    """Conserve seulement les options Tavily Extract definies dans la config."""
    return {
        key: config[key]
        for key in EXTRACT_CONFIG_KEYS
        if key in config and config[key] is not None
    }


def main() -> int:
    load_dotenv()

    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CONFIG_PATH
    try:
        config = load_config(config_path)
    except (FileNotFoundError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f"Erreur de configuration: {exc}", file=sys.stderr)
        return 1

    api_key = config.get("api_key") or os.getenv("TAVILY_API_KEY")
    if not api_key:
        print(
            "Erreur: definis TAVILY_API_KEY dans .env ou api_key dans le YAML.",
            file=sys.stderr,
        )
        return 1

    tavily_client = TavilyClient(api_key=api_key)
    try:
        response = tavily_client.extract(config["urls"], **build_extract_kwargs(config))
    except Exception as exc:  # noqa: BLE001 - script de diagnostic manuel
        print(f"Extraction Tavily echouee: {exc}", file=sys.stderr)
        return 1
    finally:
        tavily_client.close()

    print(yaml.safe_dump(response, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
