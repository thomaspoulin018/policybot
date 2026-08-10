import io
import json

import pytest

from policybot.cli import main
from policybot.intake.formulaire import formulaire
from policybot.interview.orchestrator import Interview
from policybot.llm.fake import FakeLLMProvider
from policybot.models import CriterionCitation, CriterionFinding
from policybot.preapproved.store import PreApprovedStore

from tests.helpers.forms import FIXTURE, colonne_index, ecrire_export, lignes


def lancer(*argv) -> tuple[int, str]:
    flux = io.StringIO()
    code = main(list(argv), flux=flux)
    return code, flux.getvalue()


def _classification() -> dict:
    return {
        "already_public": True,
        "contains_personal_info": False,
        "strategic_sensitive": False,
        "internal_nonpublic": False,
        "highly_sensitive_secret": False,
        "confidence": 0.9,
    }


def _finding() -> CriterionFinding:
    return CriterionFinding(
        id="A01", partie="A", category="Catégorie", criterion="Localisation",
        question="Où ?", answer="Au Canada.", inherent_risk="M",
        justification="À confirmer.", cost_dollars=0.02,
        citations=[CriterionCitation(
            url="https://vendor.test/data",
            text="Data is hosted in Canada.",
            anchored=True,
        )],
    )


def test_devis_formulaire_imprime_les_trente_cinq_questions():
    code, sortie = lancer("devis-formulaire")

    assert code == 0
    for question in formulaire().questions:
        assert question.intitule in sortie
        assert f"champ  : {question.champ}" in sortie
    assert "35 questions." in sortie


def test_dry_run_lit_les_demandes_et_affiche_l_identite_d_offre():
    code, sortie = lancer("ingerer", str(FIXTURE), "--dry-run")

    assert code == 0
    assert "3 réponse(s) lue(s), 3 demande(s) valide(s), 0 rejetée(s)" in sortie
    for etiquette in ("vendor", "product", "plan", "deployment_mode", "contract_type"):
        assert sortie.count(f"{etiquette:<16}:") == 3
    assert "OpenAI" in sortie and "public_saas" in sortie and "consumer_terms" in sortie
    assert "aucune recherche lancée" in sortie


def test_dry_run_n_instancie_aucun_orchestrateur(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("--dry-run ne doit rien appeler")

    monkeypatch.setattr("policybot.interview.factory.default_interview", interdit)
    monkeypatch.setattr("policybot.contract.exa.search_criteria_with_exa", interdit)

    code, _ = lancer("ingerer", str(FIXTURE), "--dry-run")

    assert code == 0


def test_une_demande_rejetee_donne_un_code_de_sortie_non_nul(tmp_path):
    lignes_ = lignes()
    lignes_[1][colonne_index("urgence_percue")] = "Bof"
    export = ecrire_export(tmp_path / "reponses.xlsx", lignes_=lignes_)

    code, sortie = lancer("ingerer", str(export), "--dry-run")

    assert code == 1
    assert "ligne 3 rejetée" in sortie
    assert "2 demande(s) valide(s), 1 rejetée(s)" in sortie


def test_un_fichier_absent_est_signale_sans_trace_d_exception(tmp_path):
    code, _ = lancer("ingerer", str(tmp_path / "aucun.xlsx"), "--dry-run")

    assert code == 2


def test_ingerer_produit_un_dossier_par_demande(tmp_path, monkeypatch):
    interview = Interview(
        llm=FakeLLMProvider(json_responses=[_classification()] * 3),
        store=PreApprovedStore(str(tmp_path / "pb.db")),
        exa_search=lambda tool_name, offering: [_finding()],
    )
    monkeypatch.setattr(
        "policybot.interview.factory.default_interview", lambda *a, **k: interview
    )

    code, sortie = lancer(
        "ingerer", str(FIXTURE),
        "--sortie-docx", str(tmp_path / "docx"),
        "--sortie-pdf", str(tmp_path / "pdf"),
        "--sortie-json", str(tmp_path / "json"),
    )

    assert code == 0
    assert "coût Exa total : 0.06 $" in sortie
    assert len(list((tmp_path / "docx").glob("*.docx"))) == 3
    assert len(list((tmp_path / "pdf").glob("*.pdf"))) == 3

    constats = sorted((tmp_path / "json").glob("*.json"))
    assert len(constats) == 3
    charge = json.loads(constats[0].read_text(encoding="utf-8"))
    assert charge[0]["id"] == "A01"
    assert charge[0]["citations"][0]["text"] == "Data is hosted in Canada."


def test_une_demande_en_echec_n_arrete_pas_le_lot(tmp_path, monkeypatch):
    def exa_qui_plante(tool_name, offering):
        if tool_name == "ChatGPT":
            raise RuntimeError("recherche indisponible")
        return [_finding()]

    interview = Interview(
        llm=FakeLLMProvider(json_responses=[_classification()] * 3),
        store=PreApprovedStore(str(tmp_path / "pb.db")),
        exa_search=exa_qui_plante,
    )
    monkeypatch.setattr(
        "policybot.interview.factory.default_interview", lambda *a, **k: interview
    )

    code, sortie = lancer(
        "ingerer", str(FIXTURE),
        "--sortie-docx", str(tmp_path / "docx"),
        "--sortie-pdf", str(tmp_path / "pdf"),
        "--sortie-json", str(tmp_path / "json"),
    )

    assert code == 1
    assert "échec : RuntimeError" in sortie
    assert len(list((tmp_path / "docx").glob("*.docx"))) == 2


def test_une_commande_inconnue_est_refusee():
    with pytest.raises(SystemExit):
        main(["inventer"], flux=io.StringIO())
