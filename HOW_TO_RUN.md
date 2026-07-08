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

Ajoute l'extra `pdf` si tu as besoin de générer des PDF (WeasyPrint) :

```bash
pip install -e ".[dev,pdf]"
```

## 2. Configurer les variables d'environnement (optionnel)

Copie `.env.example` vers `.env` et remplis les clés si tu veux des appels LLM
réels et le traçage LangSmith :

```bash
cp .env.example .env
```

Sans `OPENROUTER_API_KEY`, PolicyBot utilise automatiquement le
`FakeLLMProvider` (pas d'appel réseau). Le `.env` est chargé automatiquement au
démarrage et n'est jamais lu sous `pytest`.

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
