import pytest
from policybot.grille.matrix import evaluate_matrix

EXPECTED = {
    ("Non classifié", "publique"): "PERMIS",
    ("Non classifié", "circuit_ferme"): "PERMIS",
    ("Non classifié", "souveraine"): "PERMIS",
    ("Non classifié", "gouvernementale"): "PERMIS",
    ("Protégé A", "publique"): "INTERDIT",
    ("Protégé A", "circuit_ferme"): "PERMIS",
    ("Protégé A", "souveraine"): "PERMIS",
    ("Protégé A", "gouvernementale"): "PERMIS",
    ("Protégé B", "publique"): "INTERDIT",
    ("Protégé B", "circuit_ferme"): "PERMIS",
    ("Protégé B", "souveraine"): "PERMIS",
    ("Protégé B", "gouvernementale"): "PERMIS",
    ("Protégé C", "publique"): "INTERDIT",
    ("Protégé C", "circuit_ferme"): "INTERDIT",
    ("Protégé C", "souveraine"): "INTERDIT",
    ("Protégé C", "gouvernementale"): "OBLIGATOIRE",
}


@pytest.mark.parametrize("key,expected", EXPECTED.items())
def test_matrix_all_cells(key, expected):
    data_class, iag_type = key
    assert evaluate_matrix(data_class, iag_type) == expected
