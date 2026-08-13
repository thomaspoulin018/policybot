"""Vérifie que la phase 0 de la bascule Google Forms est réellement terminée.

Six contrôles, dans l'ordre où ils peuvent échouer. Aucun effet de bord :
aucun formulaire n'est créé, aucun n'est modifié. Le dernier contrôle
interroge l'API avec un identifiant inexistant — un 404 prouve que le jeton
est bon et que l'API est activée, sans rien laisser dans le Drive du compte.

    python scripts/verifier_google.py

Le premier passage ouvre le navigateur pour le consentement, puis écrit
`token.json`. Les passages suivants réutilisent ce fichier.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


PROJECT_ROOT = Path(__file__).resolve().parent.parent

SCOPES = [
    "https://www.googleapis.com/auth/forms.body",
    "https://www.googleapis.com/auth/forms.responses.readonly",
]

# Identifiant volontairement inexistant : l'API doit répondre 404, ce qui
# prouve l'authentification sans créer ni lire quoi que ce soit de réel.
FORM_ID_INEXISTANT = "1zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"

CONSOLE = "https://console.cloud.google.com"


class EchecControle(Exception):
    """Un contrôle a échoué. Le message dit quoi faire, pas seulement quoi."""


def _ok(message: str) -> None:
    print(f"  [OK]  {message}")


def _detail(message: str) -> None:
    print(f"        {message}")


def controle_1_paquets() -> None:
    """Les deux paquets du flux OAuth sont installés dans le venv."""
    manquants = []
    for module, paquet in (
        ("google.auth", "google-auth"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
    ):
        try:
            __import__(module)
        except ImportError:
            manquants.append(paquet)
    if manquants:
        raise EchecControle(
            "paquets absents du venv : " + ", ".join(manquants) + "\n"
            "        Installe-les :\n"
            "            .\\.venv\\Scripts\\activate\n"
            "            pip install " + " ".join(manquants)
        )
    _ok("google-auth et google-auth-oauthlib installés")


def controle_2_credentials(chemin: Path) -> None:
    """`credentials.json` existe et décrit bien un client de type bureau."""
    if not chemin.is_file():
        raise EchecControle(
            f"{chemin.name} introuvable dans {chemin.parent}\n"
            "        Étapes 1 à 4 du guide : crée un projet Google Cloud,\n"
            "        active l'API Forms, configure l'écran de consentement,\n"
            f"        puis crée un identifiant OAuth « Application de bureau » :\n"
            f"            {CONSOLE}/apis/credentials\n"
            f"        Télécharge le fichier et renomme-le {chemin.name}."
        )
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except json.JSONDecodeError as erreur:
        raise EchecControle(f"{chemin.name} n'est pas un JSON valide : {erreur}")

    if "installed" not in donnees:
        type_trouve = ", ".join(donnees) or "(vide)"
        raise EchecControle(
            f"{chemin.name} ne décrit pas un client « Application de bureau ».\n"
            f"        Clé attendue : « installed ». Clé trouvée : {type_trouve}.\n"
            "        Un client « Application Web » ne convient pas au flux local :\n"
            f"        recrée un identifiant de type Application de bureau sur\n"
            f"            {CONSOLE}/apis/credentials"
        )
    client_id = donnees["installed"].get("client_id", "")
    _ok(f"{chemin.name} valide — client de bureau {client_id[:22]}…")


def controle_3_jeton(chemin_creds: Path, chemin_token: Path):
    """Obtient un jeton : cache, rafraîchissement, puis consentement."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if chemin_token.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(chemin_token), SCOPES)
        except ValueError:
            # Jeton écrit avec d'autres scopes : on repart du consentement.
            creds = None

    if creds and creds.valid:
        _ok(f"jeton valide réutilisé depuis {chemin_token.name}")
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        chemin_token.write_text(creds.to_json(), encoding="utf-8")
        _ok(f"jeton expiré rafraîchi, {chemin_token.name} réécrit")
        return creds

    print("        consentement requis — ouverture du navigateur…")
    flux = InstalledAppFlow.from_client_secrets_file(str(chemin_creds), SCOPES)
    creds = flux.run_local_server(port=0)
    chemin_token.write_text(creds.to_json(), encoding="utf-8")
    _ok(f"consentement accordé, {chemin_token.name} écrit")
    return creds


