# Config YAML pour les outils pré-approuvés (page 1 du wizard)

## Contexte

La première page du wizard (`wizard_outil.html.j2`, "Étape 1 · Ton outil") propose
des puces d'outils connus, tirées de la constante `KNOWN_TOOLS` codée en dur dans
`policybot/web/routes.py` :

```python
KNOWN_TOOLS = ["ChatGPT", "ChatGPT Pro", "Claude.ai", "Perplexity", "Microsoft Copilot Entreprise"]
```

Modifier cette liste exige aujourd'hui d'éditer du code Python. L'objectif est de
la déplacer dans un fichier YAML facile à éditer pour un officier non-développeur.

Le `REGISTRY` de `policybot/classify/tool_registry.py` (métadonnées vendor/iag_type/
terms_url utilisées pour l'auto-classification) reste hors scope — il n'est pas
touché par ce changement, décision confirmée avec l'utilisateur.

## Approche

Suivre le pattern déjà établi par `policybot/grille/rules.py` pour `grille.yaml` :
un fichier YAML à côté du module Python qui le charge, chemin par défaut dérivé de
`__file__`, chargement via `yaml.safe_load`.

Différence par rapport à `grille.yaml` : le fichier est relu à **chaque requête**
GET `/` (pas seulement au démarrage), pour que les modifications soient visibles
sans redémarrer le serveur. Le fichier est petit (quelques lignes) et la page 1
n'est pas un chemin critique en performance, donc le coût d'une lecture disque par
requête est négligeable.

## Composants

### 1. `policybot/preapproved/known_tools.yaml` (nouveau)

Liste simple de noms d'outils, avec un commentaire d'en-tête expliquant comment
l'éditer :

```yaml
# Outils pré-approuvés proposés comme choix rapides sur la première page.
# Ajouter un nom ici suffit : pas besoin de redémarrer PolicyBot.
- ChatGPT
- ChatGPT Pro
- Claude.ai
- Perplexity
- Microsoft Copilot Entreprise
```

### 2. `policybot/preapproved/known_tools.py` (nouveau)

```python
from __future__ import annotations
import os
import yaml

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "known_tools.yaml")


def load_known_tools(path: str | None = None) -> list[str]:
    with open(path or _DEFAULT_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    return list(raw)
```

Pas de modèle Pydantic : c'est une simple liste de chaînes, pas une structure
imbriquée comme les règles de la grille. Comportement sur fichier manquant ou
malformé : laisser l'exception se propager (même choix que `load_rules`), car le
fichier est livré avec le dépôt et son absence est une erreur de déploiement, pas
un cas à gérer silencieusement.

### 3. `policybot/web/routes.py` (modifié)

- Suppression de la constante `KNOWN_TOOLS`.
- Import de `load_known_tools`.
- `wizard_home` appelle `load_known_tools()` à chaque requête au lieu de référencer
  la constante :

```python
@router.get("/", response_class=HTMLResponse)
def wizard_home(request: Request):
    return templates.TemplateResponse(request, "wizard_outil.html.j2", {
        "active_step": "outil", "known_tools": load_known_tools(),
    })
```

Le template `wizard_outil.html.j2` ne change pas : il itère déjà sur `known_tools`.

## Tests

- `tests/preapproved/test_known_tools.py` (nouveau) : vérifie que `load_known_tools()`
  retourne une liste non vide contenant les outils par défaut, et qu'un chemin
  explicite vers un fichier YAML de test personnalisé est bien pris en compte.
- `tests/web/test_routes_outil.py` : les tests existants (`test_home_page_renders_outil_step`,
  `test_known_tool_skips_straight_to_donnees_step`) continuent de passer sans
  modification, car `ChatGPT` reste dans la liste par défaut.

## Hors scope

- Fusion avec `REGISTRY` (`tool_registry.py`) — décision explicite de l'utilisateur
  de garder les deux séparés pour l'instant.
- Interface d'administration pour éditer le YAML depuis le navigateur — l'édition
  se fait directement dans le fichier.
