from pathlib import Path

import pytest

from policybot.contract.criteres import (
    CRITERIA_SEARCHES,
    SEARCH_DEFAULTS,
    load_criterion_searches,
)
from policybot.criteria import ARP_CRITERIA


def test_repository_contains_exactly_seventeen_valid_criterion_searches():
    assert len(CRITERIA_SEARCHES) == 17
    assert len({item.id for item in CRITERIA_SEARCHES}) == 17
    assert {
        (item.category, item.criterion)
        for item in CRITERIA_SEARCHES if item.partie == "A"
    } == {(category, criterion) for category, criterion, _ in ARP_CRITERIA}
    assert SEARCH_DEFAULTS.schemas["global"]["properties"]["inherent_risk"]["enum"] == ["F", "M", "E"]


def test_unknown_query_placeholder_is_rejected(tmp_path: Path):
    source = Path("configs/recherche_criteres")
    for path in source.glob("*.yaml"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    target = tmp_path / "A01-localisation-serveurs.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("{tool}", "{inconnu}"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown query placeholders"):
        load_criterion_searches(tmp_path, "configs/recherche_defaults.yaml")


def test_explicit_paths_override_repository_defaults(tmp_path: Path):
    defaults, searches = load_criterion_searches(
        Path("configs/recherche_criteres"),
        Path("configs/recherche_defaults.yaml"),
    )
    assert defaults.version == 2
    assert searches[0].id == "A01"
