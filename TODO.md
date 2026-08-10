# TODO

Inventaire honnête de ce qui manque, classé par gravité. Rien de tout ceci
n'est en cours : c'est ce qui reste sur la table après la refonte vers
l'ingestion de formulaire.

## Critique

### Aucune mesure de la qualité des recherches

Le harnais d'évaluation est mort avec le pivot vers Exa. Modifier un YAML de
critère est donc un pari : on ne peut ni prouver un progrès, ni détecter une
régression. **Si un seul point devait passer devant les autres, c'est
celui-là** — sans lui, les deux suivants ne peuvent même pas être travaillés.

### Le périmètre de l'offre n'est pas contrôlé

Aucun filtre n'écarte une page hors-offre avant extraction. Une garantie
réservée aux offres Entreprise peut donc être présentée comme applicable à une
offre grand public, avec une citation ancrée — donc crédible. C'est le seul
défaut du système qui produit une *fausse* conclusion plutôt qu'une absence de
conclusion. Voir
[`docs/ANALYSE_AMELIORATION_RECHERCHE_CONTRACTUELLE.md`](docs/ANALYSE_AMELIORATION_RECHERCHE_CONTRACTUELLE.md).

## Élevé

### `expires_at` n'est jamais renseigné ni respecté

Le cache ARP (`policybot/contract/cache.py`) n'expire que par version de
schéma. Une analyse d'août 2026 sera resservie intacte en 2028, alors que les
conditions du fournisseur auront changé plusieurs fois.

### Aucun test avec une vraie réponse Exa

Toute la suite passe par un client injecté. Un changement de forme de la
réponse Exa ne serait vu qu'en production.

### Aucun export Microsoft Forms réel n'a été vérifié

La fixture `tests/fixtures/reponses_forms.xlsx` est écrite par nous. Il faut
s'envoyer le formulaire à soi-même, exporter, et passer ce fichier en
`--dry-run`. C'est la seule étape que le code ne peut pas vérifier tout seul.

## Moyen

### Aucune intégration continue

Les tests ne tournent que sur une machine de développement, quand on y pense.

### Le gabarit DOCX dépend de l'emplacement du dépôt

`_DEFAULT_FICHE_TEMPLATE` remonte de deux niveaux depuis le module vers
`documents_reference/`. Le `pyproject.toml` le déclare désormais en
`data-files`, mais le chemin par défaut reste relatif au dépôt ;
`POLICYBOT_FICHE_TEMPLATE` est la porte de sortie.

### Aucun suivi du coût cumulé

Le plafond budgétaire est par exécution. Rien n'empêche cinquante exécutions à
0,90 $.

## Par conception

### Rien ne relie les constats à une recommandation

La grille MCN a été supprimée : l'officier désigné décide. C'est cohérent, et
c'est désormais écrit — ce n'est pas un oubli mais une décision de conception.

### Un usage par réponse

Microsoft Forms n'a pas de section répétable. Le wizard gérait plusieurs usages
par demande ; le formulaire n'en gère qu'un. Pour deux usages, le demandeur
remplit le formulaire deux fois.
