from pathlib import Path

import pytest

from policybot.contract.criteres import (
    CRITERIA,
    CRITERIA_SEARCHES,
    SEARCH_DEFAULTS,
    load_criterion_searches,
)


def _copier_catalogue(destination: Path) -> None:
    for path in Path("configs/recherche_criteres").glob("*.yaml"):
        (destination / path.name).write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )


def test_catalogue_respecte_les_invariants_structurels():
    ids = [item.id for item in CRITERIA]
    assert len(ids) == len(set(ids))
    assert {item.partie for item in CRITERIA} == {"A", "B"}
    assert all(item.id.startswith(item.partie) for item in CRITERIA)
    assert CRITERIA_SEARCHES == tuple(item for item in CRITERIA if item.exa is not None)
    assert all(item.question.strip() for item in CRITERIA)
    assert SEARCH_DEFAULTS.schemas["global"]["properties"]["inherent_risk"]["enum"] == [
        "F", "M", "E"
    ]


def test_ajouter_un_fichier_sans_exa_suffit_a_ajouter_un_critere(tmp_path: Path):
    _copier_catalogue(tmp_path)
    (tmp_path / "A99-nouveau.yaml").write_text(
        """version: 2
id: A99
partie: A
category: Catégorie ajoutée
criterion: Critère ajouté
question: Question ajoutée ?
""",
        encoding="utf-8",
    )

    _, criteres = load_criterion_searches(
        tmp_path, Path("configs/recherche_defaults.yaml")
    )

    ajoute = next(item for item in criteres if item.id == "A99")
    assert ajoute.exa is None


def test_identifiant_incompatible_avec_la_partie_est_rejete(tmp_path: Path):
    _copier_catalogue(tmp_path)
    target = tmp_path / "A01-localisation-serveurs.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("id: A01", "id: B99"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="appartient à la partie A"):
        load_criterion_searches(tmp_path, "configs/recherche_defaults.yaml")


def test_unknown_query_placeholder_is_rejected(tmp_path: Path):
    _copier_catalogue(tmp_path)
    target = tmp_path / "A01-localisation-serveurs.yaml"
    target.write_text(
        target.read_text(encoding="utf-8").replace("{tool}", "{inconnu}"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown query placeholders"):
        load_criterion_searches(tmp_path, "configs/recherche_defaults.yaml")


def test_explicit_paths_override_repository_defaults():
    defaults, searches = load_criterion_searches(
        Path("configs/recherche_criteres"),
        Path("configs/recherche_defaults.yaml"),
    )
    assert defaults.version == 2
    assert searches[0].partie in {"A", "B"}
