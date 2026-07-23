# Référence des règles de la Partie B

Ce document décrit les champs utilisables dans `grille.yaml`, leurs valeurs
exactes et les critères auxquels une règle peut être rattachée.

## Fonctionnement de `when`

Chaque clé de `when` doit correspondre au fait évalué par le moteur. Les clés
sont combinées avec **ET** et les valeurs d'une même liste avec **OU**.

```yaml
when:
  rens_personnels: ["True"]
  data_residency: ["us", "eu", "unknown"]
```

Cette condition signifie : renseignements personnels **ET** résidence des
données égale à `us`, `eu` **OU** `unknown`.

Les comparaisons sont exactes et sensibles à la casse et aux accents. Le moteur
convertit chaque fait en texte avant la comparaison. Les booléens doivent donc
être écrits `"True"` et `"False"`, avec une majuscule. Un `when: {}` se
déclenche toujours.

## Champs disponibles dans `when`

Seuls les champs de ce tableau sont actuellement transmis à `grille.yaml`.

| Champ | Valeurs possibles | Provenance et signification |
|---|---|---|
| `data_classification` | `"Non classifié"`, `"Protégé A"`, `"Protégé B"`, `"Protégé C"` | Classification déterministe des données décrites pour l'usage. |
| `automated_decisions` | `"True"`, `"False"` | Indique si l'outil prend ou déclenche une décision automatiquement. |
| `training_default` | `"yes"`, `"no"`, `"unknown"` | Le fournisseur utilise-t-il les données soumises pour entraîner son modèle par défaut? |
| `opt_out_available` | `"yes"`, `"no"`, `"unknown"` | Une option de retrait de l'entraînement est-elle offerte? |
| `opt_out_confirmed_enabled` | `"yes"`, `"no"`, `"unknown"` | Le retrait est-il confirmé comme activé pour l'offre évaluée? |
| `data_residency` | `"quebec"`, `"canada_outside_quebec"`, `"us"`, `"eu"`, `"multi_region"`, `"configurable"`, `"unknown"` | Lieu d'hébergement ou de traitement des données. |
| `sub_processors` | `"disclosed"`, `"undisclosed"`, `"unknown"` | Les sous-traitants sont-ils divulgués? |
| `data_retention` | `"none"`, `"limited"`, `"indefinite"`, `"unknown"` | Durée ou politique de conservation des données. |
| `encryption_standard` | `"strong"`, `"partial"`, `"none"`, `"unknown"` | Niveau de chiffrement contractuellement documenté. |
| `ip_ownership` | `"customer"`, `"vendor"`, `"unclear"`, `"unknown"` | Titularité des droits sur les contenus générés. |
| `rens_personnels` | `"True"`, `"False"` | Présence de renseignements personnels dans l'usage. |
| `needs_officer_confirmation` | `"True"`, `"False"` | Classification incertaine ou réponse libre qui exige une confirmation humaine. |
| `result_used_for_decision` | `"True"`, `"False"` | Vrai lorsque « Prise de décision » est sélectionné comme utilisation des résultats. |
| `result_published` | `"True"`, `"False"` | Vrai lorsque « Publication » est sélectionné comme utilisation des résultats. |
| `api_integration` | `"True"`, `"False"` | Vrai lorsque le mode d'utilisation comprend une intégration par API. |
| `formation_iag_recue` | `"aucune"`, `"partielle"`, `"complète"`, `"unknown"` | Niveau de formation déclaré; `unknown` signifie qu'aucune réponse n'est disponible. |

`unknown` représente une information non démontrée. Il ne signifie pas `no`.
Une règle conservatrice peut inclure `unknown`, mais seulement lorsqu'une
absence de preuve constitue réellement un risque à confirmer.

## Catégories et critères disponibles dans `then`

Les libellés doivent être copiés exactement, avec leurs accents.

### Gestion des données

| Critère | Particularité |
|---|---|
| `Fuite de données confidentielles` | La cote de la ligne est calculée directement depuis `data_classification` : Non classifié et Protégé A → F, Protégé B → M, Protégé C → E. Une règle YAML peut affecter le risque global, mais ne remplace pas cette cote de ligne. |
| `Mauvaise classification des données` | Peut notamment utiliser `needs_officer_confirmation`. |
| `Utilisation de données pour entraînement` | Peut utiliser `training_default`, `opt_out_available` et `opt_out_confirmed_enabled`. |
| `Compatibilité avec la LAI/PRP` | Peut utiliser `rens_personnels` et `data_residency`. |

### Éthique et fiabilité des résultats

| Critère | Signaux pertinents disponibles |
|---|---|
| `Hallucinations et erreurs factuelles` | `result_used_for_decision`, `result_published` |
| `Biais algorithmiques` | `result_used_for_decision`, `automated_decisions` |
| `Supervision humaine insuffisante` | `automated_decisions`, `result_used_for_decision` |
| `Propriété intellectuelle du contenu généré` | `ip_ownership`, `result_published` |

### Risques organisationnels

| Critère | Signaux pertinents disponibles |
|---|---|
| `Formation insuffisante du personnel` | `formation_iag_recue` |
| `Dépendance technologique` | `api_integration` |
| `Image et réputation institutionnelle` | `result_published` |

## Champs disponibles dans `then`

| Champ | Valeurs possibles | Effet |
|---|---|---|
| `category` | Une des trois catégories ci-dessus | Rattache la règle à une section de la Partie B. Doit accompagner `criterion`. |
| `criterion` | Un des onze critères ci-dessus | Rattache la règle à une ligne de la Partie B. |
| `risk_level` | `"Faible"`, `"Modéré"`, `"Élevé"`, `"Critique"` | Propose une cote inhérente et participe au risque global. La cote la plus sévère gagne. |
| `recommendation` | `"Autoriser"`, `"Autoriser_avec_conditions"`, `"Escalader"`, `"Refuser"` | Participe à la recommandation; la plus restrictive gagne. La recommandation ne constitue jamais une autorisation. |
| `conditions` | Liste de textes | Ajoute des conditions et des observations au rapport. |

`category`, `criterion`, `risk_level`, `recommendation` et `conditions` sont
techniquement optionnels. Une règle sans `category`/`criterion` peut contribuer
au résultat global de la Partie C sans remplir une ligne de la Partie B. Une
règle sans `risk_level` ni `recommendation` sert de rappel et n'influence pas le
verdict global.

## Exemple complet

```yaml
- id: R-EXEMPLE
  when:
    result_published: ["True"]
    data_classification: ["Protégé A", "Protégé B"]
  then:
    category: "Éthique et fiabilité des résultats"
    criterion: "Propriété intellectuelle du contenu généré"
    risk_level: "Modéré"
    recommendation: "Autoriser_avec_conditions"
    conditions:
      - "Vérifier les droits et les licences avant toute publication."
```

Cette règle se déclenche seulement si une publication est prévue **ET** si les
données sont classifiées Protégé A **OU** Protégé B.

## Limites du format actuel

Le moteur prend en charge uniquement des correspondances exactes. Il ne permet
pas directement les comparaisons numériques, les négations, les expressions
régulières, les recherches dans du texte libre ou un `OU` entre deux champs
différents. Un nouveau fait déterministe doit être ajouté dans `engine.py` pour
représenter ce genre de condition avant de pouvoir l'utiliser dans le YAML.

Enfin, la matrice MCN est évaluée avant `grille.yaml`. Une combinaison
`INTERDIT` retourne immédiatement `Refuser`; aucune règle YAML ne peut modifier
ce résultat.