def controle_4_scopes(creds) -> None:
    """Les deux scopes ont bien été accordés, pas seulement demandés."""
    url = (
        "https://oauth2.googleapis.com/tokeninfo?access_token="
        + urllib.parse.quote(creds.token)
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as reponse:
            infos = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        raise EchecControle(
            f"le jeton est refusé par Google (HTTP {erreur.code}).\n"
            "        Supprime token.json et relance pour reprendre le consentement."
        )

    accordes = set(infos.get("scope", "").split())
    absents = [scope for scope in SCOPES if scope not in accordes]
    if absents:
        raise EchecControle(
            "scopes non accordés :\n"
            + "".join(f"            {scope}\n" for scope in absents)
            + "        Ajoute-les à l'écran de consentement OAuth, supprime\n"
            "        token.json, puis relance ce script."
        )
    _ok("les deux scopes sont accordés (body + responses.readonly)")


def controle_5_api(creds) -> None:
    """L'API Forms est activée sur le projet — vérifié sans effet de bord."""
    requete = urllib.request.Request(
        f"https://forms.googleapis.com/v1/forms/{FORM_ID_INEXISTANT}",
        headers={"Authorization": f"Bearer {creds.token}"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=30):
            pass
    except urllib.error.HTTPError as erreur:
        corps = erreur.read().decode("utf-8", errors="replace")
        if erreur.code == 404:
            # Le seul résultat attendu : authentifié, API active, form absent.
            _ok("API Google Forms activée et joignable")
            return
        if erreur.code == 403 and (
            "SERVICE_DISABLED" in corps or "has not been used" in corps
        ):
            raise EchecControle(
                "l'API Google Forms n'est pas activée sur ce projet.\n"
                "        Étape 2 du guide — active-la ici :\n"
                f"            {CONSOLE}/apis/library/forms.googleapis.com\n"
                "        L'activation prend parfois quelques minutes à se propager."
            )
        if erreur.code == 401:
            raise EchecControle(
                "jeton refusé (401). Supprime token.json et relance."
            )
        raise EchecControle(
            f"réponse inattendue de l'API (HTTP {erreur.code}) :\n"
            f"        {corps[:400]}"
        )
    except urllib.error.URLError as erreur:
        raise EchecControle(f"API injoignable : {erreur.reason}")
    # Un 200 sur un identifiant inventé n'a aucun sens : mieux vaut le dire.
    raise EchecControle(
        "l'API a répondu 200 sur un formulaire inexistant — résultat "
        "incohérent, à examiner avant d'aller plus loin."
    )


def controle_6_gitignore(*chemins: Path) -> None:
    """Les fichiers de secrets sont bien exclus du dépôt.

    Un `credentials.json` commité vaut une fuite d'identifiants : mieux vaut
    l'apprendre ici que dans l'historique git.
    """
    import subprocess

    exposes = []
    for chemin in chemins:
        resultat = subprocess.run(
            ["git", "check-ignore", "-q", chemin.name],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
        )
        # 0 = ignoré, 1 = suivi par git, 128 = hors dépôt.
        if resultat.returncode == 128:
            _detail("hors dépôt git — contrôle sans objet")
            return
        if resultat.returncode != 0:
            exposes.append(chemin.name)

    if exposes:
        raise EchecControle(
            "ces fichiers ne sont PAS ignorés par git : " + ", ".join(exposes) + "\n"
            "        Ajoute-les au .gitignore avant tout commit — ils donnent\n"
            "        un accès complet aux formulaires du compte."
        )
    _ok("credentials.json et token.json sont exclus du dépôt")


def main(argv=None) -> int:
    for canal in (sys.stdout, sys.stderr):
        reconfigure = getattr(canal, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    parseur = argparse.ArgumentParser(
        description="Vérifie les prérequis Google Cloud de la bascule Forms."
    )
    parseur.add_argument(
        "--credentials",
        default=str(PROJECT_ROOT / "credentials.json"),
        help="identifiant OAuth téléchargé depuis la console Google Cloud",
    )
    parseur.add_argument(
        "--token",
        default=str(PROJECT_ROOT / "token.json"),
        help="cache du jeton, écrit après le consentement",
    )
    args = parseur.parse_args(argv)

    chemin_creds = Path(args.credentials)
    chemin_token = Path(args.token)

    print("Vérification de la phase 0 — prérequis Google Cloud")
    print()

    etapes = (
        ("1/6  paquets Python", lambda: controle_1_paquets()),
        ("2/6  credentials.json", lambda: controle_2_credentials(chemin_creds)),
    )
    try:
        for titre, controle in etapes:
            print(titre)
            controle()

        print("3/6  jeton OAuth")
        creds = controle_3_jeton(chemin_creds, chemin_token)

        print("4/6  scopes accordés")
        controle_4_scopes(creds)

        print("5/6  API Forms activée")
        controle_5_api(creds)
    except EchecControle as erreur:
        print(f"  [!!]  {erreur}")
        print()
        print("Phase 0 incomplète. Corrige le point ci-dessus et relance.")
        return 1

    print("6/6  secrets ignorés par git")
    try:
        controle_6_gitignore(chemin_creds, chemin_token)
    except EchecControle as erreur:
        print(f"  [!!]  {erreur}")
        return 1

    print()
    print("Phase 0 terminée : la phase 1 peut commencer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
