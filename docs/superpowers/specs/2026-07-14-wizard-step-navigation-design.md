# Navigation cliquable entre les étapes du wizard — conception

Date : 2026-07-14

## Contexte

Le wizard web (`policybot/web/routes.py`, `policybot/web/templates/`) affiche
dans la barre latérale (`_steps.html.j2`) une liste d'étapes numérotées, avec
une coche (✓) sur les étapes déjà passées et un style "actif" sur l'étape
courante. Ces indicateurs sont aujourd'hui de simples `<div>` non cliquables.

L'architecture du wizard est **entièrement stateless côté serveur** : chaque
étape est une route `POST` qui reçoit l'état complet (`WizardState`) via des
champs cachés injectés dans le formulaire de l'étape précédente
(`WizardState.to_hidden_fields()` / `WizardState.from_form()`), et le
transmet à la suivante. Il n'y a ni session serveur ni cookie porteur
d'état — ce choix est documenté dans CLAUDE.md et doit être préservé.

Le seul mécanisme de retour existant est le bouton « ← Retour », qui appelle
`history.back()` côté navigateur : il s'appuie sur le cache de formulaire du
navigateur (bfcache), pas sur un rendu serveur. Fait notable découvert en
lisant le code : les templates `wizard_profil_utilisateurs.html.j2`,
`wizard_donnees.html.j2`, `wizard_usage.html.j2` et
`wizard_resultats.html.j2` ne relisent **jamais** `state` pour pré-remplir
leurs propres champs (contrairement à `wizard_outil.html.j2` et
`wizard_contexte_affaires.html.j2`, qui le font déjà). Seul le cache
navigateur explique pourquoi ces champs semblent "conservés" aujourd'hui.

## Objectif

Permettre à l'utilisateur de cliquer sur une étape déjà complétée (icône ✓)
dans la barre latérale pour y revenir et modifier ses réponses, sans perdre
les réponses déjà saisies aux étapes suivantes. Les étapes futures (jamais
atteintes) restent non cliquables.

## Approche

Réutiliser le pattern stateless existant plutôt que d'introduire une session
serveur ou une réécriture SPA côté client :

1. **Un formulaire par étape, identifié.** Chaque `<form>` d'étape (outil,
   type d'outil, profil utilisateurs, données, usage, résultats, contexte
   d'affaires) reçoit `id="wizard-form"`.

2. **Icônes d'étape → boutons de soumission externes.** Dans
   `_steps.html.j2`, chaque étape marquée "done" devient un
   `<button type="submit" form="wizard-form" formaction="/wizard/goto/{clé}"
   formnovalidate>` au lieu d'un `<div>`. L'attribut HTML `form="wizard-form"`
   permet à un bouton situé dans `<aside>` (hors du `<form>`, qui vit dans
   `<main>`) de soumettre quand même ce formulaire — sans JavaScript.
   `formnovalidate` désactive la validation HTML5 (`required`) des champs de
   la page courante, puisqu'on quitte la page sans vouloir la valider.
   L'étape active et les étapes futures restent des `<div>` non cliquables
   (le calcul "done / active / futur" existe déjà dans le template).

3. **Nouvelles routes `POST /wizard/goto/{étape}`.** Une route par étape
   navigable (`outil`, `profil-utilisateurs`, `donnees`, `usage`,
   `resultats`, `contexte-affaires` — pas `resultat`, qui est un rapport généré,
   pas un formulaire). Chaque route :
   - reconstruit `WizardState` à partir du formulaire soumis
     (`_group_form` + `WizardState.from_form`), donc avec **tous** les champs
     de la page courante inclus, même non validés ;
   - rerend le template de l'étape ciblée avec ce `state`, en réutilisant
     exactement le même code de construction de contexte que la route
     d'avancement correspondante (factorisé en fonctions `_render_*`
     partagées, pour éviter la duplication entre "avancer" et "revenir").

4. **Pré-remplissage des templates à partir de `state`.** Les 4 templates qui
   n'affichent pas encore les valeurs de `state` (`profil_utilisateurs`,
   `donnees`, `usage`, `resultats`) sont mis à jour pour cocher/valoriser
   leurs champs depuis `state`, exactement comme le font déjà `outil` et
   `contexte_affaires`. C'est ce qui rend "conserver tout" réellement
   fonctionnel au clic (et, en bonus, corrige la fragilité actuelle du
   bouton « ← Retour » qui ne dépendait que du navigateur).

5. **Cas de l'usage courant vs usages sauvegardés.** Les étapes "Tes
   données" / "Ton usage" / "Usage des résultats" représentent l'usage *en
   cours de saisie* (`WizardState.current_usage_draft()`), pas un usage déjà
   validé dans `saved_usages`. Revenir sur une de ces icônes réaffiche donc
   toujours le brouillon d'usage courant — comportement déjà cohérent avec
   le reste du wizard (aucune logique nouvelle à ajouter ici).

## Détails d'implémentation

- `_steps.html.j2` : ajoute un mapping clé d'étape → slug d'URL (ex.
  `profil_utilisateurs` → `profil-utilisateurs`, `contexte_affaires` →
  `contexte-affaires`), utilisé pour construire `formaction`.
- `routes.py` : factorise, pour chaque étape, une fonction `_render_<étape>(request, state)`
  qui construit le contexte de template (déjà en partie fait pour `outil` via
  `_render_outil`). Les handlers `POST /wizard/<étape>` (avancement) et
  `POST /wizard/goto/<étape>` (retour) appellent la même fonction ; seule la
  transformation de `state` diffère (avancement peut dériver un nouvel état,
  ex. usage suivant vierge ; retour réutilise `state` tel quel).
- Étape `outil` : le retour doit toujours rerendre `wizard_outil.html.j2`
  (le formulaire principal), jamais l'écran intermédiaire
  `wizard_tool_type.html.j2`.
- `style.css` : les boutons `.st.done` doivent visuellement rester identiques
  aux `<div>` actuels (reset des styles par défaut de `<button>` : bordure,
  fond, alignement, curseur).

## Hors scope

- Pas de session serveur, pas de stockage persistant de l'état du wizard.
- Pas de navigation vers des étapes futures jamais atteintes.
- Pas de rendu "GET direct" d'une étape par URL (le mécanisme reste un POST
  déclenché depuis la page courante, cohérent avec le reste du wizard).
- Le rapport final (étape "Résultat") n'est pas navigable en arrière — y
  retourner nécessiterait de relancer `Interview.assess`, ce qui n'est pas
  demandé ici.

## Tests

- Un test par route `goto` (dans `tests/web/`, à côté des tests existants
  par étape) vérifiant que : (a) le state soumis est bien reflété dans les
  champs cachés et pré-remplis du template rendu, (b) le bon template est
  rendu pour l'étape demandée, (c) le cas `outil` retourne bien
  `wizard_outil.html.j2` et non l'écran de type d'outil.
- Un test vérifiant que `_steps.html.j2` ne rend un bouton cliquable que pour
  les étapes "done", et un `<div>` pour l'étape active et les étapes futures.
- Régression sur les templates modifiés (`profil_utilisateurs`, `donnees`,
  `usage`, `resultats`) : vérifier que les valeurs de `state` apparaissent
  bien cochées/valorisées dans le HTML rendu.
