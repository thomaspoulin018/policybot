from __future__ import annotations
import os
import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "known_tools.yaml")


def load_known_tools(path: str | None = None) -> list[str]:
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return list(raw)
