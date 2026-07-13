# Comment lancer PolicyBot

Guide rapide pour démarrer l'application en local. Pour le contexte fonctionnel
et l'architecture, voir [`README.md`](README.md).

## Prérequis

- Python 3.11+
- (Optionnel) une clé OpenRouter + un compte LangSmith si tu veux des réponses
  LLM réelles et la traçabilité — sans ça, l'app tourne avec le `FakeLLMProvider`.

## 1. Installer les dépendances

```bash
pip install -e ".[dev]"
```

Ajoute l'extra `pdf` pour que chaque resultat genere aussi un PDF dans `output/pdf/` :

```bash
pip install -e ".[dev,pdf]"
```

Les dossiers `output/pdf/` et `output/docx/` sont crees automatiquement. Tu peux changer leurs destinations avec `POLICYBOT_PDF_OUTPUT_DIR` et `POLICYBOT_DOCX_OUTPUT_DIR`.

## 2. Configurer les variables d'environnement (optionnel)

Copie `.env.example` vers `.env` et remplis les clés si tu veux des appels LLM
réels et le traçage LangSmith :

```bash
cp .env.example .env
```

Sans `OPENROUTER_API_KEY`, PolicyBot utilise automatiquement le
`FakeLLMProvider` (pas d'appel réseau). Le `.env` est chargé automatiquement au
démarrage et n'est jamais lu sous `pytest`.


### Recherche contractuelle Tavily

Pour utiliser Tavily comme source de recherche des faits contractuels ARP, ajoute ces variables dans `.env` :

```bash
TAVILY_API_KEY=<ta cle Tavily>
POLICYBOT_CONTRACT_SEARCH=tavily
```

Au premier passage d'un outil, PolicyBot genere automatiquement `configs/tavily_contracts/<outil>.yaml`. Ce YAML contient une requete Tavily Search par champ `ContractFacts`, puis les URLs trouvees sont envoyees a Tavily Extract pour recuperer le contenu complet avant la normalisation LLM : `trains_on_input`, `data_retention`, `data_residency`, `sub_processors`, `human_review`, `encryption_standard`, `ip_ownership`, `applicable_law`, `foreign_vendor_dependency`, `contract_prohibits_reuse` et `reentraining_opt_out`. Tavily Extract accepte au maximum 20 URLs par appel; ajuste `extract_defaults.max_urls` dans le YAML pour reduire ce nombre au besoin.

Tester Tavily sans lancer le serveur web :

```bash
python -m policybot.contract.tavily_probe "ChatGPT" --show-config --evidence-out output/tavily-chatgpt.md
```

Pour aller jusqu'aux `ContractFacts`, ajoute `--facts` avec `OPENROUTER_API_KEY` defini. Pour construire aussi l'ARP Partie A :

```bash
python -m policybot.contract.tavily_probe "ChatGPT" --facts --arp --iag-type publique --evidence-out output/tavily-chatgpt.md
```
## 3. Lancer le serveur web

```bash
uvicorn policybot.api.app:app --reload
```

L'app démarre sur http://127.0.0.1:8000 :

- L'assistant (wizard web) est servi via les routes de `policybot/web/routes.py`.
- `POST /assess` et `POST /report` exposent le pipeline brut (API JSON).

## 4. Lancer les tests

```bash
pytest -v
```

Tous les tests tournent hors-ligne (LLM factice, fixtures HTML pour les
fetchers de conditions d'utilisation) — aucun appel réseau n'est fait.

## Dépannage rapide

- **Port déjà utilisé** : `uvicorn policybot.api.app:app --reload --port 8001`
- **`policybot.db` verrouillée ou corrompue** : le fichier SQLite à la racine
  sert de cache pour les fiches ARP/pré-approuvées ; tu peux le supprimer, il
  sera recréé au prochain démarrage.
- **Pas de réponses LLM réelles** : vérifie que `OPENROUTER_API_KEY` est bien
  défini dans `.env` (et que le serveur a été redémarré après modification).
