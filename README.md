# PolicyBot

PolicyBot prépare un dossier de constats sourcés pour l’évaluation d’un outil
d’IA générative dans une université québécoise. Il ne calcule aucune
autorisation : l’officier désigné évalue la permissibilité et prend la décision.

PolicyBot n’a pas d’interface. Le formulaire de demande vit dans Microsoft
Forms ; PolicyBot avale l’export Excel des réponses.

```text
Microsoft Forms → export .xlsx → policybot ingerer → 17 recherches Exa → rapport
```

## La boucle complète

1. `policybot devis-formulaire` imprime les 35 questions à recopier dans
   Microsoft Forms. Le résultat est aussi versionné sous
   [`docs/formulaire-microsoft-forms.md`](docs/formulaire-microsoft-forms.md).
2. Les demandeurs répondent au formulaire. **Une réponse = un usage** :
   Microsoft Forms n’a pas de section répétable, donc deux usages distincts du
   même outil demandent deux réponses.
3. Tu télécharges l’export `.xlsx` des réponses.
4. `policybot ingerer reponses.xlsx --dry-run` vérifie la lecture et affiche
   l’identité d’offre résolue de chaque demande, sans dépenser un sou.
5. `policybot ingerer reponses.xlsx` lance les recherches et écrit un DOCX, un
   PDF et un `.json` de constats par demande.

## Fonctionnement

Pour une offre donnée, PolicyBot :

1. identifie l’outil, son fournisseur et son type d’IAG;
2. classifie prudemment les données décrites pour chaque usage;
3. charge 17 critères configurables (13 en partie A, 4 en partie B);
4. lance une recherche Exa indépendante par critère;
5. recueille une réponse, un niveau F/M/E proposé et une justification;
6. n’affiche que les citations retrouvées dans le texte de leur propre page;
7. produit un rapport PDF et DOCX avec le coût total des recherches.

Les recherches sont mises en cache par identité d’offre dans SQLite avec le
schéma ARP v2. Les modes `read_write`, `refresh`, `read_only` et `disabled`
sont configurables avec `POLICYBOT_ARP_CACHE_MODE`.

## Configuration

- `configs/formulaire.yaml` : les 35 questions et le champ que chacune
  alimente. C’est la source de vérité du formulaire ; il est validé contre
  `DemandeIAG` à l’import.
- `configs/recherche_defaults.yaml` : paramètres Exa, budget, schémas JSON,
  instructions et gabarits de rendu.
- `configs/recherche_criteres/*.yaml` : une question et une requête par critère.
- `POLICYBOT_SEARCH_DEFAULTS_PATH`, `POLICYBOT_CRITERIA_DIR` et
  `POLICYBOT_FORMULAIRE_PATH` : chemins de remplacement pour les tests ou un
  déploiement.
- `EXA_API_KEY` : clé Exa, conservée dans `.env` et jamais versionnée.

Le mode `neural` est utilisé par défaut. Les critères A04, A05, A11 et A12
emploient `deep` afin de mieux couvrir les enjeux contractuels. Le plafond et
la stratégie de dépassement sont définis dans le YAML commun.

## Lancer le projet

Voir [`HOW_TO_RUN.md`](HOW_TO_RUN.md) pour l’installation pas à pas.

```powershell
.\.venv\Scripts\activate
pip install -e ".[dev,pdf]"
pytest -q
policybot devis-formulaire
policybot ingerer reponses.xlsx --dry-run
```

Diagnostic réel d’un seul critère :

```powershell
python scripts/exa_debug_critere.py --critere A04 --tool ChatGPT --vendor OpenAI
```

La réponse brute est enregistrée sous `tmp/` pour inspection locale. Elle peut
contenir du texte de sources et ne doit pas être versionnée.

## Garanties

- Une défaillance Exa affecte seulement son critère.
- Une demande illisible est rejetée avec son motif ; les autres du lot passent.
- Un motif de rejet ne cite jamais une réponse libre du demandeur.
- Un niveau F/M/E invalide reste vide; PolicyBot ne l’invente pas.
- Les citations non ancrées sont rejetées et comptées.
- Les journaux structurés ne contiennent aucun texte libre : seulement longueur
  et empreinte tronquée.
- Le rapport conserve la classification déclarée et rappelle clairement que la
  validation humaine est obligatoire.

## Ce que PolicyBot ne fait pas encore

Voir [`TODO.md`](TODO.md) — notamment l’absence de toute mesure de la qualité
des recherches, et l’absence de filtre de périmètre d’offre avant extraction.
