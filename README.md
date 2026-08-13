# PolicyBot

PolicyBot prépare un dossier de constats sourcés pour l'évaluation d'un outil
d'IA générative dans une université québécoise. **Il n'autorise rien** : il
rassemble des faits contractuels, chacun rattaché à une citation retrouvée dans
le texte de sa propre page, et laisse la décision à l'autorité désignée.

PolicyBot n'a pas d'interface. Le formulaire de demande vit dans Google Forms,
créé par PolicyBot lui-même à partir d'un catalogue YAML ; l'ingestion lit
l'export JSON des réponses.

```text
Google Forms → reponses.json → policybot ingerer → 17 recherches Exa → fiche + grille + constats
```

## Prérequis

- Python 3.11 ou plus.
- Une clé **OpenRouter** (`OPENROUTER_API_KEY`) : la classification des données
  est le seul appel modèle du pipeline.
- Une clé **Exa** (`EXA_API_KEY`) : une recherche par critère.
- Un identifiant OAuth Google (`credentials.json`) si tu crées le formulaire ou
  télécharges les réponses. L'ingestion d'un JSON déjà téléchargé n'en a pas
  besoin.

Les deux clés sont **obligatoires**. Sans elles, le lot s'arrête avec le code de
retour 2 : PolicyBot ne produit jamais un rapport d'apparence complète dont tous
les constats seraient vides.

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev,google]"
pytest -q
```

L'extra `google` n'apporte que le flux OAuth (`google-auth`,
`google-auth-oauthlib`) ; les appels à l'API Forms passent par la bibliothèque
standard.

Copie ensuite `.env.example` vers `.env` et renseigne les deux clés. Le fichier
`.env` n'est lu qu'en usage console — la suite de tests reste hors ligne.

## La boucle complète

### 1. Voir le formulaire, hors ligne

```powershell
policybot devis-formulaire
```

Imprime les 34 questions actuelles telles que le catalogue les définit. Aucune connexion,
aucun coût. Le résultat est versionné sous
[`docs/formulaire-google-forms.md`](docs/formulaire-google-forms.md) ; régénère-le
avec `policybot devis-formulaire > docs/formulaire-google-forms.md`.

### 2. Créer et publier le formulaire Google

```powershell
python scripts/verifier_google.py    # six contrôles, aucun effet de bord
policybot creer-formulaire
```

Crée le formulaire, y applique le catalogue, le publie, puis écrit
`configs/formulaire-google.json` — le mapping `questionId → champ`. L'ingestion
s'appuie sur ces identifiants stables : les intitulés peuvent être reformulés
dans Google Forms sans rien casser.

La commande refuse de s'exécuter si un mapping existe déjà. `--force` crée une
**nouvelle URL** : celle qui a été diffusée est perdue et les réponses déjà
collectées deviennent illisibles avec le nouveau mapping.

### 3. Collecter les réponses

Les demandeurs remplissent le formulaire. **Une réponse = un usage** : deux
usages distincts du même outil demandent deux réponses.

```powershell
policybot recuperer-reponses -o reponses.json
```

Télécharge les réponses brutes, pagination suivie, sans interprétation. Le
fichier obtenu est rejouable autant de fois que voulu.

### 4. Vérifier avant de dépenser

```powershell
policybot ingerer reponses.json --dry-run
```

Lit et valide le JSON, affiche l'identité d'offre résolue pour chaque demande et
signale les champs manquants. **Aucun appel modèle, aucune recherche, aucun
coût.** Code de retour 1 s'il reste des rejets ou des demandes non résolues.

### 5. Produire les dossiers

```powershell
policybot ingerer reponses.json
```

Pour chaque demande : classification des données, 17 recherches Exa, puis trois
fichiers. Une demande en échec est signalée et le lot continue ; seule une clé
d'API absente arrête tout.

## Ce que PolicyBot produit

| Fichier | Où | Contenu |
|---|---|---|
| Fiche de qualification `.docx` | `output/docx/` | 7 tableaux remplis par intitulé ; la section 8 est explicitement laissée vierge |
| Grille d'évaluation des risques `.docx` | `output/docx/` | Partie A, un bloc « Usage évalué » par usage (4 au plus), puis le registre des sources |
| Constats `.json` | `output/json/NUMERO.json` | Les constats bruts, un objet par critère |
| Journal `.jsonl` | `logs/log_HORODATAGE.jsonl` | Étapes, durées, jetons et coûts. Aucun texte libre en clair : `mask_text` n'enregistre qu'une longueur et un SHA-256 |

Le résumé de fin de lot donne le coût Exa total. Code de retour 1 si une demande
a été rejetée ou a échoué.

## Fonctionnement

Pour une offre donnée, PolicyBot :

1. identifie l'outil, son fournisseur et son type d'IAG via un registre local —
   aucun réseau ;
2. construit l'identité de l'offre contractuelle (fournisseur, produit, plan,
   mode de déploiement, type de contrat, version, territoire) ;
3. classifie prudemment les données décrites — un seul appel modèle, avec repli
   conservateur sur « Protégé A » si le résultat n'est pas concluant ;
4. lance **17 recherches Exa indépendantes**, sur 8 fils, une par critère ;
5. recueille pour chacune une réponse, un niveau de risque inhérent F/M/E
   proposé et une justification ;
6. ne retient que les citations retrouvées dans le texte de leur propre page,
   avec lien profond vers le passage exact — 3 au plus par critère ;
7. remplit les gabarits Word officiels et affiche le coût total.

Les sources officielles passent devant les autres dans le registre. Une
recherche qui échoue dégrade son seul critère (`search_failed`) ; les seize
autres poursuivent.

### Les 24 critères, dont 17 recherchés

`configs/recherche_criteres/` déclare 24 critères — A01 à A13, B01 à B11. Les 17
qui portent un bloc `exa:` sont recherchés : 13 en partie A, 4 en partie B. Les
sept autres (B05 à B11) n'en portent pas et ne produisent aucun constat : **leurs
lignes de grille restent vierges pour la main humaine**, comme la section 8 de la
fiche. C'est délibéré.

## Configuration

| Fichier | Rôle |
|---|---|
| `configs/formulaire.yaml` | Les 34 questions actuelles et le champ que chacune alimente. Source de vérité du formulaire, validée contre `DemandeIAG` à l'import |
| `configs/formulaire-google.json` | Mapping `questionId → champ`, écrit par `creer-formulaire`. **À conserver** : sans lui, les réponses sont illisibles |
| `configs/policybot.yaml` | Modèle, effort de raisonnement, jetons, température et délai de la classification |
| `configs/prompts.yaml` | Les invites du classificateur |
| `configs/recherche_defaults.yaml` | Paramètres Exa communs : type de recherche, schémas JSON, instructions, plafond de 3 citations par critère |
| `configs/recherche_criteres/*.yaml` | Une question et une requête par critère |
| `documents_reference/*.docx` | Les deux gabarits Word officiels. Un gabarit modifié fait **échouer** la demande, il ne produit pas un document silencieusement incomplet |

### Variables d'environnement

| Variable | Effet |
|---|---|
| `OPENROUTER_API_KEY` | Obligatoire. Sans elle, arrêt du lot |
| `EXA_API_KEY` | Obligatoire. Sans elle, arrêt du lot |
| `OPENROUTER_MODEL`, `OPENROUTER_REASONING_EFFORT`, `OPENROUTER_MAX_TOKENS`, `OPENROUTER_TEMPERATURE`, `OPENROUTER_TIMEOUT` | Surcharges globales du YAML |
| `POLICYBOT_LLM_DATA_CLASSIFICATION_<CHAMP>` | Surcharge la seule tâche modèle ; l'emporte sur les précédentes |
| `POLICYBOT_CONFIG_PATH` | Autre `policybot.yaml` |
| `POLICYBOT_PROMPTS_PATH` | Autre `prompts.yaml` |
| `POLICYBOT_FORMULAIRE_PATH` | Autre catalogue de questions |
| `POLICYBOT_SEARCH_DEFAULTS_PATH`, `POLICYBOT_CRITERIA_DIR` | Autres définitions de recherche |
| `POLICYBOT_FICHE_TEMPLATE`, `POLICYBOT_GRILLE_TEMPLATE` | Autres gabarits Word |
| `POLICYBOT_DOCX_OUTPUT_DIR` | Répertoire des `.docx` (défaut `output/docx`) |
| `POLICYBOT_LOG_PATH` | Fichier de journal fixe au lieu d'un horodaté sous `logs/` |

Les options `--sortie-docx` et `--sortie-json` d'`ingerer` l'emportent sur les
répertoires par défaut.

## Diagnostic

Rejouer une seule recherche, sans passer par le pipeline :

```powershell
python scripts/exa_debug_critere.py --critere A04 --tool ChatGPT --vendor OpenAI
```

La réponse brute atterrit sous `tmp/`. Elle peut contenir du texte de sources et
n'a pas à être versionnée.

## Documentation

- [`README-EXA.md`](README-EXA.md) — mise en route d'Exa, diagnostic d'une
  recherche, validation des citations et ajout d'un critère.
- [`README-GOOGLE-FORMS.md`](README-GOOGLE-FORMS.md) — configuration Google
  Cloud et OAuth, création du formulaire, collecte et cycle de vie du mapping.
- [`docs/diagramme-pipeline-policybot.md`](docs/diagramme-pipeline-policybot.md)
  — le graphe complet de la chaîne réelle, du formulaire aux livrables, établi
  par lecture du code.
- [`docs/diagramme-recherche-critere.md`](docs/diagramme-recherche-critere.md)
  — le cycle de vie d'une des 17 recherches, jusqu'à la citation ancrée.
- [`docs/formulaire-google-forms.md`](docs/formulaire-google-forms.md) — les 35
  questions, générées depuis le catalogue.
- [`docs/carte-pipeline-policybot.html`](docs/carte-pipeline-policybot.html) —
  table de correspondance nœud → fichier ; rédigée avant le retrait du cache ARP,
  à lire avec cette réserve.

## Ce qui n'existe plus

Le dépôt a été démoli puis reconstruit autour de la CLI. N'attends plus de
trouver : le wizard web et son API, le cache ARP SQLite, le budget de recherche,
le rendu PDF, le repli silencieux sur un `FakeLLMProvider`, ni l'ingestion d'un
export Microsoft Forms `.xlsx`.
