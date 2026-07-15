# Navigation cliquable entre les étapes du wizard — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permettre à l'utilisateur de cliquer sur une icône d'étape déjà complétée dans la barre latérale du wizard pour y revenir, avec toutes les réponses (y compris celles des étapes suivantes) conservées.

**Architecture:** Le wizard reste stateless côté serveur. Chaque icône d'étape "done" devient un `<button>` relié (via l'attribut HTML `form`) au formulaire de la page courante ; il le soumet vers une nouvelle route `POST /wizard/goto/{étape}` qui reconstruit `WizardState` depuis le formulaire soumis et rerend le template de l'étape ciblée, pré-rempli. Les routes d'avancement existantes et les nouvelles routes de retour partagent les mêmes fonctions `_render_*` de construction de contexte de template.

**Tech Stack:** FastAPI (`policybot/web/routes.py`), Jinja2 (`policybot/web/templates/*.html.j2`), `TestClient` de `fastapi.testclient` pour les tests.

## Global Constraints

- Pas de session serveur ni de stockage persistant de l'état du wizard : l'état continue de circuler uniquement via les champs cachés du formulaire soumis (`WizardState.to_hidden_fields()` / `WizardState.from_form()`).
- Seules les étapes déjà visitées ("done", ✓) sont cliquables ; l'étape active et les étapes futures ne le sont pas.
- L'étape "Résultat" (rapport final généré) n'est jamais navigable en arrière — elle n'a pas de route `goto`.
- Revenir sur une étape doit toujours réafficher le **brouillon d'usage courant** (`WizardState.current_usage_draft()`), jamais un usage déjà sauvegardé dans `saved_usages` — comportement déjà natif de `WizardState`, aucune logique nouvelle requise.
- Revenir sur l'étape "outil" doit toujours rerendre `wizard_outil.html.j2` (le formulaire principal), jamais l'écran intermédiaire `wizard_tool_type.html.j2`.
- Chaque formulaire d'étape porte `id="wizard-form"` ; les boutons de la barre latérale utilisent `form="wizard-form"` et `formnovalidate` pour soumettre ce formulaire sans déclencher la validation HTML5 des champs `required` de la page courante.
- `git commit` après chaque tâche ; ne jamais grouper plusieurs tâches dans un seul commit.

---

## File Structure

