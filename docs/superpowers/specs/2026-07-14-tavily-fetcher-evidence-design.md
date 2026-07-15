# Fetcher Tavily : preuve par champ, dégradation gracieuse, coût maîtrisé

Date : 2026-07-14
Statut : design approuvé, prêt pour le plan d'implémentation

## Problème

`policybot/contract/tavily.py` collecte les faits contractuels d'un outil (Partie A /
ARP) via Tavily Search + Extract. Trois défauts dans l'implémentation actuelle :

1. **Traçabilité champ → source perdue.** Le module lance 16 recherches ciblées, une
   par fait contractuel, et tague chaque résultat avec `result["field"]`
   (tavily.py:299) — puis jette ce tag : toutes les pages sont concaténées en un seul
   blob, et `extract_contract_facts` demande au LLM de remplir les 16 champs d'un coup
   à partir de ce mélange. `ContractFacts` ne porte qu'un `source_url` unique pour
   l'ensemble. L'officier qui lit le rapport ne peut pas vérifier d'où sort
   `trains_on_input=yes`.
2. **Aucune gestion d'erreur.** Une exception réseau, un 401 (clé invalide) ou un 429
   (quota épuisé) remonte et fait planter `Interview.assess`. Le repli vers
   `fetch_terms` direct (orchestrator.py:70) n'est emprunté que si Tavily renvoie
   `None`, ce qui n'arrive qu'en l'absence de clé API.
3. **Coût.** 16 recherches `search_depth: advanced` + 1 Extract `advanced` par cache
   miss. Le cache ARP amortit, mais le premier passage sur un outil inconnu est lourd
   et lent.

Un quatrième défaut découle du premier : `_select_evidence_text` (arp.py:177) découpe
le blob à 12 000 caractères avec 14 regex de mots-clés. Ce bricolage n'existe que
parce qu'on écrase 20 pages en un seul prompt.

## Exigences

- **La preuve est une exigence d'auditabilité, pas du confort de debug.** Chaque fait
  contractuel doit pouvoir citer l'URL *et* un extrait verbatim vérifiable, rendus dans
  le rapport que l'officier révise.
- **Budget : coût stable, qualité en hausse.** On accepte la facture actuelle, mais
  dépensée sur des prompts ciblés plutôt qu'un blob. Pas d'explosion du coût
  (l'extraction champ par champ — 16 recherches + 16 appels LLM — est écartée pour
  cette raison).
- **Aucune régression de l'invariant du projet :** le LLM ne décide jamais d'un
  verdict. Il extrait des faits sourcés ; la grille et la matrice décident.

## Approche retenue : extraction par familles de critères

Les 16 champs sont regroupés en 5 familles qui partagent naturellement leurs sources
documentaires. Une recherche Tavily par famille, une extraction LLM par famille.

| Famille | Champs |
|---|---|
| `entrainement_reutilisation` | `trains_on_input`, `reentraining_opt_out`, `contract_prohibits_reuse`, `human_review` |
| `hebergement_retention` | `data_retention`, `data_residency`, `sub_processors`, `foreign_vendor_dependency` |
| `securite_technique` | `encryption_standard`, `authentication_support`, `audit_logging`, `incident_response` |
| `legal_pi` | `ip_ownership`, `applicable_law` |
| `termes_institutionnels` | `institutional_terms`, `quebec_higher_ed_license` |

Les 16 champs de `ContractFacts` sont couverts exactement une fois.

Alternatives écartées : (A) correctif chirurgical — remonter les URLs par champ sans
citation ; ne satisfait pas l'exigence d'auditabilité, le LLM lit toujours un blob.
(C) un appel par champ — traçabilité parfaite mais 16 recherches + 16 appels LLM, hors
budget, et la moitié des champs retombent de toute façon sur les mêmes pages (les CGU
couvrent PI *et* droit applicable).

## Modèle de données

```python
class FactEvidence(BaseModel):
    value: str            # valeur normalisée, ex. "opt_out_available"
    source_url: str | None
    quote: str | None     # extrait verbatim, 300 caractères max
    confidence: float     # 0..1
```

`ContractFacts` **garde ses 16 champs scalaires inchangés** — `build_arp`,
`grille.yaml`, `rules.py` et les tests existants continuent de lire
`facts.trains_on_input` sans modification — et gagne :

```python
evidence: dict[str, FactEvidence] = {}   # indexé par nom de champ
```

`build_arp` enrichit les `observations` de chaque `RiskFactor` Partie A avec l'URL et
la citation du champ correspondant, en plus de la valeur déjà présente. Le rapport
rend ces observations telles quelles — rien n'est inventé au rendu, conformément à
l'invariant du projet.

**Règle de non-affirmation sans source :** si le LLM ne peut pas produire de citation
verbatim pour un champ, il renvoie `unknown`. Une valeur sans preuve n'entre pas dans
`ContractFacts`.

