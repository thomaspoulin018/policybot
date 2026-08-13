from urllib.parse import parse_qs, urlparse

from policybot.intake.google_api import GoogleFormsClient


def test_lister_reponses_suit_toute_la_pagination():
    appels = []

    def transport(methode, url, corps, headers):
        appels.append((methode, url, corps))
        token = parse_qs(urlparse(url).query).get("pageToken", [None])[0]
        if token is None:
            return {"responses": [{"responseId": "r1"}], "nextPageToken": "suite"}
        return {"responses": [{"responseId": "r2"}]}

    client = GoogleFormsClient(transport=transport)

    assert client.lister_reponses("form/id") == {
        "responses": [{"responseId": "r1"}, {"responseId": "r2"}]
    }
    assert [appel[0] for appel in appels] == ["GET", "GET"]
    assert "form%2Fid/responses" in appels[0][1]
    assert "pageToken=suite" in appels[1][1]


def test_publier_envoie_les_deux_indicateurs_requis():
    appels = []

    def transport(methode, url, corps, headers):
        appels.append((methode, url, corps))
        return {}

    GoogleFormsClient(transport=transport).publier("form-1")

    methode, url, corps = appels[0]
    assert methode == "POST"
    assert url.endswith("/forms/form-1:setPublishSettings")
    assert corps["publishSettings"]["publishState"] == {
        "isPublished": True,
        "isAcceptingResponses": True,
    }
    assert corps["updateMask"] == "publishState"