- **Modify** `policybot/web/routes.py` : factorise les fonctions `_render_profil_utilisateurs`, `_render_donnees`, `_render_usage`, `_render_resultats`, `_render_contexte_affaires` (à côté de `_render_outil`, déjà existante) ; ajoute 6 routes `POST /wizard/goto/{étape}`.
- **Modify** `policybot/web/templates/wizard_profil_utilisateurs.html.j2`, `wizard_donnees.html.j2`, `wizard_usage.html.j2`, `wizard_resultats.html.j2` : pré-remplissent leurs champs depuis `state` (absent aujourd'hui).
- **Modify** tous les templates `wizard_*.html.j2` portant un `<form method="post" ...>` d'étape : ajoutent `id="wizard-form"`.
- **Modify** `policybot/web/templates/_steps.html.j2` : les icônes "done" deviennent des `<button>` pointant vers `/wizard/goto/{étape}`.
- **Modify** `policybot/web/static/style.css` : reset visuel pour que `<button class="st done">` ait le même rendu que l'ancien `<div>`.
- **Create** `tests/web/test_routes_goto.py` : tests des nouvelles routes `goto` et de la barre latérale.

---

### Task 1: Factoriser les fonctions de rendu partagées (refactor, aucun changement de comportement)

**Files:**
- Modify: `policybot/web/routes.py:84-263`

**Interfaces:**
- Produces: `_render_profil_utilisateurs(request: Request, state: WizardState) -> HTMLResponse`, `_render_donnees(request: Request, state: WizardState) -> HTMLResponse`, `_render_usage(request: Request, state: WizardState) -> HTMLResponse`, `_render_resultats(request: Request, state: WizardState) -> HTMLResponse`, `_render_contexte_affaires(request: Request, state: WizardState) -> HTMLResponse` — utilisées par les tâches suivantes (routes d'avancement existantes ET nouvelles routes `goto`).
- Consumes: `_render_outil(request, state, errors=None)` (déjà existante, `policybot/web/routes.py:84-90`), `_hidden_fields_for(state, fields)` (existante), `WizardState`, `PROFILE_FIELDS`, `DATA_FIELDS`, `USAGE_FIELDS`, `RESULT_FIELDS`, `CONTEXT_FIELDS` (déjà définies en haut du fichier).

- [ ] **Step 1: Baseline — confirmer que la suite de tests web passe avant tout changement**

Run: `pytest tests/web -v`
Expected: tous les tests PASS (aucun échec). Note le nombre de tests passés pour comparaison après refactor.

- [ ] **Step 2: Ajouter les 5 fonctions `_render_*` juste après `_render_outil`**

Dans `policybot/web/routes.py`, juste après la fonction `_render_outil` (qui se termine à la ligne 90 par `}, status_code=422 if errors else 200)`), insérer :

```python
def _render_profil_utilisateurs(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
        "active_step": "profil_utilisateurs",
        "hidden_fields": _hidden_fields_for(state, PROFILE_FIELDS),
        "state": state,
    })


def _render_donnees(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_donnees.html.j2", {
        "active_step": "donnees",
        "hidden_fields": _hidden_fields_for(state, DATA_FIELDS),
        "state": state,
        "question": data_description_question(),
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_usage(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": _hidden_fields_for(state, USAGE_FIELDS),
        "state": state,
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_resultats(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_resultats.html.j2", {
        "active_step": "resultats",
        "hidden_fields": _hidden_fields_for(state, RESULT_FIELDS),
        "state": state,
        "question": usage_details_question(),
        "usage_number": len(state.saved_usages) + 1,
    })


def _render_contexte_affaires(request: Request, state: WizardState):
    return templates.TemplateResponse(request, "wizard_contexte_affaires.html.j2", {
        "active_step": "contexte_affaires",
        "hidden_fields": _hidden_fields_for(state, CONTEXT_FIELDS),
        "state": state,
    })
```

- [ ] **Step 3: Remplacer les blocs `TemplateResponse` inline par des appels aux fonctions factorisées**

Dans `wizard_test_prefill` (route `POST /wizard/test-prefill`), remplacer :

```python
    state = demo_wizard_state()
    return templates.TemplateResponse(request, "wizard_contexte_affaires.html.j2", {
        "active_step": "contexte_affaires",
        "hidden_fields": _hidden_fields_for(state, CONTEXT_FIELDS),
        "state": state,
    })
```

par :

```python
    state = demo_wizard_state()
    return _render_contexte_affaires(request, state)
```

Dans `wizard_outil` (route `POST /wizard/outil`), remplacer le bloc qui rend `wizard_profil_utilisateurs.html.j2` :

```python
    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
            "active_step": "profil_utilisateurs", "hidden_fields": _hidden_fields_for(state, PROFILE_FIELDS), "state": state,
        })
```

par :

```python
    if classify_tool_type(tool_name) is not None or lookup_tool(tool_name) is not None:
        return _render_profil_utilisateurs(request, state)
```

Dans `wizard_outil_type` (route `POST /wizard/outil/type`), remplacer :

```python
    return templates.TemplateResponse(request, "wizard_profil_utilisateurs.html.j2", {
        "active_step": "profil_utilisateurs",
        "hidden_fields": _hidden_fields_for(state, PROFILE_FIELDS),
        "state": state,
    })
```

par :

```python
    return _render_profil_utilisateurs(request, state)
```

Dans `wizard_profil_utilisateurs_submit` (route `POST /wizard/profil-utilisateurs`), remplacer :

```python
    return templates.TemplateResponse(request, "wizard_donnees.html.j2", {
        "active_step": "donnees",
        "hidden_fields": _hidden_fields_for(state, DATA_FIELDS),
        "state": state,
        "question": data_description_question(),
    })
```

par :

```python
    return _render_donnees(request, state)
```

Dans `wizard_donnees` (route `POST /wizard/donnees`), remplacer :

```python
    return templates.TemplateResponse(request, "wizard_usage.html.j2", {
        "active_step": "usage",
        "hidden_fields": _hidden_fields_for(state, USAGE_FIELDS),
        "state": state,
        "usage_number": len(state.saved_usages) + 1,
    })
```

par :

```python
    return _render_usage(request, state)
```

Dans `wizard_usage_submit` (route `POST /wizard/usage`), remplacer :

```python
    return templates.TemplateResponse(request, "wizard_resultats.html.j2", {
        "active_step": "resultats",
        "hidden_fields": _hidden_fields_for(state, RESULT_FIELDS),
        "state": state,
        "question": usage_details_question(),
        "usage_number": len(state.saved_usages) + 1,
    })
```

par :

```python
    return _render_resultats(request, state)
```

Dans `wizard_resultats_submit` (route `POST /wizard/resultats`), remplacer le corps complet par :

```python
@router.post("/wizard/resultats", response_class=HTMLResponse)
async def wizard_resultats_submit(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    if form.get("usage_action") == "add_usage":
        state = state.with_current_usage_saved().cleared_current_usage()
        return _render_donnees(request, state)
    return _render_contexte_affaires(request, state)
```

- [ ] **Step 4: Vérifier qu'aucun test existant n'a régressé**

Run: `pytest tests/web -v`
Expected: même nombre de tests PASS qu'à l'étape 1, aucun échec. Le HTML produit est strictement identique (mêmes dictionnaires de contexte qu'avant refactor).

- [ ] **Step 5: Commit**

```bash
git add policybot/web/routes.py
git commit -m "refactor: factorise le rendu des étapes du wizard en fonctions _render_*"
```

---

### Task 2: Ajouter `id="wizard-form"` au formulaire principal de chaque étape

**Files:**
- Modify: `policybot/web/templates/wizard_outil.html.j2:7`
- Modify: `policybot/web/templates/wizard_tool_type.html.j2:7`
- Modify: `policybot/web/templates/wizard_profil_utilisateurs.html.j2:7`
- Modify: `policybot/web/templates/wizard_donnees.html.j2:7`
- Modify: `policybot/web/templates/wizard_usage.html.j2:7`
- Modify: `policybot/web/templates/wizard_resultats.html.j2:7`
- Modify: `policybot/web/templates/wizard_contexte_affaires.html.j2:7`

**Interfaces:**
- Produces: chaque page d'étape expose un `<form id="wizard-form" ...>` — c'est la cible du `form="wizard-form"` utilisé par les boutons de la barre latérale (Task 9).
- Consumes: aucune (changement purement HTML).

- [ ] **Step 1: Ajouter l'attribut `id` sur chaque formulaire d'étape**

Dans `wizard_outil.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/outil">
```
par :
```html
<form method="post" action="/wizard/outil" id="wizard-form">
```
(Ne pas toucher au second `<form action="/wizard/test-prefill">` de ce même fichier — il n'a pas besoin de cet id.)

Dans `wizard_tool_type.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/outil/type">
```
par :
```html
<form method="post" action="/wizard/outil/type" id="wizard-form">
```

Dans `wizard_profil_utilisateurs.html.j2` ligne 7, remplacer :
```html
<form class="profile-form" method="post" action="/wizard/profil-utilisateurs">
```
par :
```html
<form class="profile-form" method="post" action="/wizard/profil-utilisateurs" id="wizard-form">
```

Dans `wizard_donnees.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/donnees">
```
par :
```html
<form method="post" action="/wizard/donnees" id="wizard-form">
```

Dans `wizard_usage.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/usage">
```
par :
```html
<form method="post" action="/wizard/usage" id="wizard-form">
```

Dans `wizard_resultats.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/resultats">
```
par :
```html
<form method="post" action="/wizard/resultats" id="wizard-form">
```

Dans `wizard_contexte_affaires.html.j2` ligne 7, remplacer :
```html
<form method="post" action="/wizard/contexte-affaires" data-loading-overlay>
```
par :
```html
<form method="post" action="/wizard/contexte-affaires" data-loading-overlay id="wizard-form">
```

- [ ] **Step 2: Vérifier qu'aucun test existant n'a régressé**

Run: `pytest tests/web -v`
Expected: tous les tests PASS (aucune assertion existante ne dépend de l'absence de cet attribut).

- [ ] **Step 3: Commit**

```bash
git add policybot/web/templates/wizard_outil.html.j2 policybot/web/templates/wizard_tool_type.html.j2 policybot/web/templates/wizard_profil_utilisateurs.html.j2 policybot/web/templates/wizard_donnees.html.j2 policybot/web/templates/wizard_usage.html.j2 policybot/web/templates/wizard_resultats.html.j2 policybot/web/templates/wizard_contexte_affaires.html.j2
git commit -m "feat: identifie le formulaire de chaque étape du wizard (id=wizard-form)"
```

---

### Task 3: Pré-remplissage + route retour pour l'étape "Profil utilisateurs"

**Files:**
- Modify: `policybot/web/templates/wizard_profil_utilisateurs.html.j2`
- Modify: `policybot/web/routes.py`
- Create/Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_profil_utilisateurs(request, state)` (Task 1), `_group_form` (existante), `WizardState.from_form` (existante).
- Produces: route `POST /wizard/goto/profil-utilisateurs`.

- [ ] **Step 1: Écrire le test qui échoue**

Créer `tests/web/test_routes_goto.py` :

```python
from fastapi.testclient import TestClient
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview
from policybot.api.app import create_app


def _client(tmp_path, json_responses=None):
    llm = FakeLLMProvider(json_responses=json_responses or [])
    itv = Interview(llm=llm, store=PreApprovedStore(str(tmp_path / "pb.db")),
                    http_get=lambda url: "<html><body>ok</body></html>")
    return TestClient(create_app(itv))


def test_goto_profil_utilisateurs_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/profil-utilisateurs", data={
        "tool_name": "ChatGPT",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
    })
    assert resp.status_code == 200
    assert "profil" in resp.text.lower()
    assert 'name="nb_utilisateurs_vises" value="25"' in resp.text
    assert 'name="fonctions_roles" value="conseillers pédagogiques"' in resp.text
    assert 'name="niveau_maitrise_ti" value="intermédiaire" checked' in resp.text
    assert 'name="formation_iag_recue" value="partielle" checked' in resp.text
    assert 'name="acces_protege_a_ou_plus" value="non" checked' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_profil_utilisateurs_prefills_state -v`
Expected: FAIL avec 404 (la route `/wizard/goto/profil-utilisateurs` n'existe pas encore) — `assert resp.status_code == 200` échoue.

- [ ] **Step 3: Pré-remplir `wizard_profil_utilisateurs.html.j2` depuis `state`**

Remplacer les deux champs texte (lignes 17 et 21 du fichier original) :
```html
        <input type="number" name="nb_utilisateurs_vises" min="0" placeholder="ex. 25">
```
par :
```html
        <input type="number" name="nb_utilisateurs_vises" min="0" placeholder="ex. 25" value="{{ state.nb_utilisateurs_vises }}">
```
et :
```html
        <input type="text" name="fonctions_roles" placeholder="ex. agents de bureau, conseillers pédagogiques">
```
par :
```html
        <input type="text" name="fonctions_roles" placeholder="ex. agents de bureau, conseillers pédagogiques" value="{{ state.fonctions_roles|e }}">
```

Remplacer les 3 groupes de boutons radio pour qu'ils reflètent `state`. Pour `niveau_maitrise_ti` :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="débutant"></div>
        <strong>D&eacute;butant</strong>
        <small>Peu &agrave; l'aise avec les outils num&eacute;riques ou besoin d'un guidage serr&eacute;.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="intermédiaire"></div>
        <strong>Interm&eacute;diaire</strong>
        <small>Utilise d&eacute;j&agrave; des outils num&eacute;riques au quotidien avec une autonomie correcte.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="avancé"></div>
        <strong>Avanc&eacute;</strong>
        <small>&Agrave; l'aise avec les outils complexes, les param&eacute;trages et les usages plus pouss&eacute;s.</small>
      </label>
```
devient :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="débutant" {% if state.niveau_maitrise_ti == "débutant" %}checked{% endif %}></div>
        <strong>D&eacute;butant</strong>
        <small>Peu &agrave; l'aise avec les outils num&eacute;riques ou besoin d'un guidage serr&eacute;.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="intermédiaire" {% if state.niveau_maitrise_ti == "intermédiaire" %}checked{% endif %}></div>
        <strong>Interm&eacute;diaire</strong>
        <small>Utilise d&eacute;j&agrave; des outils num&eacute;riques au quotidien avec une autonomie correcte.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="niveau_maitrise_ti" value="avancé" {% if state.niveau_maitrise_ti == "avancé" %}checked{% endif %}></div>
        <strong>Avanc&eacute;</strong>
        <small>&Agrave; l'aise avec les outils complexes, les param&eacute;trages et les usages plus pouss&eacute;s.</small>
      </label>
```

Pour `formation_iag_recue` :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="aucune"></div>
        <strong>Aucune</strong>
        <small>Aucune formation formelle ou rappel sur les bonnes pratiques.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="partielle"></div>
        <strong>Partielle</strong>
        <small>Quelques notions vues, mais pas encore un parcours complet.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="complète"></div>
        <strong>Compl&egrave;te (MCN)</strong>
        <small>Le groupe a d&eacute;j&agrave; suivi la formation compl&egrave;te pr&eacute;vue par l'organisation.</small>
      </label>
```
devient :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="aucune" {% if state.formation_iag_recue == "aucune" %}checked{% endif %}></div>
        <strong>Aucune</strong>
        <small>Aucune formation formelle ou rappel sur les bonnes pratiques.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="partielle" {% if state.formation_iag_recue == "partielle" %}checked{% endif %}></div>
        <strong>Partielle</strong>
        <small>Quelques notions vues, mais pas encore un parcours complet.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="formation_iag_recue" value="complète" {% if state.formation_iag_recue == "complète" %}checked{% endif %}></div>
        <strong>Compl&egrave;te (MCN)</strong>
        <small>Le groupe a d&eacute;j&agrave; suivi la formation compl&egrave;te pr&eacute;vue par l'organisation.</small>
      </label>
```

Pour `acces_protege_a_ou_plus` :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="oui"></div>
        <strong>Oui</strong>
        <small>Le groupe a acc&egrave;s &agrave; de l'information Prot&eacute;g&eacute; A, B ou plus.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="non"></div>
        <strong>Non</strong>
        <small>Le groupe ne manipule pas ce niveau d'information dans son travail courant.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="à vérifier"></div>
        <strong>&Agrave; v&eacute;rifier</strong>
        <small>L'information n'est pas confirm&eacute;e pour l'instant.</small>
      </label>
```
devient :
```html
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="oui" {% if state.acces_protege_a_ou_plus == "oui" %}checked{% endif %}></div>
        <strong>Oui</strong>
        <small>Le groupe a acc&egrave;s &agrave; de l'information Prot&eacute;g&eacute; A, B ou plus.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="non" {% if state.acces_protege_a_ou_plus == "non" %}checked{% endif %}></div>
        <strong>Non</strong>
        <small>Le groupe ne manipule pas ce niveau d'information dans son travail courant.</small>
      </label>
      <label class="opt">
        <div class="top"><input type="radio" name="acces_protege_a_ou_plus" value="à vérifier" {% if state.acces_protege_a_ou_plus == "à vérifier" %}checked{% endif %}></div>
        <strong>&Agrave; v&eacute;rifier</strong>
        <small>L'information n'est pas confirm&eacute;e pour l'instant.</small>
      </label>
```

- [ ] **Step 4: Ajouter la route `POST /wizard/goto/profil-utilisateurs`**

Dans `policybot/web/routes.py`, ajouter après la route `wizard_outil_type` (donc avant `wizard_profil_utilisateurs_submit`) :

```python
@router.post("/wizard/goto/profil-utilisateurs", response_class=HTMLResponse)
async def wizard_goto_profil_utilisateurs(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_profil_utilisateurs(request, state)
```

- [ ] **Step 5: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_profil_utilisateurs_prefills_state -v`
Expected: PASS

- [ ] **Step 6: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 7: Commit**

```bash
git add policybot/web/templates/wizard_profil_utilisateurs.html.j2 policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Profil utilisateurs avec pré-remplissage"
```

---

### Task 4: Pré-remplissage + route retour pour l'étape "Tes données"

**Files:**
- Modify: `policybot/web/templates/wizard_donnees.html.j2`
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_donnees(request, state)` (Task 1).
- Produces: route `POST /wizard/goto/donnees`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_donnees_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/donnees", data={
        "tool_name": "ChatGPT",
        "data_checked": ["Renseignements personnels", "Documents internes de travail"],
        "data_free_text": "notes de cours",
    })
    assert resp.status_code == 200
    assert "données" in resp.text.lower()
    assert 'name="data_checked" value="Renseignements personnels" checked' in resp.text
    assert 'name="data_checked" value="Documents internes de travail" checked' in resp.text
    assert 'name="data_free_text" value="notes de cours"' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_donnees_prefills_state -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Pré-remplir `wizard_donnees.html.j2` depuis `state`**

Remplacer :
```html
      <label class="opt">
        <div class="top"><input type="checkbox" name="data_checked" value="{{ opt.label }}"></div>
        <b>{{ opt.label }}</b><small>{{ opt.description }}</small>
      </label>
```
par :
```html
      <label class="opt">
        <div class="top"><input type="checkbox" name="data_checked" value="{{ opt.label }}" {% if opt.label in state.data_checked %}checked{% endif %}></div>
        <b>{{ opt.label }}</b><small>{{ opt.description }}</small>
      </label>
```

Remplacer :
```html
    <input type="text" name="data_free_text"
           hx-post="/wizard/suggest/donnees" hx-trigger="changed delay:500ms"
           hx-target="#suggested-donnees" hx-swap="innerHTML">
```
par :
```html
    <input type="text" name="data_free_text" value="{{ state.data_free_text|e }}"
           hx-post="/wizard/suggest/donnees" hx-trigger="changed delay:500ms"
           hx-target="#suggested-donnees" hx-swap="innerHTML">
```

- [ ] **Step 4: Ajouter la route `POST /wizard/goto/donnees`**

Dans `policybot/web/routes.py`, ajouter après la route `wizard_profil_utilisateurs_submit` :

```python
@router.post("/wizard/goto/donnees", response_class=HTMLResponse)
async def wizard_goto_donnees(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_donnees(request, state)
```

- [ ] **Step 5: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_donnees_prefills_state -v`
Expected: PASS

- [ ] **Step 6: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 7: Commit**

```bash
git add policybot/web/templates/wizard_donnees.html.j2 policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Tes données avec pré-remplissage"
```

---

### Task 5: Pré-remplissage + route retour pour l'étape "Ton usage"

**Files:**
- Modify: `policybot/web/templates/wizard_usage.html.j2`
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_usage(request, state)` (Task 1).
- Produces: route `POST /wizard/goto/usage`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_usage_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/usage", data={
        "tool_name": "ChatGPT",
        "usage_description": "Chercher des informations publiques",
        "mode": "api",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "10",
        "systemes_api_cibles": "CRM interne",
    })
    assert resp.status_code == 200
    assert "usage" in resp.text.lower()
    assert 'name="usage_description" value="Chercher des informations publiques"' in resp.text
    assert 'name="mode" value="api" checked' in resp.text
    assert 'name="frequence_utilisation" value="quelques fois par semaine"' in resp.text
    assert 'name="nb_utilisateurs" value="10"' in resp.text
    assert 'name="systemes_api_cibles" value="CRM interne"' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_usage_prefills_state -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Pré-remplir `wizard_usage.html.j2` depuis `state`**

