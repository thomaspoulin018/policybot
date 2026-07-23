# Configurations YAML de recherche des faits

Ce dossier contient la configuration de la recherche Exa des faits
contractuels. Chaque fichier `*.yaml` décrit **un seul champ** de
`ContractFacts` (par exemple `training_default` ou `data_residency`).

Ces fichiers déterminent quoi rechercher, quelles réponses sont recevables et
comment Exa doit retourner une preuve. Ils ne rendent pas de verdict : la
grille de risques reste la seule composante qui recommande une décision.

## Déroulement d'une recherche

Pour une évaluation, PolicyBot charge tous les YAML du dossier, par ordre
alphabétique. Il lance une recherche Exa par fait (en parallèle), puis traite
chaque résultat indépendamment : l'échec d'un fait ne bloque pas les autres.

Pour un fichier donné, le déroulement est le suivant :

1. La requête `exa.query` commence par l'identité de l'offre évaluée : forfait
   (`{plan}`), mode de déploiement (`{deployment_mode}`), type
   (`{contract_type}`) et version (`{contract_version}`) du contrat, puis le
   nom de l'outil (`{tool}`) et le fournisseur (`{vendor}`). Lorsqu’un élément
   est absent, PolicyBot le rend comme `unknown` dans la requête et consigne
   l’identité incomplète dans le rapport afin que l’autorité désignée la
   confirme. Les faits qui dépendent du droit applicable peuvent aussi utiliser
   `{jurisdiction}`.
2. Exa cherche les pages correspondantes et retourne le texte, les extraits et
   un résumé structuré pour chaque résultat.
3. Le résumé doit choisir une valeur autorisée, fournir une citation verbatim
   et indiquer l'URL de la source.
4. PolicyBot conserve seulement les résultats dont la source est acceptable et
   dont la citation apparaît réellement dans le contenu retourné. Il retient
   ensuite la meilleure source selon la politique de classement.
5. Si aucune preuve ne passe ces contrôles, le fait vaut `unknown` ; aucune
   valeur n'est déduite silencieusement.

Les sources sont classées, à qualité égale, dans cet ordre : contrat, DPA,
documentation officielle, page commerciale, puis source secondaire. Les URLs
officielles connues pour l'outil sont aussi ajoutées aux domaines de recherche.

## Structure d'un fichier

Exemple simplifié tiré de `training_default.yaml` :

```yaml
version: 1
fact: training_default
category_arp: "Souveraineté et hébergement des données"
allowed_values: ["yes", "no", "unknown"]
hint: "yes si les contenus soumis servent à entraîner les modèles par défaut."

exa:
  query: "{plan} {deployment_mode} {contract_type} {contract_version} {tool} {vendor} terms customer content used to train models by default"
  type: auto
  num_results: 5
  include_domains: []
  contents:
    text: {max_characters: 8000}
    highlights: {query: "training customer content opt out", num_sentences: 3}
    summary:
      query: "Does the assessed offering use submitted data to train models by default? Return a short, verbatim, continuous quote copied exactly from the returned page text; do not use ellipses."
      schema:
        type: object
        additionalProperties: false
        required: [value, quote, source_url]
        properties:
          value: {type: string, enum: ["yes", "no", "unknown"]}
          quote: {type: string}
          source_url: {type: string}

selection:
  strategy: source_rank
  require_declared_source_url: true
```

### Métadonnées du fait

| Clé | Rôle |
| --- | --- |
| `version` | Version du format. La valeur actuelle et obligatoire est `1`. |
| `fact` | Nom exact d'un champ de `ContractFacts`. Il doit être unique dans ce dossier. |
| `category_arp` | Catégorie affichée dans l'analyse ARP ; elle décrit le contexte du fait. |
| `allowed_values` | Liste fermée des valeurs possibles. Elle doit contenir `unknown`. |
| `hint` | Note explicative destinée à guider la compréhension et la maintenance du fait. |

### Bloc `exa`

| Clé | Rôle |
| --- | --- |
| `query` | Requête de recherche. Elle doit obligatoirement contenir `{plan}`, `{deployment_mode}`, `{contract_type}`, `{contract_version}`, `{tool}` et `{vendor}`. `{jurisdiction}` est permis et requis seulement par les faits qui en dépendent. Aucun autre placeholder n'est accepté. |
| `type` | Mode de recherche Exa : `auto`, `neural`, `keyword` ou `deep`. La configuration actuelle utilise `auto`. |
| `num_results` | Nombre de résultats à demander, entre 1 et 20. |
| `include_domains` | Domaines à limiter dans la recherche. Les mêmes placeholders que `query` y sont permis. Les domaines officiels connus de l'outil sont ajoutés automatiquement. |
| `contents.text.max_characters` | Quantité maximale de texte demandée par résultat (1 à 50 000 caractères). |
| `contents.highlights` | Requête utilisée par Exa pour sélectionner des extraits, et nombre de phrases demandées (1 à 10). |
| `contents.summary` | Question posée à Exa pour produire une réponse structurée et le schéma JSON qui impose son format. |

