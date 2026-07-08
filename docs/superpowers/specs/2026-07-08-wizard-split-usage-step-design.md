# PolicyBot — Scinder l'étape "Ton usage" en deux écrans

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan
**Context:** Suite de [`2026-07-06-policybot-web-ui-design.md`](2026-07-06-policybot-web-ui-design.md)
(§7 « Step 3 — Usage »), qui décrivait l'étape 3 comme un seul écran couvrant à la
fois le mode d'usage de l'outil et l'usage prévu des résultats. En pratique, l'écran
actuel (`wizard_usage.html.j2`) mélange déjà deux questions distinctes dans son
propre HTML : le `<h1>` en dur « Comment vas-tu utiliser cet outil ? » (mode + description)
et `question.question` = « Comment comptez-vous utiliser les résultats ? »
(checkboxes `usage_details_question()` + décision automatisée). Ce spec les sépare en
deux étapes du wizard.

## 1. Purpose

Rendre l'étape 3 plus lisible en la scindant en deux écrans successifs, chacun posant
une seule question à la fois — cohérent avec le reste du wizard (une carte de
checkboxes par écran). Aucun changement de logique métier : `WizardState`,
`usage_details_question()`, et `Interview.assess` restent inchangés, tous les champs
nécessaires existent déjà.

**Hors scope :** renommer/reformuler les questions elles-mêmes, changer le mécanisme
`suggest_options`/`guess_mode`, ajouter de la validation de champs requis (déjà différé
dans le spec du 07-06, §13).

## 2. Écrans

### Écran A — "Ton usage" (inchangé dans son URL de step, `active_step="usage"`)

- Reste servi par `POST /wizard/donnees` → `wizard_usage.html.j2`.
- Contenu : uniquement le mode (`prompt`/`api`, radio pré-deviné via
  `hx-post="/wizard/mode-guess"`) + la description libre `usage_description`.
- Retire les checkboxes `result_use_checked`, le champ `result_use_free_text`, et la
  case `automated_decisions` (déplacés vers l'écran B).
- Le formulaire soumet vers `POST /wizard/usage` (URL inchangée), qui ne fait
  maintenant *que* valider mode + description et re-render l'écran B — il n'appelle
  plus `Interview.assess`.

### Écran B — "Usage des résultats" (nouvelle étape, `active_step="resultats"`)

- Nouveau template `wizard_resultats.html.j2`, rendu par la réponse de
  `POST /wizard/usage`.
- Contenu : les checkboxes de `usage_details_question()` (question affichée telle
  quelle : « Comment comptez-vous utiliser les résultats ? »), le champ "Autre"
  (`hx-post="/wizard/suggest/usage"`, inchangé), et la case "Décision automatisée".
- Le formulaire soumet vers une nouvelle route `POST /wizard/resultats`, qui reprend
  le code actuel de `wizard_usage_submit` : compose `usage_input`, appelle
  `itv.assess(...)`, gère l'exception (log + `error.html.j2` en 502), et rend
  `resultat.html.j2` en cas de succès.

## 3. Stepper (`_steps.html.j2`)

`order` passe de `["outil", "donnees", "usage", "resultat"]` à
`["outil", "donnees", "usage", "resultats", "resultat"]`. `labels` gagne
`"resultats": "Usage des résultats"`. Le libellé `"resultat": "Résultat"` (rapport
final) reste inchangé et distinct — pas de confusion entre les deux clés malgré la
proximité des noms, puisque les labels affichés diffèrent clairement
("Usage des résultats" vs "Résultat").

## 4. Changements dans `routes.py`

- `wizard_usage_submit` (actuel `POST /wizard/usage`, lignes 144-176) est coupé en
  deux fonctions :
  - `wizard_usage_submit` (conservée sur `POST /wizard/usage`) : lit `mode` +
    `usage_description` du form, construit `WizardState.from_form(form)`, et rend
    `wizard_resultats.html.j2` avec `active_step="resultats"`,
    `hidden_fields=state.to_hidden_fields()`, `question=usage_details_question()`.
  - `wizard_resultats_submit` (nouvelle, `POST /wizard/resultats`) : reprend tel quel
    le corps actuel de `wizard_usage_submit` à partir de
    `state = WizardState.from_form(form)` jusqu'à la fin (composition de
    `usage_input`, appel `itv.assess`, gestion d'erreur, rendu `resultat.html.j2`).
- Aucun changement à `/wizard/mode-guess` ni `/wizard/suggest/usage` : ces deux
  routes restent génériques (elles ne connaissent que le form posté, pas l'écran qui
  les a déclenchées) et fonctionnent identiquement peu importe l'écran d'où provient
  la requête HTMX.
- Aucun changement à `WizardState`, `wizard_state.py`, `ai_assist.py`, ou
  `questions.py` — tous les champs traversent déjà les hidden fields d'un écran à
  l'autre.

## 5. Testing

- `tests/web/test_routes_usage.py` est scindé en deux groupes de cas :
  - Soumission de l'écran A (`POST /wizard/usage` avec mode + description) → attend
    le rendu de `wizard_resultats.html.j2` avec `active_step="resultats"` et les
    hidden fields carrying forward tool_name/data/mode/description.
  - Soumission de l'écran B (`POST /wizard/resultats` avec result_use + décision
    automatisée) → attend soit `resultat.html.j2` (succès), soit `error.html.j2` en
    502 (si `Interview.assess` lève), reprenant les cas déjà couverts par l'ancien
    test de `POST /wizard/usage`.
- Le test end-to-end du scénario doré (README, ChatGPT + Protégé B ⇒ INTERDIT/Refuser)
  est mis à jour pour poster sur les deux routes dans l'ordre au lieu d'une seule.

## 6. Deferred

- Fusionner à nouveau les deux écrans si l'usage réel montre que le passage
  supplémentaire ralentit inutilement l'utilisateur — pas de données pour trancher
  aujourd'hui, décision purement UX à revisiter après usage.