Remplacer :
```html
  <label class="freefield">
    Description de l'usage :
    <input type="text" name="usage_description"
           hx-post="/wizard/mode-guess" hx-trigger="changed delay:500ms"
           hx-target="#mode-fragment" hx-swap="innerHTML">
  </label>
  <div id="mode-fragment">
    <label><input type="radio" name="mode" value="prompt" checked> Je tape mes questions directement</label>
    <label><input type="radio" name="mode" value="api"> C'est intégré à un autre système (API)</label>
  </div>
  <label class="freefield">
    Fréquence d'utilisation prévue :
    <input type="text" name="frequence_utilisation" placeholder="ex. quelques fois par semaine">
  </label>
  <label class="freefield">
    Nombre d'utilisateurs pour cet usage :
    <input type="number" name="nb_utilisateurs" min="0">
  </label>
  <label class="freefield">
    Systèmes cibles si intégré par API :
    <input type="text" name="systemes_api_cibles" placeholder="ex. CRM interne, portail étudiant">
  </label>
```
par :
```html
  <label class="freefield">
    Description de l'usage :
    <input type="text" name="usage_description" value="{{ state.usage_description|e }}"
           hx-post="/wizard/mode-guess" hx-trigger="changed delay:500ms"
           hx-target="#mode-fragment" hx-swap="innerHTML">
  </label>
  <div id="mode-fragment">
    <label><input type="radio" name="mode" value="prompt" {% if state.mode != "api" %}checked{% endif %}> Je tape mes questions directement</label>
    <label><input type="radio" name="mode" value="api" {% if state.mode == "api" %}checked{% endif %}> C'est intégré à un autre système (API)</label>
  </div>
  <label class="freefield">
    Fréquence d'utilisation prévue :
    <input type="text" name="frequence_utilisation" placeholder="ex. quelques fois par semaine" value="{{ state.frequence_utilisation|e }}">
  </label>
  <label class="freefield">
    Nombre d'utilisateurs pour cet usage :
    <input type="number" name="nb_utilisateurs" min="0" value="{{ state.nb_utilisateurs }}">
  </label>
  <label class="freefield">
    Systèmes cibles si intégré par API :
    <input type="text" name="systemes_api_cibles" placeholder="ex. CRM interne, portail étudiant" value="{{ state.systemes_api_cibles|e }}">
  </label>
```

