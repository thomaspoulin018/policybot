# PolicyBot — Capturer les données de la Fiche de qualification des usages

**Date:** 2026-07-08
**Status:** Approved (design), pending implementation plan
**Context:** L'UQAM utilise un formulaire papier/Word en 8 sections, la « Fiche de
qualification des usages », qui est l'étape 1 du guide MCN (avant la Grille
d'évaluation des risques que PolicyBot génère déjà). L'objectif à terme est que
PolicyBot puisse produire ce document lui-même, sans rencontre humaine préalable.
Ce spec couvre le premier sous-projet nécessaire : étendre le modèle de données et
le wizard pour capturer tous les champs de la Fiche que le demandeur peut renseigner
lui-même. Deux sous-projets suivants, hors scope ici, généreront le document
(nouveau template de rapport) et automatiseront la section 8 (observations
préliminaires Direction SI).

## 1. Purpose

Faire en sorte que le wizard existant (`outil → donnees → usage → resultats →
resultat`) capture, en plus de ce qu'il capture déjà, tous les champs des sections
1 à 7 de la Fiche de qualification qui sont du ressort du demandeur. Rien dans ce
spec ne change le moteur de décision (matrix/grille) ni son verdict : les nouveaux
champs sont purement descriptifs et alimentent uniquement le futur document, jamais
`Interview.assess`.

**Hors scope :**
- Rendu du document Fiche de qualification (sous-projet suivant).
- Section 8 (observations Direction SI / recommandation préliminaire) — jugement
  humain ou automatisation future, à spécifier séparément.
- Champs administratifs de la section 1 non connus du demandeur : « Responsable SI
  assigné », « Date de la rencontre de qualification », « Participants à la
  rencontre ». Restent vides dans le document, à remplir manuellement plus tard.
- Assistance LLM sur les nouveaux champs (pas de `suggest_options`/`guess_*`) —
  ce sont des formulaires simples (texte libre, cases à cocher, nombre).

## 2. Modèle de données

### 2.1 Nouveau modèle `QualificationProfile`

Ajouté à `policybot/models.py`, une seule instance par `InterviewState` (pas par
outil, pas par usage) — indépendant du moteur de risque, jamais lu par
`grille/matrix.py` ni `grille/rules.py` :

```python
class QualificationProfile(BaseModel):
    # Section 4 — Profil des utilisateurs
    nb_utilisateurs_vises: Optional[int] = None
    fonctions_roles: str = ""
    niveau_maitrise_ti: Optional[Literal["débutant", "intermédiaire", "avancé"]] = None
    formation_iag_recue: Optional[Literal["aucune", "partielle", "complète"]] = None
    acces_protege_a_ou_plus: Optional[Literal["oui", "non", "à vérifier"]] = None

    # Section 6 — Valeur attendue et bénéfices
    besoin_affaires: str = ""
    gains_qualitatifs: str = ""
    gains_quantitatifs: str = ""
    alternatives_considerees: str = ""
    urgence_percue: Optional[Literal["faible", "modérée", "élevée"]] = None

    # Section 7 — Informations contractuelles et financières
    cout_annuel_par_utilisateur: Optional[str] = None
    cout_total_annuel: Optional[str] = None
    mode_acquisition: Optional[Literal[
        "achat_direct", "seao", "appel_offres", "contrat_existant"
    ]] = None
    duree_contrat: str = ""
    responsable_budgetaire: str = ""
```

`InterviewState` gagne un champ `qualification: QualificationProfile =
Field(default_factory=QualificationProfile)`.

Note sur la section 7 : le formulaire présente coût/contrat comme un bloc unique
par demande, pas par outil. Si une demande vise deux outils avec des coûts
distincts, ce spec ne les distingue pas (champ texte libre unique) — décision
assumée pour rester simple ; à revisiter si l'usage réel le justifie.

### 2.2 Extensions directes des modèles existants

Ces modèles mélangent déjà champs descriptifs et champs de décision (`ToolRef.vendor`
est descriptif à côté de `iag_type` qui est décisionnel ; `Usage.description` est
descriptif à côté de `data_classification`) — les nouveaux champs suivent le même
pattern plutôt que d'aller dans `QualificationProfile` :

- `ToolRef` (section 2) : + `version_plan_tarifaire: str = ""`
- `Usage` (section 3) : + `frequence_utilisation: str = ""`, `nb_utilisateurs:
  Optional[int] = None`, `systemes_api_cibles: str = ""` (pertinent seulement si
  `"api" in mode`)

## 3. Flux du wizard

Flux actuel (post `2026-07-08-wizard-split-usage-step-design.md`) :

```
outil → donnees → usage → resultats → resultat
```

Nouveau flux :

```
outil (+ version) → profil_utilisateurs (nouveau) → donnees → usage (+ fréquence/nb/API) → resultats → contexte_affaires (nouveau) → resultat
```

