# Google Forms avec PolicyBot

Ce guide part d'un compte Google sans configuration et mène à un formulaire
publié dont PolicyBot sait télécharger et ingérer les réponses. Pour la boucle
complète et les livrables, voir le [README principal](README.md).

- [Partie 1 — Mise en route](#partie-1--mise-en-route)
- [Partie 2 — Comment ça marche](#partie-2--comment-ça-marche)
- [Voir aussi](#voir-aussi)

Les noms de menus Google Cloud ci-dessous ont été vérifiés dans la documentation
Google le 12 août 2026. L'interface peut évoluer; les liens directs restent la
référence.

## Partie 1 — Mise en route

### 0. Ce que tu vas obtenir

| Artefact | Rôle | Git |
|---|---|---|
| `credentials.json` | Identifiant OAuth « Application de bureau » téléchargé depuis Google Cloud. | **Secret local, ne jamais versionner.** |
| `token.json` | Jeton créé après le consentement dans le navigateur. | **Secret local, ne jamais versionner.** |
| `configs/formulaire-google.json` | `form_id`, URL répondant et mapping `questionId → champ`. | **À conserver et versionner.** |
| `responder_uri` | URL du formulaire à diffuser, aussi enregistrée dans le mapping. | Diffusable aux demandeurs. |

`credentials.json` et `token.json` donnent accès aux formulaires du compte. Ils
sont exclus par [`.gitignore`](.gitignore), mais vérifie quand même leur statut
avant tout commit.

### 1. Installer PolicyBot

Python 3.11 ou plus est requis.

```powershell
cd C:\code\05_Travail\PolicyBot
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,google]"
pytest -q
```

Sous macOS ou Linux :

```bash
source .venv/bin/activate
```

L'extra `google` installe `google-auth` et `google-auth-oauthlib` pour le flux
OAuth. Les requêtes vers l'API Forms passent ensuite par `urllib`, dans la
bibliothèque standard.

### 2. Créer un projet Google Cloud

1. Ouvre la [console Google Cloud](https://console.cloud.google.com/).
2. Clique le sélecteur de projet dans la barre supérieure, puis **Nouveau
   projet**.
3. Donne-lui un nom, par exemple `policybot-forms`, crée-le, puis sélectionne-le.

Toutes les étapes suivantes doivent être faites dans ce même projet.

### 3. Activer l'API Google Forms

Ouvre directement la
[fiche Google Forms API](https://console.cloud.google.com/apis/library/forms.googleapis.com),
vérifie le projet affiché, puis clique **Activer**.

Le chemin de menu équivalent est **APIs et services → Bibliothèque → Google
Forms API**. L'activation peut prendre quelques minutes à se propager. Le
contrôle 5 du script de vérification distingue ce cas d'un problème de jeton.

### 4. Configurer l'application OAuth

La console actuelle regroupe ces réglages sous **Google Auth Platform**.

1. Ouvre [Google Auth Platform](https://console.cloud.google.com/auth/overview).
2. Si la plateforme n'est pas configurée, clique **Commencer**.
3. Dans **Branding**, saisis au minimum le nom de l'application, le courriel
   d'assistance et le courriel de contact.
4. Dans **Audience**, choisis :

   - **Internal** seulement si le projet appartient à une organisation Google
     Workspace ou Cloud Identity et que seuls ses membres utiliseront l'outil;
   - **External** pour un compte personnel ou des utilisateurs hors de cette
     organisation.

5. Dans **Data Access**, ajoute les deux portées demandées par PolicyBot :

   ```text
   https://www.googleapis.com/auth/forms.body
   https://www.googleapis.com/auth/forms.responses.readonly
   ```

La première autorise la création, la modification et la publication du
formulaire. La seconde permet seulement de lire ses réponses. Ce sont les
valeurs de `SCOPES` dans
[`policybot/intake/google_api.py`](policybot/intake/google_api.py).

#### Si l'audience est External

Pour une application au statut **Testing**, ouvre **Audience → Test users** et
ajoute le compte Google qui possédera le formulaire. Seuls les utilisateurs de
test peuvent consentir, dans la limite indiquée par Google.

Le mode Testing a une conséquence importante : pour une application External
qui demande les portées Forms, l'autorisation et le jeton de rafraîchissement
expirent après sept jours. C'est la cause probable d'un « ça marchait la semaine
dernière ». Supprime `token.json`, relance le vérificateur et consens de nouveau.

Pour éviter cette expiration en exploitation, passe l'application **In
production** dans **Audience**. Une application personnelle ou limitée peut
rester non vérifiée, avec un avertissement et les limites Google applicables;
une diffusion plus large ou des portées soumises à vérification exige le
processus de vérification Google. Consulte la
[documentation officielle sur l'audience](https://support.google.com/cloud/answer/15549945).

### 5. Créer l'identifiant OAuth de bureau

1. Ouvre **Google Auth Platform → Clients**, ou le
   [lien direct](https://console.cloud.google.com/auth/clients).
2. Clique **Create Client** / **Créer un client**.
3. Choisis le type **Desktop app** / **Application de bureau**.
4. Donne-lui un nom, crée-le et télécharge son JSON.
5. Renomme le fichier `credentials.json` et dépose-le à la racine du dépôt.

Un client **Web application** ne convient pas. Le flux local attend la clé
`installed` dans le JSON; `controle_2_credentials()` dans
[`scripts/verifier_google.py`](scripts/verifier_google.py) refuse explicitement
les autres types.

### 6. Vérifier les six prérequis

```powershell
python scripts/verifier_google.py
```

Le premier passage ouvre le navigateur. Connecte-toi avec le compte ajouté
comme utilisateur de test ou autorisé par l'organisation, puis accepte les deux
portées. Le script écrit `token.json` et effectue six contrôles sans créer ni
modifier de formulaire.

| # | Contrôle | Échec typique et remède |
|---:|---|---|
| 1 | Paquets Python | `google-auth` ou `google-auth-oauthlib` absent : `pip install -e ".[google]"`. |
| 2 | `credentials.json` | Fichier absent, JSON invalide ou clé `installed` absente : recrée un client de bureau. |
| 3 | Jeton OAuth | Au premier passage, le navigateur s'ouvre et `token.json` est écrit. Un jeton expiré est rafraîchi si possible. |
| 4 | Portées accordées | Le script interroge `tokeninfo`. Si une portée manque, ajoute-la dans **Data Access**, supprime `token.json` et relance. |
| 5 | API activée | L'appel vise volontairement un formulaire inexistant : **HTTP 404 est le succès attendu**. `403 SERVICE_DISABLED` signifie que l'API n'est pas activée ou pas encore propagée. |
| 6 | Secrets ignorés | `git check-ignore` doit confirmer que `credentials.json` et `token.json` sont exclus. |

Le résultat attendu se termine par :

```text
Phase 0 terminée : la phase 1 peut commencer.
```

### 7. Prévisualiser, créer et publier

Commence par l'aperçu hors ligne :

```powershell
policybot devis-formulaire
```

Il affiche les 34 questions actuelles du catalogue sans réseau ni coût. Puis crée le
formulaire :

```powershell
policybot creer-formulaire
```

La commande crée un formulaire vide, ajoute les questions, le publie, active la
collecte, écrit `configs/formulaire-google.json`, puis affiche l'URL répondant.
Le formulaire créé appartient au compte qui a accordé le consentement OAuth.

> **Attention à `--force`.** Si le mapping existe déjà, la commande normale
> s'arrête. `policybot creer-formulaire --force` crée un autre formulaire et
> remplace le mapping local sans demander confirmation. PolicyBot perd alors
> l'association avec l'ancienne URL et ne peut plus interpréter les anciennes
> réponses avec le nouveau mapping. L'ancien formulaire n'est pas supprimé de
> Google, mais il faut avoir sauvegardé son mapping pour le relire correctement.

Après la création, conserve et versionne
[`configs/formulaire-google.json`](configs/formulaire-google.json). Sans ce
fichier, les identifiants opaques rendus par Google ne peuvent pas être associés
aux champs de `DemandeIAG`.

### 8. Diffuser, collecter et ingérer

Diffuse la valeur `responder_uri` du mapping. La règle métier est : **une
réponse = un usage**. Deux usages différents du même outil demandent deux
réponses.

Télécharge ensuite les réponses brutes :

```powershell
policybot recuperer-reponses -o reponses.json
```

Valide-les hors ligne avant tout appel payant :

```powershell
policybot ingerer reponses.json --dry-run
```

Si le bilan est propre, lance l'ingestion complète :

```powershell
policybot ingerer reponses.json
```

## Partie 2 — Comment ça marche

### 2.1. Les trois maillons de vérité

```text
configs/formulaire.yaml          catalogue des 34 questions actuelles, source de vérité
        │ policybot creer-formulaire
        ▼
formulaire Google réel          Google attribue un questionId à chaque question
        │ écriture du mapping
        ▼
configs/formulaire-google.json  questionId → nom de champ interne
```

L'ingestion s'appuie sur les `questionId`, pas sur les intitulés. Tu peux donc
reformuler le titre ou l'aide d'une question existante dans Google Forms sans
casser le mapping; reporte aussi la formulation dans
[`configs/formulaire.yaml`](configs/formulaire.yaml) pour garder le catalogue à
jour.

En revanche, une question ajoutée dans l'interface reçoit un identifiant absent
du mapping et sera signalée par `questionId absent du mapping`. Supprimer une
question du catalogue directement dans Google peut rendre un champ obligatoire
absent et faire rejeter la réponse. Les changements structurels doivent passer
par le catalogue et une recréation maîtrisée.

### 2.2. Séquence exacte de `creer-formulaire`

`creer_formulaire_google()` dans
[`policybot/intake/google_forms.py`](policybot/intake/google_forms.py) exécute
les opérations dans cet ordre :

1. refuse d'agir si le mapping existe et que `force` est faux;
2. crée volontairement un formulaire non publié avec son seul titre;
3. transforme le catalogue en requêtes `createItem`, puis les envoie par
   `batchUpdate`;
4. récupère les `questionId` dans l'ordre et exige autant d'identifiants que de
   questions;
5. appelle `forms.setPublishSettings` avec `isPublished` et
   `isAcceptingResponses` à `true`;
6. récupère l'URL répondant;
7. écrit `form_id`, `responder_uri`, `created_at`, `catalogue_version` et le
   dictionnaire `questions`.

La publication précède volontairement toute URL écrite ou affichée : PolicyBot
ne diffuse jamais un formulaire qu'il sait non publié. Ce comportement est
nécessaire depuis que les formulaires créés par API peuvent être non publiés par
défaut; voir le
[guide officiel de publication](https://developers.google.com/workspace/forms/api/guides/publish-form).

### 2.3. Flux OAuth et client REST

`GoogleFormsClient._charger_credentials()` dans
[`policybot/intake/google_api.py`](policybot/intake/google_api.py) suit ce cycle :

1. lire `token.json` avec les deux portées actuelles;
2. réutiliser le jeton s'il est valide;
3. le rafraîchir s'il est expiré et possède un `refresh_token`;
4. sinon lancer `InstalledAppFlow` dans le navigateur, sur un port local libre;
5. réécrire `token.json`.

Un jeton illisible, incompatible avec les portées demandées ou impossible à
rafraîchir déclenche donc un nouveau consentement. Supprimer volontairement
`token.json` est la façon simple de forcer ce consentement après un changement
de portée.

Les appels métier n'utilisent pas `google-api-python-client`. `_envoyer_urllib()`
envoie du JSON à `https://forms.googleapis.com/v1` avec le jeton OAuth dans
l'en-tête `Authorization`.

### 2.4. Récupération des réponses

`GoogleFormsClient.lister_reponses()` appelle
`GET /forms/{formId}/responses` avec une taille de page de 5 000, suit chaque
`nextPageToken` et agrège toutes les réponses. `recuperer_reponses_google()` les
écrit ensuite telles quelles dans un objet JSON `{"responses": [...]}`.

Il n'y a ni interprétation ni appel modèle à cette étape. Le fichier est donc
archivable et rejouable hors ligne, ce qui sépare proprement l'accès Google de
l'ingestion PolicyBot. L'API et la portée de lecture sont documentées dans le
[guide Google de récupération](https://developers.google.com/workspace/forms/api/guides/retrieve-forms-responses).

### 2.5. Ce que diagnostique `--dry-run`

`policybot ingerer reponses.json --dry-run` affiche :

- le nombre de réponses lues, de demandes valides et de rejets;
- chaque `questionId` inconnu;
- le motif de chaque réponse rejetée;
- l'identité contractuelle résolue pour chaque demande;
- les champs d'identité manquants ou un type d'outil non résolu.

Le code de retour vaut 1 s'il reste un rejet ou une demande non résolue, sinon
0. Aucun modèle, aucune recherche Exa et aucun générateur de document n'est
appelé.

### 2.6. Modifier le formulaire après sa création

| Changement | Marche à suivre |
|---|---|
| Reformuler un intitulé ou une aide | Modifie la question existante dans Google Forms, sans la supprimer. Aligne ensuite `configs/formulaire.yaml`. Le `questionId` reste utilisable. |
| Ajouter ou retirer une question | Modifie d'abord `configs/formulaire.yaml`, adapte au besoin le schéma d'ingestion et le gabarit, sauvegarde l'ancien mapping et les réponses, puis recrée avec `--force`. Tu obtiens une nouvelle URL et un nouveau mapping. |
| Compléter les outils déjà approuvés | Modifie la page 1 de `configs/formulaire.yaml`, où l'option `À COMPLÉTER` est encore présente, puis recrée de façon maîtrisée. |
| Compléter l'adresse de la sécurité informatique | Remplace `ADRESSE À COMPLÉTER` dans la page 1 du catalogue, puis recrée de façon maîtrisée. |
| Régénérer l'aperçu versionné | `policybot devis-formulaire > docs/formulaire-google-forms.md` |

> **Rappel sur `--force`.** Cette commande remplace le mapping local par celui
> d'un nouveau formulaire. Sauvegarde avant l'opération l'ancien
> `configs/formulaire-google.json`, son URL et les réponses déjà téléchargées.
> Sans l'ancien mapping, le JSON des anciennes réponses n'est plus
> interprétable par PolicyBot.

Les deux marqueurs `À COMPLÉTER` du catalogue sont du travail de configuration
institutionnelle restant : ils ne signalent pas une panne de l'intégration.

## Voir aussi

- [README principal](README.md) — installation, boucle complète et livrables.
- [Recherche Exa](README-EXA.md) — configuration et diagnostic des constats.
- [Aperçu généré du formulaire](docs/formulaire-google-forms.md) — sortie de
  `policybot devis-formulaire`, à régénérer après une modification du catalogue
  et à ne pas modifier à la main.
- [Démarrage rapide officiel Google Forms](https://developers.google.com/workspace/forms/api/quickstart/python)
  — activation de l'API et création d'un client de bureau.
