# Comment lancer PolicyBot

Guide rapide. Pour le contexte fonctionnel et l'architecture, voir
[`README.md`](README.md).

## Prérequis

- Python 3.11+
- (Optionnel) une clé OpenRouter pour la classification des données, et une clé
  Exa pour les recherches contractuelles. Sans clé OpenRouter, PolicyBot bascule
  sur le `FakeLLMProvider` et ne fait aucun appel réseau.

## 1. Installer

```powershell
python -m venv .venv
.\.venv\Scripts\activate           # macOS / Linux : source .venv/bin/activate
pip install -e ".[dev,pdf]"
```

L'extra `pdf` ajoute `reportlab`, nécessaire à l'export PDF. Les répertoires
`output/pdf/`, `output/docx/` et `output/json/` sont créés automatiquement ;
`POLICYBOT_PDF_OUTPUT_DIR` et `POLICYBOT_DOCX_OUTPUT_DIR` changent leur
destination, tout comme les options `--sortie-pdf`, `--sortie-docx` et
`--sortie-json`.

## 2. Configurer les variables d'environnement (optionnel)

```bash
cp .env.example .env
```

Sans `OPENROUTER_API_KEY`, PolicyBot utilise le `FakeLLMProvider`. Sans
`EXA_API_KEY`, aucune recherche contractuelle n'aboutit. Le `.env` n'est jamais
lu sous `pytest`.

## 3. Préparer le formulaire

```powershell
policybot devis-formulaire
```

La sortie liste les 35 questions, leur type, leurs choix et le champ que
chacune alimente. Recopie-les dans Microsoft Forms **en conservant les
intitulés** : c'est sur eux que l'appariement des colonnes se fait. Une
divergence de casse, d'accents ou de ponctuation finale reste tolérée ; un
intitulé réécrit, non.

La même liste est versionnée sous
[`docs/formulaire-microsoft-forms.md`](docs/formulaire-microsoft-forms.md).

## 4. Ingérer les réponses

Télécharge l'export Excel depuis Microsoft Forms, puis :

```powershell
policybot ingerer reponses.xlsx --dry-run
```

`--dry-run` lit, valide et affiche l'identité d'offre résolue de chaque
demande. Il n'appelle ni modèle, ni recherche, et n'écrit aucun fichier :
c'est le mode qui permet de vérifier un export avant toute dépense. Vérifie-le
sur un vrai export avant de déclarer la chaîne bonne — le code ne peut pas
faire cette vérification à ta place.

Puis, pour de vrai :

```powershell
policybot ingerer reponses.xlsx
```

Le code de sortie vaut 1 dès qu'une demande a été rejetée ou a échoué. Une
demande en échec n'arrête jamais le lot.

## 5. Lancer les tests

```powershell
pytest -q
```

Toute la suite tourne hors ligne : LLM factice, recherche Exa injectée,
export Forms produit par `tests/helpers/forms.py`. Aucun appel réseau.

Pour régénérer la fixture d'export après un changement du catalogue :

```powershell
python -m tests.helpers.forms
```

## Dépannage rapide

- **« colonne absente de l'export »** : un intitulé de question a été réécrit
  dans Microsoft Forms. Compare avec `policybot devis-formulaire`.
- **« réponse « X » hors des choix proposés »** : un choix a été renommé dans
  le formulaire sans l'être dans `configs/formulaire.yaml`.
- **`policybot.db` verrouillée ou corrompue** : ce fichier SQLite à la racine
  n'est qu'un cache d'analyses ARP ; tu peux le supprimer, il sera recréé.
- **Pas de réponses LLM réelles** : vérifie `OPENROUTER_API_KEY` dans `.env`.