- **`profil_utilisateurs`** inséré juste après `outil` : à ce stade on connaît déjà
  l'outil, et le profil des utilisateurs est indépendant des données/usages qui
  suivent — poser la question tôt évite de la faire dépendre d'un contexte pas
  encore établi.
- **`contexte_affaires`** inséré juste avant `resultat` (après `resultats`) :
  regroupe sections 6 et 7, qui sont les questions les moins liées à l'usage
  technique et les plus proches d'une synthèse de fin de parcours (« pourquoi ce
  projet, combien ça coûte ») — cohérent avec le fait que `resultat` produit déjà
  le rapport final juste après.

### 3.1 Nouvelles routes / templates

- `POST /wizard/outil` (existant) : le form gagne un champ optionnel
  `version_plan_tarifaire`, porté par `WizardState`, transmis dans les hidden
  fields de l'écran suivant sans changer la branche de décision existante
  (known tool vs unknown tool type).
- Nouvel écran **`wizard_profil_utilisateurs.html.j2`**, servi par une nouvelle
  route `POST /wizard/profil-utilisateurs`. Les **deux** routes qui mènent
  aujourd'hui à `wizard_donnees.html.j2` — `wizard_outil` (outil connu) et
  `wizard_outil_type` (outil inconnu, après sélection du type) — rendent
  désormais `wizard_profil_utilisateurs.html.j2` à la place ; c'est la nouvelle
  route `POST /wizard/profil-utilisateurs` qui rend `wizard_donnees.html.j2` en
  aval, une fois le profil soumis. Contenu de l'écran : les 5 champs de la
  section 4 (nombre, texte libre rôles, 3 select simples).
- `donnees`, `usage`, `resultats` : inchangés dans leur logique, sauf `usage` qui
  gagne les 3 champs de section 3 sur son propre écran (mode/description déjà
  présents sur l'écran A du step `usage`).
- Nouvel écran **`wizard_contexte_affaires.html.j2`**, servi par une nouvelle route
  `POST /wizard/contexte-affaires` (appelée après soumission de l'écran
  `resultats`, à la place du render direct de `resultat.html.j2` — celui-ci est
  maintenant rendu par la soumission de ce nouvel écran). Contenu : les 9 champs
  des sections 6+7. C'est ce nouvel écran qui appelle finalement `Interview.assess`
  (reprend le corps actuel de `wizard_resultats_submit`), puisque c'est la dernière
  étape avant le rapport.
- `WizardState` gagne tous les nouveaux champs (mêmes noms que
  `QualificationProfile`/extensions), avec `to_hidden_fields`/`from_form` étendus
  en conséquence — aucune session serveur, pattern inchangé.
- `Interview.assess` gagne un paramètre pour recevoir
  `qualification: QualificationProfile | None`, `tool_version_plan_tarifaire:
  str | None`, et par usage `frequence_utilisation`/`nb_utilisateurs`/
  `systemes_api_cibles` dans `usage_input`, et les assigne tel quel sur
  `InterviewState`/`ToolRef`/`Usage` sans passer par le moteur de risque.

## 4. Testing

- `tests/web/test_routes_profil_utilisateurs.py` (nouveau) : soumission de l'écran,
  vérifie que les hidden fields du profil traversent vers l'écran `donnees`.
- `tests/web/test_routes_contexte_affaires.py` (nouveau) : soumission de l'écran,
  vérifie l'appel à `Interview.assess` avec les données accumulées, et que
  `InterviewState.qualification` est bien peuplé dans le résultat.
- `tests/web/test_routes_outil.py` étendu pour `version_plan_tarifaire`.
- `tests/web/test_routes_usage.py` étendu pour les 3 nouveaux champs de section 3.
- Le test bout-en-bout du scénario doré (`tests/test_golden_scenarios.py` /
  README) est mis à jour pour poster sur les deux nouvelles routes dans l'ordre.
- Un test unitaire sur `models.py` vérifie que `QualificationProfile` a des
  valeurs par défaut permettant de construire un `InterviewState` complet sans
  aucun des nouveaux champs (rétrocompatibilité des scénarios de test existants
  qui n'en fournissent aucun).

## 5. Deferred

- Rendu de ces champs dans un document (sous-projet « nouveau template Fiche de
  qualification »).
- Automatisation de la section 8 (sous-projet séparé, touche à l'invariant
  « PolicyBot recommande, n'autorise jamais »).
- Champs administratifs section 1 (responsable SI assigné, date/participants de
  rencontre) — restent hors wizard.
- Distinction du coût par outil si une demande en vise plusieurs (actuellement un
  champ texte libre unique par demande).
- Décider si `contexte_affaires` doit rester en toute fin de parcours ou être
  déplacé plus tôt, une fois l'usage réel du wizard observé.
