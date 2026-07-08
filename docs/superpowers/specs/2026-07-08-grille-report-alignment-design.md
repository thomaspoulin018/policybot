# Alignement du rapport sur la Grille d'évaluation des risques — Design

**Date:** 2026-07-08
**Status:** Approuvé (design), en attente du plan d'implémentation
**Contexte:** le rapport HTML/PDF généré par PolicyBot (`policybot/report/`) ne
mirrore aujourd'hui qu'un résumé agrégé — pas la structure exacte du document
source officiel `documents_reference/SI_-_Grille_valuation_des_risques.docx`.
Ce design aligne le pipeline (ARP, moteur de règles, rendu) sur les sections,
catégories et critères exacts de ce document.

---

## 1. Constat

Le document de référence définit une structure fixe en 4 sections :

1. **Identification** — Numéro demande, Numéro grille d'évaluation, Outil
   évalué, Analyste SI, Date.
2. **Partie A — ARP (un tableau par outil)** — 13 critères nommés sur 3
   catégories : Souveraineté et hébergement des données (5), Sécurité de
   l'information (5), Conformité légale et contractuelle (3).
3. **Partie B — par usage (un tableau par usage)** — 11 critères nommés sur 3
   catégories : Gestion des données (4), Éthique et fiabilité des résultats
   (4), Risques organisationnels (3).
4. **Partie C — Synthèse** — Niveau de risque global, ÉFVP-R requise,
   Recommandation préliminaire, Conditions/restrictions proposées.

Écarts constatés avec l'implémentation actuelle :

- `build_arp()` (`policybot/contract/arp.py`) ne produit que 7 lignes, avec 2
  qui n'existent pas dans le document (Conservation des données, Révision
  humaine) et 6 manquantes.
- `Usage.partie_b` (`policybot/models.py`) existe dans le modèle mais n'est
  jamais rempli ni rendu — `evaluate_usage()` ne calcule qu'un risque agrégé
  unique par usage.
- `report.html.j2` n'affiche ni la Partie A, ni la section Identification, ni
  les conditions de la Partie C.

## 2. Décision antérieure à respecter

`docs/superpowers/specs/2026-07-07-grille-rules-design.md` exclut déjà,
délibérément, 5 critères de toute extraction LLM automatique :
authentification SSO/MFA, journalisation/traçabilité, gestion des incidents,
compatibilité licence gouvernementale, conditions d'utilisation acceptables.
Raison documentée : une page de conditions d'utilisation publique
(`TermsFetcher`) ne mentionne quasiment jamais ces éléments — un LLM forcé à
répondre produirait du bruit plutôt qu'un vrai signal. Ce design **maintient
cette exclusion** : ces 5 critères restent des lignes vides dans le rapport,
à documenter à la main par l'agent SI (cohérent avec le fait que le document
source est fondamentalement un formulaire).

## 3. Partie A — extension de `ContractFacts` et reconstruction de `build_arp`

### 3.1 Nouveaux champs `ContractFacts` (4, tous `Literal[..., "unknown"]`)

| Champ | Valeurs | Critère du document | Catégorie |
|---|---|---|---|
| `applicable_law` | `quebec_canada \| foreign \| unknown` | Juridiction applicable | Souveraineté |
| `foreign_vendor_dependency` | `yes \| no \| unknown` | Dépendance technologique | Souveraineté |
| `contract_prohibits_reuse` | `yes \| no \| unknown` | Garanties contractuelles de non-divulgation | Souveraineté |
| `reentraining_opt_out` | `yes \| no \| unknown` | Utilisation des entrées et des sorties | Sécurité de l'information |

Champs déjà existants réutilisés tels quels : `trains_on_input` (Données
soumises utilisées pour entraînement), `data_residency` (Localisation des
serveurs), `encryption_standard` (Chiffrement des données), `ip_ownership`
(Propriété intellectuelle).

Règle conservatrice inchangée sur les 4 nouveaux champs : `unknown` → risque
`E`, valeur positive confirmée → `F`.

Le prompt système `_SYSTEM` de `arp.py` est étendu pour ces 4 nouveaux champs
uniquement (pas les 5 exclus, §2).

### 3.2 Champ réaffecté

