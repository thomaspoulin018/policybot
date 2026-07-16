# Extraction ARP — dix itérations du 2026-07-16

Jeu d'évaluation : 48 champs notés = 3 outils golden (`chatgpt`, `claude_ai`,
`microsoft_copilot_entreprise`) × 16 champs `ContractFacts`. Vérité terrain gelée
(`tests/contract/fixtures/golden/*/expected.yaml`), jamais modifiée. Toutes les
itérations tournent sur `--source snapshot`, donc sur la même évidence Tavily :
aucune itération n'a touché aux requêtes, aucune relance `--source live` n'a été
nécessaire, et les scores sont comparables entre eux.

## Le préalable : la baseline ne mesurait pas ce qu'on croyait

La baseline archivée (`baseline-snapshot.txt`, MATCH 5 / WRONG_ABSTAIN 43 /
WRONG_VALUE 0) ne décrivait aucune prudence du modèle. **Tous les appels LLM
échouaient** sur un `HTTP 402` d'OpenRouter (compte à découvert : 10 $ achetés,
10,17 $ consommés). Chaque famille retombait en `unknown` via la note
« extraction LLM échouée », et le harnais notait ces pannes comme des
abstentions. Le crédit rechargé, la même configuration donne **20 / 25 / 3**
(`baseline-working.txt`) : c'est la vraie référence des itérations 6 à 15.

Leçon à retenir hors de cette expérience : un `WRONG_ABSTAIN` de masse doit être
suspecté d'être une panne d'infrastructure avant d'être interprété comme de la
calibration. `_extract_family` avale l'exception pour ne pas tuer l'entrevue —
ce qui est le bon comportement en production, mais rend une panne totale
indiscernable d'une prudence extrême dans le rapport d'évaluation.

## Classement (MATCH décroissant, puis WRONG_VALUE croissant)

| Rang | Itération | MATCH | ABSTAIN | WRONG_VALUE | Hypothèse | Leviers touchés |
|---|---|---|---|---|---|---|
| 1 | 11 | **25** | 20 | 3 (6,2 %) | `max_tokens: 4096` tronque les réponses ; les sorties coupées retombent en `unknown`. | `policybot.yaml` : `max_tokens` 4096 → 8192 |
| 2 | 13 | 23 | 20 | 5 (10,4 %) | Si 8192 aide, 16384 aiderait davantage. | `policybot.yaml` : `max_tokens` → 16384 |
| 3 | 12 | 22 | 21 | 5 (10,4 %) | Un peu d'échantillonnage aide à trouver la bonne phrase. | `policybot.yaml` : `temperature` 0,0 → 0,3 |
| 4 | 15 | 22 | 20 | 6 (12,5 %) | **Réplication exacte de l'itération 11** : le gain tient-il ? | aucun (config 11 rejouée telle quelle) |
| 5 | 6 | 21 | 24 | 3 (6,2 %) | Le modèle paraphrase ses citations, qui échouent à l'ancrage. Rendre la copie mécanique et explicite. | `prompts.yaml` : `contract_extraction.system` + `user_template` |
| 6 | 14 | 21 | 23 | 4 (8,3 %) | Exiger des citations plus longues réduira les valeurs fausses. | `arp.py` : `_MIN_QUOTE_MATCH_CHARS` 15 → 40 |
| 7 | 8 | 21 | 22 | 5 (10,4 %) | L'ancrage par sous-chaîne exacte rejette des citations honnêtes reformatées ; un repli flou les récupérerait. | `arp.py` : `_quote_is_anchored` + repli `SequenceMatcher` à 75 % |
| 8 | 7 | 19 | 24 | 5 (10,4 %) | Retrouver la bonne phrase dans 8 000 caractères demande du raisonnement. | `policybot.yaml` : `reasoning_effort` low → high |
| 9 | 9 | 18 | 27 | 3 (6,2 %) | Une calibration explicite (« unknown est une bonne réponse ») coupera les valeurs fausses. | `prompts.yaml` : bloc « Calibration » ajouté au `system` |
| 10 | 10 | 16 | 30 | 2 (4,2 %) | Un autre modèle de la même famille extrait mieux. | `policybot.yaml` : `model` luna → `openai/gpt-5.6-terra` |

## Ce que les chiffres permettent — et ne permettent pas — de conclure

**Le résultat le plus important du lot n'est aucun des dix leviers : c'est la
mesure du bruit.** La configuration de l'itération 11 a été exécutée **trois
fois, sans qu'un seul levier ne change**, et malgré `temperature: 0.0` :

| Exécution | MATCH | ABSTAIN | WRONG_VALUE |
|---|---|---|---|
| `iteration-11.txt` | 25 | 20 | 3 |
| `iteration-15.txt` (réplication) | 22 | 20 | 6 |
| `final-confirmation.txt` (relance de confirmation) | 22 | 21 | 5 |