`state.mode != "api"` reproduit le défaut actuel (case "prompt" cochée par défaut quand `state.mode` est `None`), tout en cochant "api" quand `state.mode == "api"`.

- [ ] **Step 4: Ajouter la route `POST /wizard/goto/usage`**

Dans `policybot/web/routes.py`, ajouter après la route `wizard_donnees` :

```python
@router.post("/wizard/goto/usage", response_class=HTMLResponse)
async def wizard_goto_usage(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_usage(request, state)
```

- [ ] **Step 5: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_usage_prefills_state -v`
Expected: PASS

- [ ] **Step 6: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 7: Commit**

```bash
git add policybot/web/templates/wizard_usage.html.j2 policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Ton usage avec pré-remplissage"
```

---

### Task 6: Pré-remplissage + route retour pour l'étape "Usage des résultats"

**Files:**
- Modify: `policybot/web/templates/wizard_resultats.html.j2`
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_resultats(request, state)` (Task 1).
- Produces: route `POST /wizard/goto/resultats`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_resultats_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/resultats", data={
        "tool_name": "ChatGPT",
        "result_use_checked": ["Publication"],
        "result_use_free_text": "validation humaine avant diffusion",
        "automated_decisions": "true",
    })
    assert resp.status_code == 200
    assert "usage des résultats" in resp.text.lower()
    assert 'name="result_use_checked" value="Publication" checked' in resp.text
    assert 'name="result_use_free_text" value="validation humaine avant diffusion"' in resp.text
    assert 'name="automated_decisions" value="true" checked' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_resultats_prefills_state -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Pré-remplir `wizard_resultats.html.j2` depuis `state`**

