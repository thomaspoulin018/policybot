# Cycle de vie d'une recherche de critère

Un critère sur dix-sept, du YAML fusionné jusqu'au `CriterionFinding`. C'est ici que s'applique la règle « rien n'est affiché comme preuve si la citation n'est pas ancrée dans le texte de sa propre page ».

Code de référence : `policybot/contract/exa.py` et `policybot/contract/citations.py`.

```mermaid
flowchart TD
  Y[("configs/recherche_criteres/A01-....yaml<br/>query · type · num_results · include_domains")]
  D[("configs/recherche_defaults.yaml<br/>prompts · schemas · budget · max_citations")]
  Y --> MERGE["_deep_merge : défauts partagés puis surcharges du critère"]
  D --> MERGE
  MERGE --> RENDER["render_query() : substitution de l'identité d'offre<br/>tool · vendor · plan · deployment_mode · contract_type · jurisdiction"]
  RENDER --> QUERY["requête finale = query rendue + global_instruction"]

  QUERY --> CALL["client.search(query, output_schema, contents, num_results, type)"]
  CALL --> FAIL{"exception ?"}
  FAIL -->|"oui"| KO["record_exa_search_failed()<br/>CriterionFinding outcome = search_failed"]
  FAIL -->|"non"| OUT["_response_output()<br/>answer · inherent_risk · justification"]

  CALL --> COST["_response_cost()<br/>costDollars.total si présent, sinon 0"]
  OUT --> RISK{"inherent_risk dans F, M, E ?"}
  RISK -->|"non"| NULLR["risque laissé à None"]
  RISK -->|"oui"| KEEPR["risque retenu"]

  CALL --> RES["results triés par source_sort_key<br/>type de source, puis score Exa, puis URL"]
  RES --> LOOP["pour chaque résultat : summary.citation"]
  LOOP --> VAL["validated_citation(url, page_text, quote, begin, end)"]
  VAL --> OFFS{"offsets fournis et cohérents ?"}
  OFFS -->|"oui"| USEO["extrait pris tel quel"]
  OFFS -->|"non"| RECOMP["recalcul par recherche du verbatim<br/>exacte, puis tolérante aux espaces"]
  RECOMP --> ANCH{"verbatim présent dans le texte de la page ?"}
  ANCH -->|"non"| DROP["citation rejetée<br/>rejected_citations incrémenté"]
  ANCH -->|"oui"| USEO
  USEO --> LINK["build_deep_link : fragment de texte ciblé<br/>12 mots ou moins entiers, sinon 5 premiers et 5 derniers"]
  LINK --> DEDUP{"URL déjà retenue ?"}
  DEDUP -->|"oui"| SKIP["ignorée"]
  DEDUP -->|"non"| ACC["citation acceptée"]
  ACC --> CAP{"plafond max_citations_per_criterion atteint ?"}
  CAP -->|"oui"| ENDL["arrêt de la boucle"]
  CAP -->|"non"| LOOP

  KEEPR --> FINDING
  NULLR --> FINDING
  COST --> FINDING
  ACC --> FINDING
  FINDING["CriterionFinding<br/>outcome = ok si answer non vide, sinon no_answer"]

  classDef err fill:#fef2f2,stroke:#ef4444,color:#991b1b;
  classDef conf fill:#f1f5f9,stroke:#94a3b8,color:#334155;
  class KO,DROP err;
  class Y,D conf;
```
