import io
import json

import pytest

from policybot.cli import main
from policybot.intake.formulaire import FormulaireInvalideError, formulaire
from policybot.interview.orchestrator import Interview
from policybot.llm import FakeLLMProvider
from policybot.models import CriterionCitation, CriterionFinding

from tests.helpers.forms import (
    configuration_mapping,
    document_reponses,
    ecrire_reponses,
    mapping_questions,
)


def lancer(*argv) -> tuple[int, str]:
    flux = io.StringIO()
    code = main(list(argv), flux=flux)
    return code, flux.getvalue()


@pytest.fixture
def fichier_reponses(tmp_path, monkeypatch):
    chemin_mapping = tmp_path / "formulaire-google.json"
    chemin_mapping.write_text(
        json.dumps(configuration_mapping(), ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(
        "policybot.intake.reponses.DEFAULT_MAPPING_PATH", chemin_mapping
    )
    return ecrire_reponses(tmp_path / "reponses.json")


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


def test_devis_formulaire_imprime_toutes_les_questions():
    code, sortie = lancer("devis-formulaire")

    assert code == 0
    for question in formulaire().questions:
        assert question.intitule in sortie
        assert f"champ  : {question.champ}" in sortie
    assert f"{len(formulaire().questions)} questions." in sortie


def test_devis_formulaire_retourne_un_code_non_nul_si_le_catalogue_est_invalide(
    monkeypatch,
):
    def invalide():
        raise FormulaireInvalideError("catalogue invalide")

    monkeypatch.setattr("policybot.cli.devis", invalide)

    code, sortie = lancer("devis-formulaire")

    assert code == 2
    assert "catalogue invalide" in sortie


def test_creer_formulaire_affiche_uniquement_l_url_publiee(monkeypatch):
    appels = []

    def creer(*, force=False):
        appels.append(force)
        return {"responder_uri": "https://forms.google.test/nouveau"}

    monkeypatch.setattr("policybot.cli.creer_formulaire_google", creer)

    code, sortie = lancer("creer-formulaire", "--force")

    assert code == 0
    assert appels == [True]
    assert "l'URL diffusée sera perdue" in sortie
    assert "réponses déjà collectées deviendront illisibles" in sortie
    assert "créé et publié" in sortie
    assert "https://forms.google.test/nouveau" in sortie


def test_recuperer_reponses_affiche_le_compte_et_le_chemin(tmp_path, monkeypatch):
    sortie_json = tmp_path / "reponses.json"
    monkeypatch.setattr(
        "policybot.cli.recuperer_reponses_google",
        lambda sortie: (2, sortie_json),
    )

    code, sortie = lancer("recuperer-reponses", "-o", str(sortie_json))

    assert code == 0
    assert "2 réponse(s) téléchargée(s)" in sortie
    assert str(sortie_json) in sortie


def test_dry_run_lit_les_demandes_et_affiche_l_identite_d_offre(fichier_reponses):
    code, sortie = lancer("ingerer", str(fichier_reponses), "--dry-run")

    assert code == 0
    assert "3 réponse(s) lue(s), 3 demande(s) valide(s), 0 rejetée(s)" in sortie
    for etiquette in ("vendor", "product", "plan", "deployment_mode", "contract_type"):
        assert sortie.count(f"{etiquette:<16}:") == 3
    assert "OpenAI" in sortie and "public_saas" in sortie and "consumer_terms" in sortie
    assert "aucune recherche lancée" in sortie


def test_dry_run_n_instancie_aucun_orchestrateur(monkeypatch, fichier_reponses):
    def interdit(*args, **kwargs):
        raise AssertionError("--dry-run ne doit rien appeler")

    monkeypatch.setattr("policybot.interview.factory.default_interview", interdit)
    monkeypatch.setattr("policybot.contract.exa.search_criteria_with_exa", interdit)

    code, _ = lancer("ingerer", str(fichier_reponses), "--dry-run")

    assert code == 0


def test_une_demande_rejetee_donne_un_code_de_sortie_non_nul(
    tmp_path, fichier_reponses
):
    document = document_reponses()
    question_id = next(
        cle for cle, champ in mapping_questions().items() if champ == "urgence_percue"
    )
    document["responses"][1]["answers"][question_id]["textAnswers"]["answers"][0][
        "value"
    ] = "Bof"
    export = ecrire_reponses(tmp_path / "reponses-invalides.json", document)

    code, sortie = lancer("ingerer", str(export), "--dry-run")

    assert code == 1
    assert "réponse response-2 rejetée" in sortie
    assert "2 demande(s) valide(s), 1 rejetée(s)" in sortie


def test_un_fichier_absent_est_signale_sans_trace_d_exception(tmp_path):
    code, _ = lancer("ingerer", str(tmp_path / "aucun.json"), "--dry-run")

    assert code == 2


def test_ingerer_produit_un_dossier_par_demande(
    tmp_path, monkeypatch, fichier_reponses
):
    interview = Interview(
        llm=FakeLLMProvider(json_responses=[_classification()] * 3),
        exa_search=lambda tool_name, offering: [_finding()],
    )
    monkeypatch.setattr(
        "policybot.interview.factory.default_interview", lambda *a, **k: interview
    )

    code, sortie = lancer(
        "ingerer", str(fichier_reponses),
        "--sortie-docx", str(tmp_path / "docx"),
        "--sortie-json", str(tmp_path / "json"),
    )

    assert code == 0
    assert "coût Exa total : 0.06 $" in sortie
    documents = list((tmp_path / "docx").glob("*.docx"))
    assert len(documents) == 6
    assert len([path for path in documents if path.name.endswith("-fiche.docx")]) == 3
    assert len([path for path in documents if path.name.endswith("-grille.docx")]) == 3

    constats = sorted((tmp_path / "json").glob("*.json"))
    assert len(constats) == 3
    charge = json.loads(constats[0].read_text(encoding="utf-8"))
    assert charge[0]["id"] == "A01"
    assert charge[0]["citations"][0]["text"] == "Data is hosted in Canada."


def test_une_demande_en_echec_n_arrete_pas_le_lot(
    tmp_path, monkeypatch, fichier_reponses
):
    def exa_qui_plante(tool_name, offering):
        if tool_name == "ChatGPT":
            raise RuntimeError("recherche indisponible")
        return [_finding()]

    interview = Interview(
        llm=FakeLLMProvider(json_responses=[_classification()] * 3),
        exa_search=exa_qui_plante,
    )
    monkeypatch.setattr(
        "policybot.interview.factory.default_interview", lambda *a, **k: interview
    )

    code, sortie = lancer(
        "ingerer", str(fichier_reponses),
        "--sortie-docx", str(tmp_path / "docx"),
        "--sortie-json", str(tmp_path / "json"),
    )

    assert code == 1
    assert "échec : RuntimeError" in sortie
    assert len(list((tmp_path / "docx").glob("*.docx"))) == 4


def test_une_commande_inconnue_est_refusee():
    with pytest.raises(SystemExit):
        main(["inventer"], flux=io.StringIO())
