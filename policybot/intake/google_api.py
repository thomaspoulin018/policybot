"""Client REST minimal pour Google Forms.

Le module concentre les deux seuls effets réseau de l'intégration : le flux
OAuth utilisateur et les appels HTTP à l'API Forms. Un transport injectable
permet de tester tous les appels sans jeton ni accès réseau.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CREDENTIALS_PATH = _PROJECT_ROOT / "credentials.json"
DEFAULT_TOKEN_PATH = _PROJECT_ROOT / "token.json"
API_BASE_URL = "https://forms.googleapis.com/v1"
SCOPES = (
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
)

Transport = Callable[[str, str, dict | None, dict[str, str]], dict]


class GoogleFormsError(RuntimeError):
    """Échec lisible de l'authentification ou de l'API Google Forms."""


class GoogleFormsAuthError(GoogleFormsError):
    """Le jeton OAuth n'a pas pu être obtenu."""


class GoogleFormsAPIError(GoogleFormsError):
    """Une requête HTTP vers l'API Forms a échoué."""


class GoogleFormsClient:
    """Quatre opérations Google Forms, sans dépendre du client API Google."""

    def __init__(
        self,
        *,
        credentials_path: str | Path = DEFAULT_CREDENTIALS_PATH,
        token_path: str | Path = DEFAULT_TOKEN_PATH,
        transport: Transport | None = None,
    ) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._transport = transport
        self._credentials = None

    def creer_formulaire(self, titre: str) -> dict:
        """Crée volontairement un formulaire non publié."""
        return self._appeler(
            "POST",
            "/forms",
            corps={"info": {"title": titre}},
            query={"unpublished": "true"},
        )

    def appliquer_lot(self, form_id: str, requetes: list[dict]) -> dict:
        """Applique le catalogue et demande le formulaire résultant."""
        return self._appeler(
            "POST",
            f"/forms/{urllib.parse.quote(form_id, safe='')}:batchUpdate",
            corps={"requests": requetes, "includeFormInResponse": True},
        )

    def publier(self, form_id: str) -> dict:
        """Publie le formulaire et active explicitement la collecte."""
        return self._appeler(
            "POST",
            f"/forms/{urllib.parse.quote(form_id, safe='')}:setPublishSettings",
            corps={
                "publishSettings": {
                    "publishState": {
                        "isPublished": True,
                        "isAcceptingResponses": True,
                    }
                },
                "updateMask": "publishState",
            },
        )

    def lister_reponses(self, form_id: str) -> dict:
        """Suit la pagination et rend un document JSON unique rejouable."""
        responses: list[dict] = []
        page_token: str | None = None
        while True:
            query = {"pageSize": "5000"}
            if page_token:
                query["pageToken"] = page_token
            page = self._appeler(
                "GET",
                f"/forms/{urllib.parse.quote(form_id, safe='')}/responses",
                query=query,
            )
            contenu = page.get("responses", [])
            if not isinstance(contenu, list):
                raise GoogleFormsAPIError(
                    "Réponse invalide de Google Forms : « responses » n'est pas une liste."
                )
            responses.extend(contenu)
            page_token = page.get("nextPageToken")
            if not page_token:
                break
        return {"responses": responses}

    def _appeler(
        self,
        methode: str,
        chemin: str,
        *,
        corps: dict | None = None,
        query: dict[str, str] | None = None,
    ) -> dict:
        url = API_BASE_URL + chemin
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers = {"Accept": "application/json"}
        if self._transport is None:
            headers["Authorization"] = f"Bearer {self._jeton()}"
            return self._envoyer_urllib(methode, url, corps, headers)
        try:
            resultat = self._transport(methode, url, corps, headers)
        except GoogleFormsError:
            raise
        except Exception as erreur:
            raise GoogleFormsAPIError(
                f"Transport Google Forms en échec : {type(erreur).__name__} — {erreur}"
            ) from erreur
        if not isinstance(resultat, dict):
            raise GoogleFormsAPIError("Le transport Google Forms n'a pas rendu un objet JSON.")
        return resultat

    def _jeton(self) -> str:
        if self._credentials is None:
            self._credentials = self._charger_credentials()
        token = getattr(self._credentials, "token", None)
        if not token:
            raise GoogleFormsAuthError("Le flux OAuth n'a rendu aucun jeton d'accès.")
        return token

    def _charger_credentials(self):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as erreur:
            raise GoogleFormsAuthError(
                "Dépendances OAuth absentes. Installe l'extra avec "
                "« pip install -e \".[google]\" »."
            ) from erreur

        creds = None
        if self.token_path.is_file():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self.token_path), list(SCOPES)
                )
            except (OSError, ValueError):
                creds = None
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
            else:
                self._sauvegarder_credentials(creds)
                return creds
        if not self.credentials_path.is_file():
            raise GoogleFormsAuthError(
                f"Identifiants OAuth introuvables : {self.credentials_path}"
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(self.credentials_path), list(SCOPES)
            )
            creds = flow.run_local_server(port=0)
        except Exception as erreur:
            raise GoogleFormsAuthError(
                f"Consentement OAuth impossible : {type(erreur).__name__} — {erreur}"
            ) from erreur
        self._sauvegarder_credentials(creds)
        return creds

    def _sauvegarder_credentials(self, creds) -> None:
        try:
            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
        except OSError as erreur:
            raise GoogleFormsAuthError(
                f"Impossible d'écrire le jeton OAuth {self.token_path} : {erreur}"
            ) from erreur

    @staticmethod
    def _envoyer_urllib(
        methode: str,
        url: str,
        corps: dict | None,
        headers: dict[str, str],
    ) -> dict:
        donnees = None
        if corps is not None:
            donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
            headers = {**headers, "Content-Type": "application/json; charset=utf-8"}
        requete = urllib.request.Request(
            url, data=donnees, headers=headers, method=methode
        )
        try:
            with urllib.request.urlopen(requete, timeout=30) as reponse:
                brut = reponse.read()
        except urllib.error.HTTPError as erreur:
            brut_erreur = erreur.read().decode("utf-8", errors="replace")
            message = brut_erreur[:500]
            try:
                message = json.loads(brut_erreur).get("error", {}).get("message", message)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise GoogleFormsAPIError(
                f"Google Forms a refusé la requête (HTTP {erreur.code}) : {message}"
            ) from erreur
        except (urllib.error.URLError, TimeoutError, OSError) as erreur:
            raison = getattr(erreur, "reason", erreur)
            raise GoogleFormsAPIError(f"Google Forms est injoignable : {raison}") from erreur
        if not brut:
            return {}
        try:
            resultat = json.loads(brut.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as erreur:
            raise GoogleFormsAPIError(
                "Google Forms a rendu une réponse qui n'est pas un JSON valide."
            ) from erreur
        if not isinstance(resultat, dict):
            raise GoogleFormsAPIError("Google Forms n'a pas rendu un objet JSON.")
        return resultat