`Garanties contractuelles de non-divulgation` était dérivé de `sub_processors`
(disclosed/undisclosed) — un signal différent (sous-traitance) de celui que
demande le document (interdiction contractuelle de réutilisation). Il est
désormais dérivé de `contract_prohibits_reuse`. `sub_processors` reste dans
`ContractFacts`, utilisé uniquement par la règle R-21 (Partie B) — il perd sa
ligne Partie A dédiée.

### 3.3 Champs qui perdent leur ligne Partie A

`data_retention` et `human_review` restent dans `ContractFacts` (utilisés par
R-22/R-23 en Partie B) mais `build_arp()` ne génère plus de `RiskFactor` pour
« Conservation des données » ni « Révision humaine par le fournisseur » — ces
critères n'existent pas dans le document de référence.

### 3.4 `build_arp()` — sortie finale : exactement 13 `RiskFactor`

| # | Catégorie | Critère | Source |
|---|---|---|---|
| 1 | Souveraineté | Localisation des serveurs | `data_residency` |
| 2 | Souveraineté | Juridiction applicable | `applicable_law` *(nouveau)* |
| 3 | Souveraineté | Dépendance technologique | `foreign_vendor_dependency` *(nouveau)* |
| 4 | Souveraineté | Données soumises utilisées pour entraînement du modèle | `trains_on_input` |
| 5 | Souveraineté | Garanties contractuelles de non-divulgation | `contract_prohibits_reuse` *(nouveau, réaffecté)* |
| 6 | Sécurité de l'information | Mécanismes d'authentification | *aucun — ligne vide* |
| 7 | Sécurité de l'information | Chiffrement des données | `encryption_standard` |
| 8 | Sécurité de l'information | Journalisation et traçabilité | *aucun — ligne vide* |
| 9 | Sécurité de l'information | Utilisation des entrées et des sorties | `reentraining_opt_out` *(nouveau)* |
| 10 | Sécurité de l'information | Gestion des incidents | *aucun — ligne vide* |
| 11 | Conformité légale et contractuelle | Propriété intellectuelle | `ip_ownership` |
| 12 | Conformité légale et contractuelle | Conditions d'utilisation acceptables | *aucun — ligne vide* |
| 13 | Conformité légale et contractuelle | Compatibilité licence usage gouvernemental | *aucun — ligne vide* |

Les 5 lignes « vide » ne sont pas produites par `build_arp()` — elles sont
ajoutées au moment du rendu (§5), avec `origin` absent / une valeur neutre
indiquant « à documenter manuellement », pour rester cohérent avec l'invariant
« rien de dérivé n'est silencieusement inventé ».

## 4. Partie B — restructuration du moteur de règles

### 4.1 Schéma `grille.yaml`

Chaque règle reçoit deux nouvelles clés optionnelles dans `then` :
`category` et `criterion`, qui la rattachent à l'un des 11 critères fixes de
la Partie B. Les règles sans ces clés (R-12, R-21, R-22, R-26 — hébergement
hors Québec, sous-traitants non divulgués, conservation indéfinie,
chiffrement faible) continuent d'alimenter le risque agrégé/les conditions de
la Partie C mais n'apparaissent dans aucune ligne Partie B dédiée, faute de
critère correspondant dans le document.

### 4.2 Rattachement des règles existantes aux 11 critères

| Critère (document) | Catégorie | Règle(s) |
|---|---|---|
| Fuite de données confidentielles | Gestion des données | *base* : dérivée directement de `data_classification` (Non classifié/Protégé A → F, Protégé B → M, Protégé C → E), pas une règle `grille.yaml` |
| Mauvaise classification des données | Gestion des données | R-25 |
| Utilisation de données pour entraînement | Gestion des données | R-07 |
| Compatibilité avec la LAI/PRP | Gestion des données | R-24 |
| Hallucinations et erreurs factuelles | Éthique et fiabilité | R-28 |
| Biais algorithmiques | Éthique et fiabilité | R-29 |
| Supervision humaine insuffisante | Éthique et fiabilité | R-20, R-23 |
| Propriété intellectuelle du contenu généré | Éthique et fiabilité | R-27 |
| Formation insuffisante du personnel | Risques organisationnels | R-30 |
| Dépendance technologique | Risques organisationnels | R-31 |
| Image et réputation institutionnelle | Risques organisationnels | R-32 |

