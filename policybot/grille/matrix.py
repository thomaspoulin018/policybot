from policybot.models import DataClass, IagType, MatrixResult

# MCN guide — Cadre d'utilisation de l'IA générative (slide 4).
_MATRIX: dict[DataClass, dict[IagType, MatrixResult]] = {
    "Non classifié": {
        "publique": "PERMIS", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé A": {
        "publique": "INTERDIT", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé B": {
        "publique": "INTERDIT", "circuit_ferme": "PERMIS",
        "souveraine": "PERMIS", "gouvernementale": "PERMIS",
    },
    "Protégé C": {
        "publique": "INTERDIT", "circuit_ferme": "INTERDIT",
        "souveraine": "INTERDIT", "gouvernementale": "OBLIGATOIRE",
    },
}


def evaluate_matrix(data_classification: DataClass, iag_type: IagType) -> MatrixResult:
    """Hard gate: (data class × tool type) → PERMIS / INTERDIT / OBLIGATOIRE.

    Sanctioned MCN policy. No caller may override an INTERDIT result.
    """
    return _MATRIX[data_classification][iag_type]