Le `summary.schema` doit toujours définir et exiger les trois propriétés
`value`, `quote` et `source_url`. L'énumération
`summary.schema.properties.value.enum` doit être exactement identique à
`allowed_values`, dans le même ordre. Cela évite qu'Exa retourne une valeur que
le modèle ne peut pas utiliser.

Les recherches qui visent des pages juridiques (conditions, contrat, DPA ou
politique de confidentialité) demandent actuellement 24 000 caractères; les
recherches de documentation technique restent à 8 000 caractères.

Pour forcer le mode `deep` sur tous les faits sans modifier les YAML, définissez
`POLICYBOT_EXA_SEARCH_TYPE=deep` dans l'environnement puis redémarrez
l'application. Ce mode réalise une recherche multi-étapes; il est donc plus
lent et plus coûteux. Sans cette variable, chaque fichier conserve son propre
mode `type`.

### Bloc `selection`

`strategy` vaut actuellement toujours `source_rank`. Quand plusieurs résultats
fournissent une preuve valide pour le même fait, PolicyBot sélectionne d'abord
la source la plus fiable, puis le score de pertinence Exa, puis l'URL pour
départager de manière déterministe. L'ordre de fiabilité est : document
contractuel, DPA, documentation technique officielle, page commerciale, puis
source secondaire. Ainsi, une clause contractuelle est retenue avant une page
marketing, même si cette dernière a un meilleur score Exa.

Quand `require_declared_source_url` vaut `true`, l'URL indiquée dans le résumé
Exa (`source_url`) doit être exactement celle du résultat dont PolicyBot
utilise le contenu. Si elles diffèrent, le candidat est rejeté. Ce contrôle
évite d'accepter une citation attribuée à une autre page, mais peut aussi faire
tomber le fait à `unknown` lorsqu'Exa utilise une URL canonique ou redirigée.

Les configurations livrées utilisent `false` : l'URL réelle du résultat reste
enregistrée comme preuve et la citation doit toujours être présente dans son
contenu. L'URL déclarée par Exa est alors conservée à titre d'information, sans
rejeter une preuve dont l'URL déclarée diffère.

## Ajouter ou modifier une configuration

1. Modifiez le YAML du fait existant, ou créez un nouveau fichier seulement si
   le champ correspondant existe déjà dans `ContractFacts`.
2. Choisissez des valeurs de `allowed_values` reconnues par ce champ, ajoutez
   toujours `unknown`, puis recopiez exactement cette liste dans l'`enum` de
   `summary.schema`.
3. Écrivez une requête précise, en conservant l'identité complète de l'offre
   au début : `{plan} {deployment_mode} {contract_type} {contract_version}`,
   puis `{tool} {vendor}`. Ajoutez `{jurisdiction}` lorsqu'un fait dépend de
   la compétence applicable. La
   question `summary.query` doit demander une réponse factuelle limitée aux
   valeurs de l'énumération et exiger une citation courte, verbatim, continue,
   copiée exactement du texte retourné, sans ellipse.
4. Gardez `require_declared_source_url: false` pour accepter une URL canonique
   ou redirigée déclarée par Exa, tout en vérifiant la citation contre l'URL
   réellement retenue.
5. Exécutez `pytest tests/contract/test_fact_search.py tests/contract/test_exa.py -v`.

Au chargement, PolicyBot refuse une configuration avec une clé inconnue, un
fait inconnu ou dupliqué, une valeur invalide, des placeholders manquants, ou
un schéma de résumé incohérent. Il exige également un YAML pour chaque champ
contractuel attendu : supprimer un fichier sans mettre à jour le modèle et les
tests fait donc échouer le démarrage ou les tests.

## Emplacement et rechargement

Le dossier par défaut est `configs/recherche_des_faits`. Il peut être remplacé
par la variable d'environnement `POLICYBOT_FACT_SEARCH_DIR`, utile notamment
pour tester un jeu de configurations isolé. Les définitions sont chargées au
chargement du module Python ; après une modification en production, redémarrez
l'application pour garantir que le nouveau jeu de YAML est pris en compte.