Remplacer :
```html
      <label class="opt">
        <div class="top"><input type="checkbox" name="result_use_checked" value="{{ opt.label }}"></div>
        <b>{{ opt.label }}</b>
      </label>
```
par :
```html
      <label class="opt">
        <div class="top"><input type="checkbox" name="result_use_checked" value="{{ opt.label }}" {% if opt.label in state.result_use_checked %}checked{% endif %}></div>
        <b>{{ opt.label }}</b>
      </label>
```

Remplacer :
```html
    <input type="text" name="result_use_free_text"
           hx-post="/wizard/suggest/usage" hx-trigger="changed delay:500ms"
           hx-target="#suggested-usage" hx-swap="innerHTML">
```
par :
```html
    <input type="text" name="result_use_free_text" value="{{ state.result_use_free_text|e }}"
           hx-post="/wizard/suggest/usage" hx-trigger="changed delay:500ms"
           hx-target="#suggested-usage" hx-swap="innerHTML">
```

Remplacer :
```html
    <div class="top"><input type="checkbox" name="automated_decisions" value="true"></div>
```
par :
```html
    <div class="top"><input type="checkbox" name="automated_decisions" value="true" {% if state.automated_decisions %}checked{% endif %}></div>
```

- [ ] **Step 4: Ajouter la route `POST /wizard/goto/resultats`**

