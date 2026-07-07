# Vraies règles `grille.yaml` — Design

## Contexte

`grille.yaml` ne contient aujourd'hui que 3 règles de départ (R-07, R-12, R-20). Le
document source officiel, `SI_-_Grille_valuation_des_risques.docx`, n'est pas une
liste de règles « si X alors Y » : c'est un formulaire F/M/E/C que l'analyste SI
remplit à la main, sur ~15 critères répartis en Partie A (analyse du produit —
souveraineté, sécurité de l'information, conformité légale) et Partie B
(analyse par usage — gestion des données, éthique/fiabilité, risques
organisationnels).

Certains de ces critères n'ont aucun fait correspondant dans PolicyBot
aujourd'hui (biais algorithmiques, hallucinations, formation du personnel,
réputation — génériques à tout usage d'IA générative, pas conditionnés par des
données) ; d'autres correspondent à des faits déjà modélisés mais jamais
branchés dans le moteur de règles.

## Objectif

Étendre `grille.yaml` avec un jeu de règles réalistes et honnêtes : chaque
règle conditionnelle ne se déclenche que sur un fait que PolicyBot peut
réellement obtenir (formulaire d'entrevue ou extraction LLM depuis un texte de
conditions d'utilisation public). Les critères sans signal disponible sont
traités comme des rappels fixes plutôt que simulés par de fausses règles
conditionnelles.

## Périmètre explicitement exclu

Restent des cases à cocher manuelles pour l'agent SI, non automatisées par
PolicyBot : authentification SSO/MFA, journalisation/audit, plan de réponse
aux incidents, compatibilité de licence gouvernementale, acceptabilité
générale des conditions d'utilisation. Ces critères dépendent d'une vraie
revue de sécurité ou d'un contrat signé (DPA), pas d'une page de conditions
d'utilisation publique récupérée par `TermsFetcher`.

## Section A — Modèle de données et extraction

1. **Réactiver 3 champs `ContractFacts` dormants** (`data_retention`,
   `sub_processors`, `human_review`) : déjà extraits par le LLM et stockés,
   mais jamais utilisés en aval. Leur ajouter une ligne `RiskFactor` dans
   `build_arp()` (`policybot/contract/arp.py`), sur le même modèle que
   `trains_on_input`/`data_residency` aujourd'hui (catégorie, critère,
   inherent/residual F/M/E/C dérivé de la valeur, `origin="rule"`).

2. **Ajouter 2 nouveaux champs `ContractFacts`** :
   - `encryption_standard: Literal["strong", "partial", "none", "unknown"]`
   - `ip_ownership: Literal["customer", "vendor", "unclear", "unknown"]`

   Étendre le prompt système `_SYSTEM` de `arp.py` pour que le LLM les
   renseigne, et ajouter leur ligne `RiskFactor` correspondante dans
   `build_arp()`.

## Section B — Câblage dans le moteur (`engine.py`)

Le dict `facts` construit dans `evaluate_usage()` passe de 4 à 9 clés :

- `data_classification`, `automated_decisions` (déjà présents)
- `trains_on_input`, `data_residency` (déjà présents)
- `sub_processors`, `data_retention`, `human_review`, `encryption_standard`,
  `ip_ownership` (nouveaux, tous les champs `ContractFacts`)
- `rens_personnels`, `needs_officer_confirmation` (champs `Usage` déjà
  collectés, jamais exposés au moteur)

`classifier_confidence` (float) reste hors du dict de faits — c'est un
détail d'implémentation dont `needs_officer_confirmation` est déjà la
traduction booléenne exploitable par une règle.

**Correctif inclus** : `synthesize()` dédoublonne désormais
`GlobalResult.conditions` en préservant l'ordre d'apparition
(`list(dict.fromkeys(conditions))`), pour éviter des doublons si plusieurs
usages déclenchent la même règle (notamment les rappels fixes de la
section C, qui se déclenchent pour chaque usage).

## Section C — Nouvelles règles `grille.yaml`

### Règles conditionnelles (IDs à la suite de R-20)

