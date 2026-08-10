# PolicyBot — consignes de développement

PolicyBot rassemble des constats sourcés et propose un risque inhérent F/M/E
par critère. Il ne calcule aucune autorisation. Rien n’est affiché comme preuve
si la citation n’est pas ancrée dans le texte de sa propre page.

## Commandes

```powershell
.\.venv\Scripts\activate
pip install -e ".[dev,pdf]"
pytest -q
policybot devis-formulaire
policybot ingerer reponses.xlsx --dry-run
```

Ne jamais créer de worktree. Travailler dans le répertoire courant. Ne jamais
versionner `.env`, les réponses Exa brutes, les journaux ni les rapports.

## Architecture

```text
Microsoft Forms (externe)
  -> export .xlsx
  -> policybot.intake.reponses : une ligne = une DemandeIAG
  -> identification de l’offre
  -> classification des données par usage
  -> cache ARP SQLite (schéma 2)
  -> 17 recherches Exa parallèles, une par critère
  -> CriterionFinding[]
  -> rapport PDF / DOCX + constats .json
```

PolicyBot n’héberge aucun formulaire et n’expose aucune interface web. Le
catalogue `configs/formulaire.yaml` et le schéma `DemandeIAG` se valident
mutuellement à l’import, comme `criteres.py` valide la couverture des 17
critères : une question qui pointe vers un champ inexistant, un champ
obligatoire que le formulaire ne demande pas, ou une valeur de choix que le
schéma refuse font échouer le chargement.

Les 13 critères de partie A correspondent exactement à `ARP_CRITERIA`. Les
quatre critères de partie B recherchés correspondent à :

- Utilisation de données pour entraînement
- Compatibilité avec la LAI/PRP
- Biais algorithmiques
- Image et réputation institutionnelle

`policybot/contract/criteres.py` valide cette couverture à l’import. Toute
instruction envoyée à Exa, tout schéma structuré et tout paramètre de recherche
doit rester dans `configs/recherche_defaults.yaml` ou dans le YAML du critère.

`policybot/contract/exa.py` effectue les appels et isole les échecs.
`policybot/contract/citations.py` valide les offsets, recalcule les positions à
partir du verbatim lorsque nécessaire, rejette les citations non ancrées et
construit les liens `#:~:text=`.

`CriterionFinding` est la source de vérité d’une ligne :

- réponse;
- risque inhérent F/M/E proposé et justification;
- citations ancrées;
- type et coût Exa;
- résultat `ok`, `no_answer` ou `search_failed`.

`ArpRecord` contient les 17 constats et leur coût total. La version courante du
cache est `CURRENT_ARP_SCHEMA_VERSION = 2`; les anciennes entrées sont ignorées.

## Traçabilité

`policybot/tracing.py` écrit des événements JSONL masqués. Aucun prompt,
description d’usage, réponse ou extrait ne doit y apparaître en clair. Utiliser
`mask_text()` pour toute donnée libre. Les diagnostics locaux en clair sont
opt-in et désactivés par défaut.

## Tests

La suite est entièrement hors ligne. Les points essentiels sont :

- cohérence des 17 YAML;
- parsing de la sortie structurée et du coût Exa;
- isolation d’une recherche en échec;
- validation et liens profonds des citations;
- rendu PDF et DOCX;
- appariement des colonnes d’un export Forms et isolation d’une demande
  rejetée.
