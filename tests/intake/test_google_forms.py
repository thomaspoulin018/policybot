import json

import pytest

from policybot.intake.formulaire import formulaire
from policybot.intake.google_api import GoogleFormsClient
from policybot.intake.google_forms import (
    FormulaireGoogleExistantError,
    creer_formulaire_google,
    recuperer_reponses_google,
)


def test_creation_applique_le_lot_publie_puis_ecrit_le_mapping(tmp_path):
    appels = []

    def transport(methode, url, corps, headers):
        appels.append(url)
        if url.endswith("/forms?unpublished=true"):
            return {"formId": "form-123"}
        if url.endswith("/forms/form-123:batchUpdate"):
            compteur = 0
            replies = []
            for requete in corps["requests"]:
                item = requete.get("createItem", {}).get("item", {})
                if "questionItem" in item:
                    compteur += 1
                    replies.append({"createItem": {"questionId": [f"qid-{compteur}"]}})
                else:
                    replies.append({})
            return {
                "replies": replies,
                "form": {"responderUri": "https://forms.google.test/form-123"},
            }
        if url.endswith("/forms/form-123:setPublishSettings"):
            return {"formId": "form-123"}
        raise AssertionError(url)

    chemin = tmp_path / "formulaire-google.json"
    configuration = creer_formulaire_google(
        client=GoogleFormsClient(transport=transport), chemin_mapping=chemin
    )

    assert appels[0].endswith("/forms?unpublished=true")
    assert appels[1].endswith(":batchUpdate")
    assert appels[2].endswith(":setPublishSettings")
    assert len(configuration["questions"]) == len(formulaire().questions)
    assert configuration["questions"]["qid-1"] == formulaire().questions[0].champ
    assert json.loads(chemin.read_text(encoding="utf-8")) == configuration


def test_creation_refuse_d_ecraser_et_affiche_l_ancienne_url(tmp_path):
    chemin = tmp_path / "formulaire-google.json"
    chemin.write_text(
        json.dumps(
            {
                "form_id": "ancien",
                "responder_uri": "https://forms.google.test/ancien",
                "questions": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FormulaireGoogleExistantError, match="forms.google.test/ancien"):
        creer_formulaire_google(
            client=GoogleFormsClient(transport=lambda *args: {}),
            chemin_mapping=chemin,
        )


def test_recuperation_ecrit_le_json_et_retourne_le_compte(tmp_path):
    mapping = tmp_path / "mapping.json"
    mapping.write_text(
        json.dumps({"form_id": "f1", "questions": {"q1": "demandeur"}}),
        encoding="utf-8",
    )

    def transport(methode, url, corps, headers):
        return {"responses": [{"responseId": "r1"}]}

    sortie = tmp_path / "reponses.json"
    compte, chemin = recuperer_reponses_google(
        sortie,
        client=GoogleFormsClient(transport=transport),
        chemin_mapping=mapping,
    )

    assert compte == 1
    assert chemin == sortie
    assert json.loads(sortie.read_text(encoding="utf-8"))["responses"][0][
        "responseId"
    ] == "r1"