Dans `policybot/web/routes.py`, ajouter après la route `wizard_usage_submit` :

```python
@router.post("/wizard/goto/resultats", response_class=HTMLResponse)
async def wizard_goto_resultats(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_resultats(request, state)
```

- [ ] **Step 5: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_resultats_prefills_state -v`
Expected: PASS

- [ ] **Step 6: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 7: Commit**

```bash
git add policybot/web/templates/wizard_resultats.html.j2 policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Usage des résultats avec pré-remplissage"
```

---

### Task 7: Route retour pour l'étape "Ton outil" (déjà pré-remplie)

**Files:**
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_outil(request, state, errors=None)` (existante, Task 1 ne la modifie pas).
- Produces: route `POST /wizard/goto/outil`.

`wizard_outil.html.j2` reflète déjà entièrement `state` (tool_name, demandeur, unite, version_plan_tarifaire) — aucune modification de template n'est nécessaire ici.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_outil_renders_main_form_not_tool_type_screen(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/outil", data={
        "tool_name": "Notion AI",
        "demandeur": "Marie Tremblay",
        "unite": "Direction TI",
        "tool_type_override": "circuit_ferme",
    })
    assert resp.status_code == 200
    assert "Quel outil d'IA générative" in resp.text
    assert 'value="Notion AI"' in resp.text
    assert 'name="demandeur" value="Marie Tremblay"' in resp.text
    assert 'name="unite" value="Direction TI"' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_outil_renders_main_form_not_tool_type_screen -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Ajouter la route `POST /wizard/goto/outil`**

Dans `policybot/web/routes.py`, ajouter juste avant `wizard_outil` (donc en tout premier parmi les routes `/wizard/...`) :

```python
@router.post("/wizard/goto/outil", response_class=HTMLResponse)
async def wizard_goto_outil(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_outil(request, state)
```

