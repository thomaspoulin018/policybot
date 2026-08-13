from datetime import date

import pytest
from pydantic import ValidationError

from policybot.intake.schema import DemandeIAG, TypeIagInconnuError

from tests.intake.conftest import DEMANDE_MINIMALE


def demande(**overrides) -> DemandeIAG:
    return DemandeIAG(**{**DEMANDE_MINIMALE, **overrides})


def test_une_reponse_obligatoire_vide_est_refusee():
    with pytest.raises(ValidationError, match="obligatoire"):
        demande(besoin_affaires="   ")


def test_la_description_des_donnees_joint_cases_cochees_et_texte_libre():
    d = demande(
        data_checked=["Information déjà publique", "Documents internes de travail"],
        data_free_text="communiqués publiés sur le site institutionnel",
    )
    assert d.description_donnees() == (
        "Information déjà publique; Documents internes de travail; "
        "communiqués publiés sur le site institutionnel"
    )


def test_l_usage_input_reprend_le_mode_et_l_usage_des_resultats():
    d = demande(
        mode="api",
        nb_utilisateurs=8,
        result_use_checked=["Prise de décision"],
        result_use_free_text="validation humaine avant diffusion",
        automated_decisions=True,
    )
    usage = d.usage_input()

    assert usage["mode"] == ["api"]
    assert usage["nb_utilisateurs"] == 8
    assert usage["automated_decisions"] is True
    assert usage["result_use"] == ["Prise de décision", "validation humaine avant diffusion"]


def test_le_mode_absent_retombe_sur_prompt():
    assert demande().usage_input()["mode"] == ["prompt"]


def test_les_entrees_orchestrateur_portent_la_demande_et_un_seul_usage():
    entrees = demande().vers_entrees_orchestrateur(numero="IAG-2026-abc123")

    assert entrees.request.numero == "IAG-2026-abc123"
    assert entrees.request.demandeur == "Marie Tremblay"
    assert entrees.tool_name == "ChatGPT"
    assert len(entrees.usage_inputs) == 1
    assert entrees.qualification.besoin_affaires == DEMANDE_MINIMALE["besoin_affaires"]


def test_l_identite_d_offre_est_resolue_a_partir_des_reponses():
    entrees = demande(
        version_plan_tarifaire="Enterprise",
        contract_version="MCA-2026",
        jurisdiction="Québec, Canada",
    ).vers_entrees_orchestrateur()

    offre = entrees.offering
    assert offre.product == "ChatGPT"
    assert offre.plan == "Enterprise"
    # Un plan Enterprise implique une offre gérée et un contrat institutionnel.
    assert offre.deployment_mode == "managed_saas"
    assert offre.contract_type == "institutional_agreement"
    assert offre.contract_version == "MCA-2026"
    assert offre.jurisdiction == "Québec, Canada"


def test_un_outil_hors_registre_sans_type_est_refuse():
    with pytest.raises(TypeIagInconnuError):
        demande(tool_name="Outil maison inconnu").vers_entrees_orchestrateur()


def test_un_outil_hors_registre_avec_type_declare_est_accepte():
    entrees = demande(
        tool_name="Outil maison inconnu",
        tool_type_override="souveraine",
    ).vers_entrees_orchestrateur()

    assert entrees.iag_type == "souveraine"
    assert entrees.offering.deployment_mode == "sovereign_hosted"
