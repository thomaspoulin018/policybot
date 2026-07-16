# TODO — PolicyBot

Mise à jour : **2026-07-16**

## État vérifié

- `pytest -k arp -q` : **44 passed**.
- `pytest -q` : **278 passed, 2 failed**.
- Les deux échecs restants concernent uniquement le désaccord entre
  `configs/policybot.yaml` (`cache.arp.mode: disabled`) et les tests qui
  attendent `read_write`.

## Réalisé depuis la précédente version

- [x] Migrer les tests et fixtures ARP vers la vérification d'ancrage des
  citations (`DEFAULT_EVIDENCE`, citations présentes dans l'évidence).
- [x] Ajouter la configuration YAML centralisée des cinq tâches LLM, avec
  surcharges par variables d'environnement.
- [x] Ajouter le routage vers un fournisseur LLM configuré par tâche et
  propager les paramètres OpenRouter (`model`, budget, température, timeout,
  raisonnement).
- [x] Ajouter les quatre modes de cache ARP : `read_write`, `refresh`,
  `read_only` et `disabled`.
- [x] Ajouter les logs internes par exécution, avec données textuelles masquées,
  identifiant d'entrevue partagé et rotation des fichiers JSONL.
- [x] Ajouter le harnais d'évaluation ARP hors pytest, trois jeux golden et les
  snapshots Tavily rejouables sous `runs/arp/2026-07-16/`.
- [x] Exécuter l'évaluation live sur ChatGPT, Claude.ai et Microsoft Copilot
  Entreprise, puis tester cinq variantes de modèle/budget. Aucun changement
  n'est retenu : les variantes introduisent au moins une valeur `WRONG_VALUE`.

## À faire — priorité immédiate

### 1. Aligner la configuration du cache ARP

- [ ] Décider le comportement par défaut en développement/production :
  `disabled` (configuration actuelle, plus conservatrice) ou `read_write`
  (attendu par les tests et utile pour amortir les collectes).
- [ ] Aligner `configs/policybot.yaml` et les deux tests de configuration, puis
  obtenir une suite complète à **280 passed**.
- [ ] Définir une durée de validité pour les analyses ARP et renseigner
  `ArpRecord.expires_at`.
- [ ] Faire respecter `ArpRecord.expires_at` à la lecture du cache, en plus de
  l'invalidation déjà présente pour une ancienne version de schéma.
- [ ] Documenter si une analyse expirée est rafraîchie automatiquement ou si
  une confirmation de l'agent responsable est requise.

### 2. Rendre l'extraction ARP exploitable en production

- [ ] Relancer `python -m policybot.contract.extraction_eval` avec un budget
  OpenRouter suffisant : la baseline du 2026-07-16 a produit
  `MATCH 5 / WRONG_ABSTAIN 43 / WRONG_VALUE 0`, les autres essais ayant
  introduit de 1 à 5 `WRONG_VALUE`.
- [ ] Examiner les erreurs récurrentes par champ
  (`sub_processors`, `data_residency`, `authentication_support`,
  `incident_response`) et ajouter des consignes négatives ciblées seulement
  après validation de la vérité terrain.
- [ ] Revalider manuellement les trois `expected.yaml` et dater les preuves
  lorsqu'une page contractuelle change.
- [ ] Évaluer une calibration exigeant deux indices indépendants pour les
  valeurs fortes, sans affaiblir l'ancrage strict des citations.

### 3. Packaging et documentation

- [ ] Inclure `policybot/grille/grille.yaml`, les templates HTML/web et les
  autres fichiers de données nécessaires dans le wheel construit.
- [ ] Mettre à jour la section de statut de `README.md`, encore basée sur
  l'ancien état « backend seul / 64 tests » et sur les trois règles initiales.
- [ ] Ajouter une procédure de lancement et de diagnostic pour les deux modes
  de collecte contractuelle : URL directe et Tavily.

## À évaluer plus tard

- [ ] Évaluer la mise en cache des classifications de données, suggestions du
  formulaire, décisions préapprouvées et résultats Tavily bruts.
- [ ] Ajouter le tableau de revue/back-office pour l'agent responsable.
- [ ] Ajouter le rafraîchissement planifié des ARP arrivées à expiration.
- [ ] Ajouter la thématisation PDF selon l'identité visuelle UQAM.

## Garde-fous à préserver

- La matrice MCN reste le seul garde-fou de permission et une cellule
  `INTERDIT` est toujours bloquante.
- Les notes F/M/E/C extraites restent des propositions, jamais une autorisation.
- Les citations doivent être verbatim, suffisamment longues et ancrées dans
  l'évidence fournie ; sinon la valeur devient `unknown`.
- Aucun texte libre (description, termes, prompt ou réponse LLM) ne doit être
  écrit en clair dans les logs.