- [ ] **Step 4: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_outil_renders_main_form_not_tool_type_screen -v`
Expected: PASS

- [ ] **Step 5: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 6: Commit**

```bash
git add policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Ton outil"
```

---

### Task 8: Route retour pour l'étape "Contexte d'affaires" (déjà pré-remplie)

**Files:**
- Modify: `policybot/web/routes.py`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: `_render_contexte_affaires(request, state)` (Task 1).
- Produces: route `POST /wizard/goto/contexte-affaires`.

`wizard_contexte_affaires.html.j2` reflète déjà entièrement `state` — aucune modification de template n'est nécessaire ici.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_contexte_affaires_prefills_state(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/goto/contexte-affaires", data={
        "tool_name": "ChatGPT",
        "besoin_affaires": "réduire le temps de traitement",
        "urgence_percue": "élevée",
        "mode_acquisition": "seao",
    })
    assert resp.status_code == 200
    assert "contexte d'affaires" in resp.text.lower()
    assert 'name="besoin_affaires" value="réduire le temps de traitement"' in resp.text
    assert 'name="urgence_percue" value="élevée" checked' in resp.text
    assert 'name="mode_acquisition" value="seao" checked' in resp.text
```

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_goto_contexte_affaires_prefills_state -v`
Expected: FAIL (404, route absente).

- [ ] **Step 3: Ajouter la route `POST /wizard/goto/contexte-affaires`**

Dans `policybot/web/routes.py`, ajouter après la route `wizard_goto_resultats` (Task 6) :

```python
@router.post("/wizard/goto/contexte-affaires", response_class=HTMLResponse)
async def wizard_goto_contexte_affaires(request: Request):
    form = _group_form(await request.form())
    state = WizardState.from_form(form)
    return _render_contexte_affaires(request, state)
```

- [ ] **Step 4: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_contexte_affaires_prefills_state -v`
Expected: PASS

- [ ] **Step 5: Vérifier l'absence de régression**

Run: `pytest tests/web -v`
Expected: tous les tests PASS.

- [ ] **Step 6: Commit**

```bash
git add policybot/web/routes.py tests/web/test_routes_goto.py
git commit -m "feat: route de retour vers l'étape Contexte d'affaires"
```

---

### Task 9: Rendre cliquables les icônes d'étapes déjà complétées

**Files:**
- Modify: `policybot/web/templates/_steps.html.j2`
- Modify: `policybot/web/static/style.css`
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: toutes les routes `POST /wizard/goto/{étape}` créées aux Tasks 3–8 ; `id="wizard-form"` ajouté à chaque formulaire d'étape (Task 2).
- Produces: barre latérale avec icônes "done" cliquables.

**Invariant exploité (voir `_steps.html.j2` existant) :** `order.index(active_step) > loop.index0` n'est vrai pour la dernière entrée de `order` ("resultat") que si `active_step` a un index strictement supérieur au sien — impossible puisque "resultat" est déjà le dernier élément. "resultat" ne peut donc jamais apparaître dans la branche "done" : pas besoin de l'exclure explicitement du mapping `goto_slugs`.

- [ ] **Step 1: Écrire le test qui échoue**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_steps_nav_renders_done_steps_as_clickable_buttons(tmp_path):
    client = _client(tmp_path)
    resp = client.post("/wizard/donnees", data={"tool_name": "ChatGPT"})
    assert resp.status_code == 200
    assert 'id="wizard-form"' in resp.text
    assert '<button type="submit" form="wizard-form" formaction="/wizard/goto/outil"' in resp.text
    assert '<button type="submit" form="wizard-form" formaction="/wizard/goto/profil-utilisateurs"' in resp.text
    assert 'formaction="/wizard/goto/usage"' not in resp.text
    assert 'formaction="/wizard/goto/resultats"' not in resp.text
    assert 'formaction="/wizard/goto/contexte-affaires"' not in resp.text