**La relance de confirmation ne reproduit pas le Résumé agrégé de l'itération 11**
(22 contre 25, et 5 WRONG_VALUE contre 3), et elle retombe exactement sur le
score de la réplication de l'itération 15. Le bruit run-à-run couvre une plage de
22 à 25 MATCH et de 3 à 6 WRONG_VALUE, soit autant que l'écart entre la première
et la cinquième place du classement.

Conséquences, qu'il vaut mieux assumer que maquiller :

- **Le classement ci-dessus n'est pas une hiérarchie de mérite.** Il est produit
  tel que la consigne l'exige (MATCH décroissant, WRONG_VALUE croissant), mais
  les rangs 1 à 5 (25 à 21 MATCH) tiennent dans le bruit d'une seule
  configuration rejouée. Le « 25 » de l'itération 11 est le haut de sa propre
  dispersion : ses deux réplications donnent 22 et 22.
- **Aucun des dix leviers testés n'a produit d'effet démontrable sur une
  exécution.** Le meilleur candidat reste `max_tokens: 8192` (itération 11) :
  trois exécutions donnent 25 / 22 / 22, moyenne 23,0, contre 21 pour l'itération
  6 restée à 4096 — mais ce 21 est lui-même une exécution unique, donc l'écart
  est *suggestif, pas établi*. L'hypothèse d'une troncature à 4096 est
  mécaniquement plausible, mais elle n'a **jamais été vérifiée directement** :
  aucun `finish_reason: length` n'a été observé. C'est le premier point à
  trancher, et il se tranche par une inspection de la réponse brute, pas par le
  score.
- `foreign_vendor_dependency` bascule dans les deux sens entre des runs qui ne
  diffèrent que par un levier sans rapport avec lui : marqueur de bruit, pas
  d'effet.
- Les deux seuls candidats encore plausibles sont les plus éloignés de la
  moyenne, et restent des exécutions uniques : `reasoning_effort: high`
  (itération 7, 19 MATCH / 5 WRONG_VALUE — le modèle devient affirmatif sans être
  mieux informé, et invente `sub_processors` et `incident_response`) et le modèle
  `terra` (itération 10, 16 MATCH / 30 ABSTAIN, mais le plus sûr du lot avec
  2 WRONG_VALUE).

**Pour PolicyBot, le tri par MATCH est de toute façon le mauvais tri.** Une valeur
contractuelle fausse alimente la grille comme si elle était établie, alors qu'un
`unknown` avoué appelle une vérification humaine. Le classement demandé
récompense donc la mauvaise chose, et le bruit rend ce mauvais tri instable.

## Recommandation

1. **Ne retenir aucun des dix leviers en l'état.** Aucun n'est distinguable du
   bruit sur une exécution ; `max_tokens: 8192` est le seul à mériter une
   vérification ciblée (voir ci-dessus). La
   configuration restaurée (itération 11) l'est parce que la consigne demande de
   restaurer la première du classement, **pas parce qu'elle est meilleure**.
2. **Rendre l'évaluation capable de trancher avant d'optimiser quoi que ce soit.**
   À ±3 MATCH de bruit, ce harnais ne peut pas arbitrer un gain de 2 points : les
   dix itérations ont surtout mesuré du hasard. Par ordre d'utilité : exécuter
   chaque configuration *k* fois et comparer des moyennes avec leur dispersion ;
   élargir le jeu golden au-delà de 3 outils (48 champs, c'est trop peu pour que
   quelques bascules ne dominent pas) ; enquêter sur la source de la variance à
   `temperature: 0.0` (routage OpenRouter entre fournisseurs, quantisations
   différentes ?), car sans elle rien n'est mesurable.
3. **Faire remonter les notes de `FactEvidence` dans le rapport**
   (« citation introuvable dans la preuve », « extraction LLM échouée »,
   « aucune citation vérifiable »). Le `Résumé agrégé` confond aujourd'hui trois
   `unknown` de natures opposées : le modèle a abstenu, le garde-fou a rejeté une
   citation, ou l'appel a planté. Cette confusion est exactement ce qui a masqué
   la panne 402 pendant toute la baseline.
4. **Compter les échecs d'appel LLM à part** dans le `Résumé agrégé`, plutôt que
   de les agréger silencieusement aux abstentions.

## Reproduire une variante

Chaque itération a archivé ses deux fichiers de configuration :

```
runs/arp/2026-07-16/configs/iteration-<N>/{prompts.yaml,policybot.yaml}
```

`configs/` n'est pas suivi par git : ces copies sont la seule façon de restaurer
une variante. Les itérations 8 et 14 touchent en plus `policybot/contract/arp.py`
(garde-fou), qui est suivi par git et n'est donc pas archivé ici.