## Flux de collecte

1. **Cinq recherches**, une par famille, avec sa requête (`{tool} {vendor} …`).
2. **Indexation inverse URL → familles** : chaque URL retenue mémorise la ou les
   familles qui l'ont trouvée.
3. **Budget d'extraction réparti à parts égales** — 4 URLs par famille, plafond Tavily
   de 20 respecté. Répartition en round-robin plutôt que « les 20 premières arrivées »,
   ce qui corrige la famine actuelle des dernières familles (aujourd'hui les premiers
   champs de `FACT_FIELDS` monopolisent le budget).
4. **Un seul appel Extract** sur les URLs dédupliquées. Une URL trouvée par deux
   familles n'est extraite qu'une fois mais nourrit les deux prompts — c'est ce qui
   garde la facture stable.
5. **Cinq extractions LLM** : chaque prompt ne voit que les pages de sa famille et ne
   doit remplir que ses 2 à 4 champs, chacun avec valeur + URL + citation.
6. **Fusion** des cinq résultats en un `ContractFacts` unique (valeurs + `evidence`).

`_select_evidence_text` n'est pas supprimé mais **redistribué** : ses 14 regex de
mots-clés deviennent la propriété des familles (chaque famille porte les siennes), et le
découpage ne s'applique qu'à une famille dont l'évidence dépasse le budget. Avec Tavily
c'est rare (l'évidence d'une famille est déjà ciblée) ; sur le chemin de repli
`fetch_terms`, qui rend une page de CGU entière, le découpage reste indispensable — et
devient meilleur, puisqu'il ne conserve que les extraits pertinents *pour la famille en
cours d'extraction* au lieu d'un mélange des 16 sujets.

## Gestion d'erreur : dégradation par famille

Chaque appel Tavily passe par un wrapper qui attrape l'exception, la consigne via
`trace_step` et poursuit. Conséquences graduées :

- **Recherche d'une famille en échec** → les champs de cette famille restent `unknown`,
  avec une observation explicite (« collecte Tavily échouée »). Les quatre autres
  familles aboutissent normalement. Un résultat partiel honnête vaut mieux qu'un
  plantage.
- **Extract en échec** → repli sur le `raw_content` déjà présent dans les résultats de
  recherche (`_fallback_search_chunks`, tavily.py:271, existe déjà).
- **Toutes les familles en échec, ou zéro évidence** → `None` ; l'orchestrateur retombe
  sur `fetch_terms` direct (orchestrator.py:70), chemin déjà câblé mais aujourd'hui
  jamais emprunté en cas d'exception.
- **Erreur d'authentification (401) ou de quota (429)** → distinguée dans la trace :
  « ta clé est épuisée » et « cette page ne répond pas » n'appellent pas la même
  réaction.

**Aucune exception Tavily ne remonte dans `Interview.assess`.**

## Coût

| | Avant | Après |
|---|---|---|
| Recherches `advanced` | 16 | 5 |
| Appels Extract | 1 (≤ 20 URLs) | 1 (≤ 20 URLs) |
| Appels LLM d'extraction | 1 (blob de 12 000 car.) | 5 (≈ 1/4 du contexte chacun) |

Facture du même ordre de grandeur, dépensée sur des prompts ciblés. Le cache ARP
(`PreApprovedStore`) continue d'amortir : un outil déjà vu ne coûte rien.

## Configuration

Le YAML par outil (`configs/tavily_contracts/<slug>.yaml`) passe d'une liste `fields` à
une liste `families`, chacune portant sa requête, ses champs et ses surcharges de
recherche. Un `schema_version` est ajouté : les configs à l'ancien schéma (absent ou
périmé) sont régénérées automatiquement.

Le confinement de `include_domains` au seul domaine du `terms_url` est **conservé tel
quel** — c'est un choix de qualité de source, hors périmètre de ce design.

## Tests

Le module est déjà testable par injection (`search_func` / `extract_func` passés à
`collect_terms_from_tavily`, `FakeLLMProvider` avec réponses en file). On étend le même
pattern, sans I/O réelle :

- Répartition équitable du budget d'extraction entre familles (round-robin).
- Déduplication d'une URL trouvée par deux familles : un seul Extract, deux prompts
  nourris.
- Recherche d'une famille en échec : ses champs sont `unknown`, les autres familles
  aboutissent, aucune exception ne remonte.
- Échec total → `None` → l'orchestrateur emprunte le repli `fetch_terms`.
- `ContractFacts.evidence` peuplé avec URL et citation ; champ sans citation → `unknown`.
- `build_arp` reporte URL et citation dans les `observations` des `RiskFactor` Partie A.
- Régression : les tests existants de `grille` / `rules` continuent de passer sans
  modification (les 16 champs scalaires sont inchangés).
