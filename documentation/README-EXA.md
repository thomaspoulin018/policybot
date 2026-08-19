# Recherche contractuelle avec Exa

Ce guide explique comment lancer et diagnostiquer les recherches Exa de
PolicyBot. Pour la vue d'ensemble du pipeline, voir le [README principal](README.md).

- [Partie 1 — Mise en route](#partie-1--mise-en-route)
- [Partie 2 — Comment ça marche](#partie-2--comment-ça-marche)
- [Voir aussi](#voir-aussi)

## Partie 1 — Mise en route

### 1. Le rôle d'Exa dans PolicyBot

Exa recherche les faits contractuels qui alimentent la grille d'évaluation.
PolicyBot lance 17 recherches indépendantes : 13 pour la partie A et 4 pour la
partie B. Chaque recherche demande aussi une sortie JSON structurée contenant
une réponse, un niveau de risque inhérent proposé et une justification. Exa est
le seul coût variable des recherches; la tarification peut changer et doit être
consultée sur la [page officielle](https://exa.ai/pricing?tab=api).

### 2. Installer PolicyBot

Python 3.11 ou plus est requis.

```powershell
cd C:\code\05_Travail\PolicyBot
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,google]"
pytest -q
```

Sous macOS ou Linux, active plutôt l'environnement avec :

```bash
source .venv/bin/activate
```

L'extra `google` n'est pas nécessaire à Exa, mais la commande d'installation
ci-dessus prépare tout le projet. `exa-py` fait partie des dépendances de base.

### 3. Créer et enregistrer la clé

1. Crée un compte Exa et ouvre le
   [tableau de bord des clés API](https://dashboard.exa.ai/api-keys).
2. Crée une clé dédiée à PolicyBot.
3. Copie `.env.example` vers `.env` :

   ```powershell
   Copy-Item .env.example .env
   ```

4. Renseigne la clé sans guillemets :

   ```dotenv
   EXA_API_KEY=ta-cle-exa
   ```

`.env` est ignoré par git. La CLI le charge dans `main()` de
[`policybot/cli.py`](policybot/cli.py); les tests, qui appellent la CLI avec un
flux explicite, restent hors ligne. Ne copie jamais une clé dans un YAML, un
script de diagnostic ou un rapport.

Le pipeline complet exige aussi `OPENROUTER_API_KEY`. Le diagnostic Exa de
l'étape suivante n'en a pas besoin.

### 4. Tester une seule recherche réelle

Évite de lancer les 17 recherches pour vérifier une clé. Lance le diagnostic du
critère A04 :

```powershell
python scripts/exa_debug_critere.py --critere A04 --tool ChatGPT --vendor OpenAI
```

Le script affiche le chemin du fichier brut, normalement :

```text
tmp/exa_raw_A04_neural.json
```

Ce fichier n'est pas masqué et peut contenir le texte de pages sources. Il ne
doit pas être versionné. Inspecte principalement :

- `output.answer`, `output.inherent_risk` et `output.justification`, la sortie
  globale structurée;
- `results[].summary.citation`, les extraits proposés page par page;
- `results[].text`, le texte dans lequel chaque extrait doit être retrouvé;
- `costDollars`, le coût rapporté par Exa pour cet appel.

Le diagnostic utilise le critère et les schémas réels. La commande accepte
seulement les identifiants ayant un bloc `exa:`; `--type` permet de surcharger
temporairement le type de recherche.

### 5. Comprendre une clé absente

Sans `EXA_API_KEY`, `search_criteria_with_exa()` dans
[`policybot/contract/exa.py`](policybot/contract/exa.py) lève
`CleApiManquante("EXA_API_KEY")`. La CLI arrête le lot avec le code de retour 2.
C'est un garde-fou : continuer créerait des dossiers d'apparence complète sans
aucun constat contractuel.

### 6. Vérifier avant de dépenser

```powershell
policybot ingerer reponses.json --dry-run
```

Le mode `--dry-run` lit et valide les réponses, affiche l'identité de chaque
offre et ne lance ni modèle ni recherche. Il ne donne pas un prix prévisionnel.
Lors d'une ingestion réelle, PolicyBot additionne le `costDollars` de chaque
recherche et affiche `coût Exa total` à la fin du lot.

## Partie 2 — Comment ça marche

### 2.1. Le trajet d'une recherche

Le cœur du traitement est `_collect_one()` dans
[`policybot/contract/exa.py`](policybot/contract/exa.py).

| Étape | Comportement |
|---|---|
| Identité de l'offre | `_identity_values()` prépare `tool`, `vendor`, `plan`, `deployment_mode`, `contract_type`, `contract_version` et `jurisdiction`. Une valeur vide ou `unknown` devient une chaîne vide. |
| Requête globale | La requête du critère est suivie de deux sauts de ligne et de `global_instruction`, formatée avec la question en français. |
| Résumé par page | `contents.summary` reçoit `per_page_instruction` et le schéma `per_page`; Exa doit répondre à partir de cette seule page et proposer un extrait verbatim. |
| Appel Exa | L'appel reçoit `num_results`, `type`, `output_schema`, `contents` et, si le critère en déclare, `include_domains`. |
| Sortie globale | `answer`, `inherent_risk` et `justification` sont lus depuis `output`. Le risque est mis en majuscules et devient nul s'il n'est pas `F`, `M` ou `E`. |
| Coût | `_response_cost()` accepte les formes de `costDollars` rendues par les versions prises en charge du SDK. |
| Ordre des sources | `source_sort_key()` dans [`policybot/contract/source_policy.py`](policybot/contract/source_policy.py) place d'abord les URL classées officielles, puis la pertinence Exa, puis l'URL. |
| Citations | Les extraits vides sont ignorés. Les extraits non retrouvés sont rejetés, une seule citation est gardée par URL et le plafond commun est appliqué. |
| Verdict | `outcome` vaut `ok` si `answer` n'est pas vide, sinon `no_answer`. |

Le classement « officiel » est une heuristique déterministe fondée sur des
marqueurs d'URL (`terms`, `legal`, `docs`, `security`, `privacy`, etc.). Il ne
constitue pas une validation juridique du propriétaire de la page.

### 2.2. Parallélisme et isolation des échecs

`collect_criteria_from_exa()` utilise un `ThreadPoolExecutor` avec
`DEFAULT_MAX_WORKERS = 8`. Chaque critère est enveloppé séparément : une
exception devient un constat vide avec `outcome = "search_failed"`, tandis que
les autres recherches continuent. Une fois les fils terminés, la liste est
remise dans l'ordre des définitions, pas dans l'ordre d'arrivée.

Les trois états visibles dans le résumé du lot sont :

| État | Signification |
|---|---|
| `ok` | Exa a rendu une réponse globale non vide. |
| `no_answer` | L'appel a réussi, mais la réponse globale est vide. |
| `search_failed` | L'appel ou son traitement a levé une exception pour ce critère. |

Une clé absente est différente : elle est vérifiée avant le lancement du lot et
arrête toute l'ingestion.

### 2.3. Pourquoi une citation est rejetée

`validated_citation()` dans
[`policybot/contract/citations.py`](policybot/contract/citations.py) n'accepte
jamais un extrait sur la seule parole du modèle.

1. Si `begin` et `end` sont des entiers valides, PolicyBot découpe directement
   la page à ces positions et vérifie que le texte correspond à la citation.
2. Sinon, il cherche d'abord la chaîne exacte, puis les mêmes mots sans tenir
   compte de la casse et des variations d'espaces.
3. Sans correspondance, la fonction retourne `None` et incrémente
   `rejected_citations`.
4. Une citation acceptée reçoit un lien profond `#:~:text=`. Jusqu'à 12 mots,
   tout l'extrait sert d'ancre; au-delà, l'ancre contient les 5 premiers et les
   5 derniers mots.

Un `rejected_citations` non nul avec `outcome = "ok"` est normal et sain : la
réponse globale existe, mais PolicyBot a écarté un ou plusieurs extraits qui
n'étaient pas vérifiables dans leur page. Une réponse peut donc être présente
sans citation retenue.

### 2.4. Les deux niveaux de configuration

[`configs/recherche_defaults.yaml`](configs/recherche_defaults.yaml) contient
les réglages communs. `load_criterion_searches()` dans
[`policybot/contract/criteres.py`](policybot/contract/criteres.py) les fusionne
en profondeur avec le bloc `exa` de chaque critère.

| Réglage commun | Valeur actuelle |
|---|---|
| `exa.type` | `neural` |
| `exa.num_results` | `5` |
| `exa.contents.text.max_characters` | `24000` |
| `schemas.global` | `answer`, `inherent_risk` (`F`, `M` ou `E`) et `justification`, tous requis |
| `schemas.per_page` | `answer` et `citation` requis; `begin` et `end` facultatifs |
| `max_citations_per_criterion` | `3` |

Un fichier sous [`configs/recherche_criteres/`](configs/recherche_criteres/)
peut surcharger `type`, `num_results`, `include_domains` ou `contents` dans son
bloc `exa`.

### 2.5. Anatomie d'un critère

Voici le fichier A01 complet :

```yaml
version: 2
id: A01
partie: A
category: Souveraineté et hébergement des données
criterion: Localisation des serveurs
question: Les données sont-elles hébergées au Québec ou dans une juridiction équivalente ?
exa:
  query: Where does {vendor} host and process {tool} customer data? data residency regions {plan} {deployment_mode} {contract_type} {contract_version}
```

| Champ | Règle |
|---|---|
| `version` | Doit être le littéral `2`. |
| `id` | Doit respecter `^[AB][A-Za-z0-9_-]+$`, être unique et commencer par la lettre de `partie`. |
| `partie` | `A` ou `B`. Au moins un critère de chaque partie doit exister dans le catalogue. |
| `category` | Catégorie affichée dans la grille. |
| `criterion` | Intitulé utilisé pour retrouver la ligne correspondante dans le gabarit Word. |
| `question` | Question métier, réinjectée dans les instructions globale et par page. |
| `exa` | Facultatif. Sans ce bloc, le critère reste dans la grille mais aucune recherche n'est lancée. |
| `exa.query` | Requête Exa. Les seuls marqueurs permis sont les sept champs d'identité listés plus haut. |

Les modèles Pydantic utilisent `extra="forbid"` : une clé inconnue fait échouer
le chargement. Le type de recherche doit être l'un de `auto`, `fast`, `neural`,
`instant`, `deep-lite`, `deep` ou `deep-reasoning`. Un marqueur inconnu provoque
l'erreur `unknown query placeholders`.

### 2.6. Ajouter un critère recherché

1. Crée par exemple
   `configs/recherche_criteres/A14-mon-critere.yaml`. Les fichiers `*.yaml` sont
   chargés par nom trié; le nom détermine donc l'ordre d'apparition.
2. Renseigne les champs décrits ci-dessus et ajoute un bloc `exa`. Écris la
   requête dans la langue des sources visées; conserve la question métier en
   français.
3. Vérifie le chargement sans réseau :

   ```powershell
   python -c "from policybot.contract.criteres import CRITERIA_SEARCHES; print(len(CRITERIA_SEARCHES))"
   ```

4. Lance une seule recherche réelle :

   ```powershell
   python scripts/exa_debug_critere.py --critere A14 --tool ChatGPT --vendor OpenAI
   ```

5. Vérifie le gabarit Word avant de terminer. `_fill_risk_table()` dans
   [`policybot/report/grille.py`](policybot/report/grille.py) retrouve une ligne
   par l'intitulé `criterion` et lève une erreur si elle manque. Ajouter le YAML
   sans ajouter la ligne correspondante au gabarit ne suffit pas.
6. Exécute les tests :

   ```powershell
   pytest -q
   ```

Attention : `SEARCH_DEFAULTS` et `CRITERIA` sont chargés au moment où
`policybot.contract.criteres` est importé. Un YAML invalide peut donc empêcher
toute commande qui importe la recherche de démarrer. Le chargeur impose aussi
des identifiants uniques et la présence des parties A et B.

### 2.7. Inventaire actuel

| Ensemble | Nombre | Identifiants |
|---|---:|---|
| Partie A, recherchés | 13 | A01 à A13 |
| Partie B, recherchés | 4 | B01 à B04 |
| Partie B, sans bloc `exa` | 7 | B05 à B11 |
| **Total** | **24** | 17 recherchés, 7 laissés à l'évaluation humaine |

Les noms de fichiers des sept derniers utilisent des repères descriptifs
(`B00a`, `B00b`, `B02a`, `B03a` à `B03d`), mais leur champ `id` — la valeur
utilisée par le code et la grille — est bien `B05` à `B11`. Il faut distinguer
le nom du fichier de l'identifiant interne.

## Voir aussi

- [README principal](README.md) — installation et boucle complète.
- [Google Forms](README-GOOGLE-FORMS.md) — création du formulaire et ingestion
  des réponses.
- [Cycle d'une recherche](docs/diagramme-recherche-critere.md) — diagramme du
  trajet jusqu'à la citation ancrée.