### 4.3 `evaluate_usage()` — nouvelle sortie

Pour chaque usage (sauf `INTERDIT`, où le gate matriciel retourne avant toute
règle, comme aujourd'hui) :

1. Construit les 11 `RiskFactor` fixes de `partie_b` : pour chaque critère,
   `inherent`/`residual` = pire résultat parmi les règles qui lui sont
   rattachées et qui matchent (F par défaut si aucune ne matche), sauf
   « Fuite de données confidentielles » dont la valeur de base vient
   directement de `data_classification` (§4.2).
2. Garde le calcul actuel de `risk_level`/`verdict`/`conditions` agrégés
   (Partie C) à partir de **toutes** les règles déclenchées — les 11
   rattachées et R-12/21/22/26 — sans changement de comportement pour la
   synthèse globale.
3. Stocke les 11 `RiskFactor` dans `out.partie_b`.

## 5. Rendu (`report.html.j2`)

Réécriture du template pour mirrorer les 4 sections du document, dans
l'ordre :

1. **Identification** — `request.numero` (Numéro demande), liste
   `state.tools` (Outil évalué), `request.date` (Date). `Numéro grille
   d'évaluation` et `Analyste SI` : champs vides (propres au processus humain,
   non collectés par l'entrevue).
2. **Partie A** — un tableau par outil (`state.tools`), 13 lignes groupées par
   catégorie, colonnes Critère / Description / Risque inhérent / Mitigation /
   Risque résiduel / Responsable / Observations. La lettre F/M/E/C retenue est
   mise en évidence (rendu HTML/PDF, pas des cases interactives). Les 5
   critères sans source (§3.4) sont ajoutées par le template lui-même, vides.
3. **Partie B** — une section par usage, tableau des 11 `RiskFactor` de
   `usage.partie_b`, même style de rendu, groupé par les 3 catégories.
4. **Partie C** — Niveau de risque global, ÉFVP-R requise, Recommandation, et
   **Conditions et restrictions proposées** (`state.result_global.conditions`
   — actuellement absent du rendu, correction incluse).

Le bandeau « recommandation, pas autorisation » reste sur chaque section.

## 6. Tests et fichiers touchés

**Fichiers modifiés :**
- `policybot/models.py` — 4 nouveaux champs `ContractFacts`
- `policybot/contract/arp.py` — prompt étendu (4 champs) ; `build_arp()`
  génère 13 `RiskFactor` (8 dérivés, 5 absents/laissés au rendu) au lieu de 7
- `policybot/grille/grille.yaml` — `category`/`criterion` ajoutés aux règles
  rattachables (R-07, R-20, R-23, R-24, R-25, R-27 à R-32)
- `policybot/grille/engine.py` — `evaluate_usage()` construit et peuple
  `out.partie_b` (11 `RiskFactor`)
- `policybot/report/templates/report.html.j2` — réécriture complète :
  Identification, Partie A, Partie B par critère, Partie C avec conditions

**Tests étendus/ajoutés :**
- `tests/contract/test_arp.py` — 13 lignes exactes (libellés/catégories
  conformes au document), 4 nouveaux champs extraits, `unknown` → `E`
- `tests/grille/test_engine.py` — `partie_b` contient exactement les 11
  `RiskFactor` attendus (bons libellés/catégories), rattachement correct par
  critère, agrégat Partie C inchangé (inclut toujours R-12/21/22/26)
- Tests de rendu (nouveau fichier `tests/report/test_renderer.py` si absent,
  sinon étendu) — présence des 13 lignes Partie A, 11 lignes Partie B par
  usage, ligne Conditions en Partie C, section Identification
- `tests/test_golden_scenarios.py` — scénario ChatGPT/Perplexity ré-exécuté
  pour confirmer l'absence de régression sur le verdict (`INTERDIT`/`Refuser`)
  et vérifier la nouvelle structure de rendu bout-en-bout

Aucun changement architectural : le travail suit le pattern existant (règles
comme données, `FakeLLMProvider` pour les tests, TDD critère par critère).