```

Ce test poste vers `/wizard/donnees`, qui rerend `wizard_usage.html.j2` avec `active_step="usage"` : "outil" et "profil_utilisateurs" sont "done" (donc cliquables), "usage" est actif, "resultats"/"contexte_affaires"/"resultat" sont futurs (donc non cliquables).

- [ ] **Step 2: Lancer le test et confirmer l'échec**

Run: `pytest tests/web/test_routes_goto.py::test_steps_nav_renders_done_steps_as_clickable_buttons -v`
Expected: FAIL — les icônes "done" sont encore des `<div>`, pas des `<button>`.

- [ ] **Step 3: Modifier `_steps.html.j2`**

Remplacer le contenu complet du fichier par :

```jinja
{# policybot/web/templates/_steps.html.j2 #}
{% set order = ["outil", "profil_utilisateurs", "donnees", "usage", "resultats", "contexte_affaires", "resultat"] %}
{% set labels = {"outil": "Ton outil", "profil_utilisateurs": "Profil utilisateurs", "donnees": "Tes données", "usage": "Ton usage", "resultats": "Usage des résultats", "contexte_affaires": "Contexte d'affaires", "resultat": "Résultat"} %}
{% set goto_slugs = {"outil": "outil", "profil_utilisateurs": "profil-utilisateurs", "donnees": "donnees", "usage": "usage", "resultats": "resultats", "contexte_affaires": "contexte-affaires"} %}
<nav class="steps">
{% for key in order %}
  {% if order.index(active_step) > loop.index0 %}
    <button type="submit" form="wizard-form" formaction="/wizard/goto/{{ goto_slugs[key] }}" formnovalidate class="st done"><span class="n">✓</span> {{ labels[key] }}</button>
  {% elif key == active_step %}
    <div class="st active"><span class="n">{{ loop.index }}</span> {{ labels[key] }}</div>
  {% else %}
    <div class="st"><span class="n">{{ loop.index }}</span> {{ labels[key] }}</div>
  {% endif %}
{% endfor %}
</nav>
```

- [ ] **Step 4: Ajuster le CSS pour que les boutons "done" ressemblent aux anciens `<div>`**

Dans `policybot/web/static/style.css`, juste après la ligne `.steps .st.active .n{border-color:var(--red);color:#fff;background:var(--red)}`, ajouter :

```css
.steps button.st{background:none;border:none;font:inherit;text-align:left;width:100%}
.steps button.st.done{cursor:pointer}
.steps button.st.done:hover{color:#fff}
.steps button.st.done:hover .n{background:#fff;color:var(--teal)}
```

- [ ] **Step 5: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_steps_nav_renders_done_steps_as_clickable_buttons -v`
Expected: PASS

- [ ] **Step 6: Vérifier l'absence de régression sur toute la suite**

Run: `pytest -v`
Expected: tous les tests PASS (suite complète, pas seulement `tests/web`).

- [ ] **Step 7: Commit**

```bash
git add policybot/web/templates/_steps.html.j2 policybot/web/static/style.css tests/web/test_routes_goto.py
git commit -m "feat: rend cliquables les icônes d'étapes déjà complétées dans la barre latérale"
```

---

### Task 10: Test d'acceptation — aller-retour préserve toutes les réponses

**Files:**
- Modify: `tests/web/test_routes_goto.py`

**Interfaces:**
- Consumes: toutes les routes créées aux Tasks 3–8.

- [ ] **Step 1: Écrire le test d'acceptation**

Ajouter à `tests/web/test_routes_goto.py` :

```python
def test_goto_back_then_forward_preserves_later_answers(tmp_path):
    client = _client(tmp_path)
    full_state_at_contexte_affaires = {
        "tool_name": "ChatGPT",
        "demandeur": "Marie Tremblay",
        "unite": "Direction TI",
        "nb_utilisateurs_vises": "25",
        "fonctions_roles": "conseillers pédagogiques",
        "niveau_maitrise_ti": "intermédiaire",
        "formation_iag_recue": "partielle",
        "acces_protege_a_ou_plus": "non",
        "data_checked": ["Renseignements personnels"],
        "data_free_text": "notes de cours",
        "usage_description": "Chercher des informations publiques",
        "mode": "prompt",
        "frequence_utilisation": "quelques fois par semaine",
        "nb_utilisateurs": "10",
        "result_use_checked": ["Publication"],
    }

    # Simule le clic sur l'icône "Tes données" depuis l'étape Contexte d'affaires.
    goto_resp = client.post("/wizard/goto/donnees", data=full_state_at_contexte_affaires)
    assert goto_resp.status_code == 200
    assert 'name="data_checked" value="Renseignements personnels" checked' in goto_resp.text
    assert 'name="data_free_text" value="notes de cours"' in goto_resp.text
    # Les réponses des étapes suivantes voyagent toujours, cachées, dans la page.
    assert 'name="usage_description" value="Chercher des informations publiques"' in goto_resp.text
    assert 'name="result_use_checked" value="Publication"' in goto_resp.text

    # L'utilisateur avance à nouveau depuis "Tes données" : tout ce qui suit doit ressortir intact.
    forward_resp = client.post("/wizard/donnees", data=full_state_at_contexte_affaires)
    assert forward_resp.status_code == 200
    assert 'name="usage_description" value="Chercher des informations publiques"' in forward_resp.text
    assert 'name="mode" value="prompt"' in forward_resp.text
    assert 'name="frequence_utilisation" value="quelques fois par semaine"' in forward_resp.text
    assert 'name="nb_utilisateurs" value="10"' in forward_resp.text
    assert 'name="result_use_checked" value="Publication"' in forward_resp.text
```

- [ ] **Step 2: Lancer le test et confirmer le succès**

Run: `pytest tests/web/test_routes_goto.py::test_goto_back_then_forward_preserves_later_answers -v`
Expected: PASS (toutes les tâches précédentes sont déjà en place, ce test ne fait que vérifier l'intégration bout en bout — s'il échoue, revoir les `_hidden_fields_for` / `PROFILE_FIELDS` / `DATA_FIELDS` / etc. de la tâche concernée).

- [ ] **Step 3: Lancer la suite complète une dernière fois**

Run: `pytest -v`
Expected: tous les tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/web/test_routes_goto.py
git commit -m "test: vérifie que l'aller-retour entre étapes préserve toutes les réponses"
```

---

## Self-Review (effectué avant remise du plan)

- **Couverture de la spec :** formulaire par étape identifié (Task 2) ; boutons cliquables uniquement sur "done" (Task 9) ; routes `goto` pour les 6 étapes formulaires, pas pour "resultat" (Tasks 3–8) ; pré-remplissage des 4 templates qui n'en avaient pas (Tasks 3–6) ; réutilisation des fonctions `_render_*` par les routes d'avancement ET de retour (Task 1, consommé partout) ; test d'acceptation "conserver tout" (Task 10). Aucune section de la spec n'est sans tâche correspondante.
- **Scan de placeholders :** aucun "TBD"/"TODO" ; chaque étape contient du code complet, exécutable tel quel.
- **Cohérence des types/signatures :** toutes les fonctions `_render_*` partagent la signature `(request: Request, state: WizardState) -> HTMLResponse` (via `TemplateResponse`), utilisée identiquement dans les routes d'avancement (Task 1) et de retour (Tasks 3–8). Les noms de routes goto suivent le même slug que l'action du formulaire correspondant (`/wizard/profil-utilisateurs` ↔ `/wizard/goto/profil-utilisateurs`, etc.).
