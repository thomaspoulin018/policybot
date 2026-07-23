# Analyse des résultats — amélioration générale de la recherche contractuelle

## Synthèse

La run ChatGPT met en évidence des problèmes structurels, applicables à toutes
les offres IAG : la collecte est robuste, mais pas encore assez précise pour
l’offre contractuelle réellement évaluée. Sur cette run, 8 faits sur 19 sont
acceptés et 11 restent à `unknown` — sans panne Exa. Les causes sont surtout
la portée du contrat, les citations non ancrées et des faits qu’une recherche
web ne peut pas établir.

| Résultat | Nombre | Lecture |
| --- | ---: | --- |
| `accepted` | 8 | Preuve exploitable |
| `citation_rejected` | 4 | Exa a répondu, mais la citation n’était pas retrouvée dans le texte fourni |
| `model_abstention` | 5 | La preuve ne permettait pas de conclure |
| `evidence_missing` | 2 | Aucun document candidat retenu |

Dans cette run, les faits les plus problématiques sont `audit_logging`,
`foreign_vendor_dependency`, `provider_human_access` et
`quebec_higher_ed_license` (citations rejetées), puis `training_default`, les
deux `opt_out`, les restrictions institutionnelles et la réutilisation des
données (abstention).

## Principal constat : la portée de l’offre

Un produit ne définit pas à lui seul les garanties applicables. Il faut
identifier son fournisseur, forfait, mode de déploiement, type et version du
contrat. Si ces informations sont absentes, une recherche peut mélanger des
conditions grand public, Enterprise/Edu, une documentation d’aide et des pages
commerciales. Une résidence des données, un DPA ou un contrôle de sécurité
peuvent alors être vrais pour une offre ou une configuration précise, mais pas
pour celle qui est évaluée.

La run ChatGPT l’illustre : en l’absence de forfait explicite, le système
choisit `consumer_terms` tout en pouvant retenir des pages d’autres offres du
même fournisseur.

Les 19 YAML ont exactement le même profil : `auto`, 5 résultats, 8 000
caractères, 3 phrases de *highlight*, sans domaine explicite. C’est une bonne
base uniforme, mais trop générique pour des faits très différents. Augmenter
simplement `num_results` ne règlera pas le problème : cela augmentera surtout
le bruit et le coût.

## Améliorations prioritaires

1. Rendre l’identité de l’offre obligatoire avant la recherche, ou conserver
   `unknown` quand elle est incomplète. Ajouter `{plan}`,
   `{deployment_mode}`, `{contract_type}`, `{contract_version}` et, lorsque
   nécessaire, `{jurisdiction}` aux placeholders YAML — aujourd’hui seuls
   `{tool}` et `{vendor}` sont permis — puis les placer au début des requêtes.

2. Restreindre les sources par type de contrat et par offre, pas seulement par
   domaine. Le registre de chaque fournisseur devrait déclarer les sources
   canoniques de ses offres grand public, institutionnelles et souveraines,
   ainsi que les préfixes d’URL permis. Une règle par préfixe d’URL ou une
   liste de pages canoniques est plus fiable qu’un filtre qui accepte tout un
   domaine ou tous ses sous-domaines.

3. Corriger les requêtes par fait :

   - `training_default` : rechercher explicitement la règle « contenu utilisé
     pour améliorer les modèles par défaut / sauf opt-out », avec l’offre et
     le forfait visés ;
   - `audit_logging` : rechercher les journaux et contrôles administrateur de
     l’espace de travail évalué, car ce n’est pas une capacité générique d’un
     produit ;
   - `dpa_available` et `sub_processors` : ne chercher le DPA et la liste des
     sous-traitants que lorsque l’offre peut effectivement être encadrée par un
     contrat de traitement de données ;
   - `applicable_law` : filtrer les conditions selon la juridiction et l’entité
     contractante applicables. Une version UE/EEE/UK ne qualifie pas, par elle
     même, une offre canadienne.

4. Sortir deux faits de la recherche web :

   - `opt_out_confirmed_enabled` doit venir d’une attestation administrateur
     ou d’une preuve de paramétrage du tenant ; le web ne peut pas savoir si un
     réglage est activé dans une organisation donnée ;
  - `quebec_higher_ed_license` devrait être alimenté par le
     contrat ou le procurement de l’organisation, pas déduit d’une page
     publique de produit.

5. Réduire les `citation_rejected` en demandant dans chaque `summary.query`
   une citation courte, verbatim, continue, sans ellipse, copiée du texte
   retourné. Pour les pages juridiques seulement, passer de 8 000 à 20–30 000
   caractères est aussi pertinent : la clause cherchée est souvent loin dans
   le document.

6. Ajouter au diagnostic l’identité complète de l’offre évaluée et, par fait,
   la requête finale, les filtres appliqués, les candidats rejetés et leurs
   motifs de rejet. La trace doit permettre à un analyste de comprendre
   pourquoi une page portant sur une autre édition, une autre région ou un
   autre contrat a été admise ou écartée.

## Principe de décision recommandé

La recherche doit répondre à la question « quelle preuve s’applique à cette
offre ? », plutôt qu’à « quelle information le fournisseur publie-t-il sur ce
sujet ? ». Une preuve hors périmètre ne devrait pas être sélectionnée, même si
elle est plus complète ou mieux classée par le moteur de recherche.

## Validation et confidentialité

Les YAML sont cohérents et valides : les tests de configuration et de
recherche passent (`8 passed`).

La trace de débogage contient des données en clair. Elle doit rester hors du
dépôt et être supprimée après le diagnostic.
