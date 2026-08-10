from pathlib import Path

import pytest

from policybot.intake.formulaire import formulaire
from policybot.intake.reponses import lire_export

from tests.helpers.forms import FIXTURE, ecrire_export, entetes, lignes


def question(champ: str):
    return next(q for q in formulaire().questions if q.champ == champ)


def colonne(champ: str) -> int:
    return entetes().index(question(champ).intitule)


@pytest.fixture
def export(tmp_path: Path):
    def _export(entetes_=None, lignes_=None) -> Path:
        return ecrire_export(tmp_path / "reponses.xlsx", entetes_, lignes_)

    return _export


def test_la_fixture_livree_donne_trois_demandes_sans_rejet():
    lot = lire_export(FIXTURE)

    assert lot.lignes_lues == 3
    assert len(lot.demandes) == 3
    assert lot.rejets == []
    assert lot.colonnes_manquantes == []


def test_la_fixture_committee_correspond_au_code_qui_la_produit(export):
    attendu = lire_export(export())
    livree = lire_export(FIXTURE)

    assert [d.model_dump() for d in livree.demandes] == [d.model_dump() for d in attendu.demandes]


def test_les_colonnes_techniques_de_forms_sont_ignorees_sans_bruit():
    assert lire_export(FIXTURE).colonnes_ignorees == []


def test_une_colonne_inconnue_est_ignoree_mais_signalee(export):
    entetes_ = entetes() + ["Commentaire libre du demandeur"]
    lignes_ = [ligne + ["peu importe"] for ligne in lignes()]

    lot = lire_export(export(entetes_, lignes_))

    assert lot.colonnes_ignorees == ["Commentaire libre du demandeur"]
    assert len(lot.demandes) == 3


def test_les_choix_multiples_sont_redecoupes():
    lot = lire_export(FIXTURE)

    assert lot.demandes[2].data_checked == [
        "Information déjà publique",
        "Documents internes de travail",
    ]


def test_les_libelles_de_choix_sont_traduits_en_valeurs_de_schema():
    premiere, _, troisieme = lire_export(FIXTURE).demandes

    assert premiere.deployment_mode == "public_saas"
    assert premiere.contract_type == "consumer_terms"
    assert premiere.niveau_maitrise_ti == "intermédiaire"
    assert troisieme.mode == "api"
    assert troisieme.mode_acquisition == "seao"
    assert troisieme.tool_type_override == "publique"


def test_les_oui_non_deviennent_des_booleens(export):
    lignes_ = lignes()
    lignes_[0][colonne("automated_decisions")] = "Oui"

    lot = lire_export(export(lignes_=lignes_))

    assert lot.demandes[0].automated_decisions is True
    assert lot.demandes[1].automated_decisions is False


def test_les_dates_et_les_nombres_sont_convertis():
    premiere = lire_export(FIXTURE).demandes[0]

    assert premiere.contract_effective_date.isoformat() == "2026-07-01"
    assert premiere.nb_utilisateurs_vises == 25


def test_l_ordre_des_colonnes_n_a_pas_d_importance(export):
    ordre = list(reversed(range(len(entetes()))))
    entetes_ = [entetes()[i] for i in ordre]
    lignes_ = [[ligne[i] for i in ordre] for ligne in lignes()]

    lot = lire_export(export(entetes_, lignes_))

    assert [d.tool_name for d in lot.demandes] == ["ChatGPT", "Microsoft Copilot Entreprise", "Gemini"]


def test_un_intitule_qui_derive_s_apparie_quand_meme(export):
    entetes_ = entetes()
    index = colonne("unite")
    entetes_[index] = "  UNITE   ADMINISTRATIVE.  "

    lot = lire_export(export(entetes_))

    assert lot.colonnes_manquantes == []
    assert lot.demandes[0].unite == "Direction des services administratifs"


def test_une_colonne_obligatoire_absente_rejette_chaque_demande_avec_son_motif(export):
    index = colonne("besoin_affaires")
    entetes_ = [e for i, e in enumerate(entetes()) if i != index]
    lignes_ = [[c for i, c in enumerate(ligne) if i != index] for ligne in lignes()]

    lot = lire_export(export(entetes_, lignes_))

    assert lot.demandes == []
    assert len(lot.rejets) == 3
    assert [r.ligne for r in lot.rejets] == [2, 3, 4]
    assert all(question("besoin_affaires").intitule in r.motif for r in lot.rejets)


def test_une_colonne_facultative_absente_laisse_passer_les_demandes(export):
    index = colonne("duree_contrat")
    entetes_ = [e for i, e in enumerate(entetes()) if i != index]
    lignes_ = [[c for i, c in enumerate(ligne) if i != index] for ligne in lignes()]

    lot = lire_export(export(entetes_, lignes_))

    assert len(lot.demandes) == 3
    assert lot.demandes[0].duree_contrat == ""
    assert question("duree_contrat").intitule in lot.colonnes_manquantes


def test_une_ligne_illisible_est_rejetee_et_les_autres_passent(export):
    lignes_ = lignes()
    lignes_[1][colonne("urgence_percue")] = "Bof"

    lot = lire_export(export(lignes_=lignes_))

    assert len(lot.demandes) == 2
    assert len(lot.rejets) == 1
    assert lot.rejets[0].ligne == 3
    assert "hors des choix proposés" in lot.rejets[0].motif


def test_une_reponse_obligatoire_vide_rejette_la_seule_ligne_concernee(export):
    lignes_ = lignes()
    lignes_[0][colonne("data_free_text")] = ""

    lot = lire_export(export(lignes_=lignes_))

    assert len(lot.demandes) == 2
    assert lot.rejets[0].motif == "réponse invalide ou manquante pour : data_free_text"


def test_les_motifs_de_rejet_ne_citent_pas_les_reponses_libres(export):
    lignes_ = lignes()
    secret = "prévisions budgétaires confidentielles"
    lignes_[0][colonne("data_free_text")] = secret
    lignes_[0][colonne("nb_utilisateurs_vises")] = "pas un nombre"

    lot = lire_export(export(lignes_=lignes_))

    assert len(lot.rejets) == 1
    assert secret not in lot.rejets[0].motif
    assert "pas un nombre" not in lot.rejets[0].motif


def test_les_lignes_vides_sont_ignorees(export):
    lignes_ = lignes() + [[""] * len(entetes())]

    lot = lire_export(export(lignes_=lignes_))

    assert lot.lignes_lues == 3
    assert len(lot.demandes) == 3


def test_un_fichier_absent_est_signale_clairement(tmp_path):
    with pytest.raises(FileNotFoundError, match="introuvable"):
        lire_export(tmp_path / "aucun.xlsx")