| ID | `when` | `risk_level` | `recommendation` | `conditions` |
|---|---|---|---|---|
| R-21 | `sub_processors` ∈ {undisclosed, unknown} ET `data_classification` ∈ {Protégé A, B, C} | Modéré | Autoriser_avec_conditions | Demander la liste des sous-traitants avant de soumettre des données classifiées. |
| R-22 | `data_retention` ∈ {indefinite, unknown} ET `data_classification` ∈ {Protégé B, C} | Élevé | Autoriser_avec_conditions | Confirmer la politique de conservation/suppression des données auprès du fournisseur. |
| R-23 | `human_review` ∈ {no, unknown} ET `rens_personnels` = True | Élevé | Autoriser_avec_conditions | Aucune révision humaine confirmée chez le fournisseur pour des renseignements personnels — prévoir une validation manuelle interne. |
| R-24 | `rens_personnels` = True ET `data_residency` ∈ {us, other, unknown} | Élevé | Escalader | Renseignements personnels traités hors Québec — valider la conformité LAI/PRP avant autorisation. |
| R-25 | `needs_officer_confirmation` = True | Modéré | Autoriser_avec_conditions | Classification à faible confiance ou réponse libre « Autre » — confirmation de l'agent SI requise avant de considérer ce résultat final. |
| R-26 | `encryption_standard` ∈ {none, unknown} ET `data_classification` ∈ {Protégé A, B, C} | Modéré | Autoriser_avec_conditions | Confirmer le niveau de chiffrement des données en transit et au repos auprès du fournisseur. |
| R-27 | `ip_ownership` ∈ {vendor, unclear, unknown} | Modéré | Autoriser_avec_conditions | Le fournisseur pourrait revendiquer des droits sur le contenu généré — vérifier les clauses de propriété intellectuelle avant publication ou usage externe. |

### Rappels fixes (`when: {}` — toujours déclenchés, aucun `risk_level` ni `recommendation`)

Correspondent aux critères Partie B « Éthique et fiabilité des résultats » et
« Risques organisationnels » du docx source, qui ne varient pas selon les
faits collectés par PolicyBot :

- **R-28** — Hallucinations : rappel de valider l'exactitude des contenus
  générés avant toute utilisation externe ou décisionnelle.
- **R-29** — Biais algorithmiques : rappel de vigilance pour les usages à
  portée décisionnelle.
- **R-30** — Formation du personnel : rappel de s'assurer d'une formation
  adéquate à l'usage responsable de l'outil.
- **R-31** — Dépendance technologique/surconfiance : rappel que le jugement
  professionnel demeure requis.
- **R-32** — Image et réputation institutionnelle : rappel de valider tout
  contenu associé à l'UQAM avant diffusion publique.

Comme ces règles n'ont pas de `risk_level`/`recommendation`, elles n'affectent
ni `highest_risk()` ni le verdict — elles n'ajoutent que du texte informatif
à `conditions`, cohérent avec le moteur existant (`evaluate_usage` ignore déjà
les clés absentes de `then`).

Ces règles ne s'exécutent jamais pour un usage `INTERDIT` par la matrice
(le gate matriciel retourne avant l'évaluation des règles), ce qui est
cohérent : un usage refusé d'emblée n'a pas besoin de rappels de bonnes
pratiques.

## Section D — Tests et fichiers touchés

**Fichiers modifiés :**
- `policybot/models.py` — 2 nouveaux champs `ContractFacts`
- `policybot/contract/arp.py` — prompt étendu + `build_arp()` génère 7 lignes
  `RiskFactor` Partie A au lieu de 2 (5 nouvelles : sub_processors,
  data_retention, human_review, encryption_standard, ip_ownership)
- `policybot/grille/grille.yaml` — 12 nouvelles règles
- `policybot/grille/engine.py` — dict `facts` étendu à 9 clés ; dédoublonnage
  dans `synthesize()`

**Tests étendus (aucun nouveau fichier de test) :**
- `tests/grille/test_rules.py` — un cas de déclenchement + un cas de
  non-déclenchement par nouvelle règle conditionnelle, plus un test pour les
  rappels fixes (toujours présents, jamais de `risk_level`)
- `tests/grille/test_engine.py` — les 9 clés arrivent dans `facts` ;
  dédoublonnage vérifié dans `synthesize()`
- `tests/contract/test_arp.py` — extraction des 2 nouveaux champs + 7 lignes
  Partie A générées par `build_arp()`
- Test golden UQAM slide-5 (`INTERDIT`/`Refuser`) : ré-exécuté pour confirmer
  l'absence de régression (aucun changement de verdict attendu, les
  nouvelles règles ne s'exécutent que pour `PERMIS`/`OBLIGATOIRE`)

Aucun changement architectural : le travail suit le pattern TDD déjà en place
(un test par règle, `FakeLLMProvider` pour l'extraction, `grille.yaml` comme
donnée et non code).
