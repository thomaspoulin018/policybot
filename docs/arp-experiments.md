# Expériences d'extraction ARP

## 2026-07-16 — robustesse de l'extraction contractuelle sur collecte Tavily live

Baseline : MATCH 5 / WRONG_ABSTAIN 43 / WRONG_VALUE 0
Snapshot : `runs/arp/2026-07-16/`

La baseline a été collectée en live sur ChatGPT, Claude.ai et Microsoft
Copilot Entreprise : cinq recherches Tavily par outil, puis un Extract groupé
par outil. Les réponses Search et Extract brutes sont conservées sous
`snapshots/`. Le rejeu `--source snapshot` reproduit exactement les comptes de
la collecte live. Toutes les itérations utilisent donc la même évidence; aucune
recollecte live n'a été nécessaire.

Échec d'infrastructure avant baseline : la première commande live a échoué avec
`ModuleNotFoundError: tavily`. L'artefact
`infrastructure-live-failure.txt` est conservé dans le run. L'installation de
l'environnement déclaré par `pip install -e ".[dev]"` a corrigé le problème,
sans changement de logique d'extraction.

Validation finale : les 37 tests ciblés de l'évaluateur, de l'ARP et des erreurs
Tavily passent. La suite complète termine à 278 réussites et 2 échecs hors
périmètre : deux tests attendent `cache.arp.mode: read_write`, tandis que la
configuration de départ contient `disabled`. Ce réglage n'a pas été modifié par
le run.

Diagnostic de la baseline : les 43 abstentions correspondent à des échecs des
appels LLM. OpenRouter répond HTTP 402 parce que les 4 096 tokens de sortie
demandés dépassent le plafond encore finançable annoncé de 3 525 tokens. Les
cinq MATCH sont uniquement les vérités terrain dont la valeur attendue est
déjà `unknown`. Cette baseline est valide comme état observé, mais dégénérée;
elle rend le garde-fou `WRONG_VALUE == 0` particulièrement difficile à battre.

### Itération 1 — les abstentions viennent du budget de sortie supérieur au plafond OpenRouter

Hypothèse formulée avant modification : réduire le budget à 1 024 tokens
permettra aux appels LLM de s'exécuter et de récupérer des faits sans inventer.

Changement : `configs/policybot.yaml`, uniquement
`contract_extraction.max_tokens`, de 4 096 à 1 024.
Résultat : MATCH 18 / WRONG_ABSTAIN 28 / WRONG_VALUE 2
Écart à la baseline : MATCH +13 / WRONG_ABSTAIN -15 / WRONG_VALUE +2.
Erreurs : `chatgpt.incident_response` vaut `documented_no_notice` au lieu de
`unknown`; `claude_ai.data_residency` vaut `other` au lieu de `us`.
Verdict : annulé — toute hausse de WRONG_VALUE est éliminatoire; la valeur a été
remise immédiatement à 4 096.

### Itération 2 — un modèle Flash Lite moins coûteux peut exécuter le budget inchangé en restant conservateur

Hypothèse formulée avant modification : Gemini 2.5 Flash Lite acceptera 4 096
tokens à moindre coût et s'abstiendra lorsque la clause ne suffit pas.

Changement : `configs/policybot.yaml`, uniquement
`contract_extraction.model`, de `openai/gpt-5.6-luna` à
`google/gemini-2.5-flash-lite`.
Résultat : MATCH 19 / WRONG_ABSTAIN 24 / WRONG_VALUE 5
Écart à la baseline : MATCH +14 / WRONG_ABSTAIN -19 / WRONG_VALUE +5.
Erreurs : résidence ChatGPT et Claude, sous-traitants ChatGPT, réponse aux
incidents ChatGPT et niveau des journaux Microsoft Copilot.
Verdict : annulé — gain brut maximal en MATCH, mais cinq valeurs inventées ou
surinterprétées; le modèle initial a été restauré immédiatement.

### Itération 3 — Claude 3 Haiku sera plus littéral et prudent

Hypothèse formulée avant modification : un petit modèle Anthropic moins cher
pourra exécuter 4 096 tokens et ne valider que les formulations explicites.

Changement : `configs/policybot.yaml`, uniquement
`contract_extraction.model`, de `openai/gpt-5.6-luna` à
`anthropic/claude-3-haiku`.
Résultat : MATCH 11 / WRONG_ABSTAIN 36 / WRONG_VALUE 1
Écart à la baseline : MATCH +6 / WRONG_ABSTAIN -7 / WRONG_VALUE +1.
Erreur : `chatgpt.sub_processors` vaut `disclosed` au lieu de `undisclosed`.
Verdict : annulé — c'est le signal le plus proche d'un gain admissible, mais
une seule hausse de WRONG_VALUE suffit; le modèle initial a été restauré.

### Itération 4 — GPT-4o mini combinera format structuré fiable et prudence

Hypothèse formulée avant modification : le support du format structuré et le
faible coût de GPT-4o mini permettront quelques extractions sûres à budget
inchangé.

Changement : `configs/policybot.yaml`, uniquement
`contract_extraction.model`, de `openai/gpt-5.6-luna` à
`openai/gpt-4o-mini`.
Résultat : MATCH 18 / WRONG_ABSTAIN 28 / WRONG_VALUE 2
Écart à la baseline : MATCH +13 / WRONG_ABSTAIN -15 / WRONG_VALUE +2.
Erreurs : `authentication_support` est surclassé `sso_mfa` au lieu de
`partial`, pour ChatGPT et Claude.ai.
Verdict : annulé — deux valeurs erronées; le modèle initial a été restauré.

### Itération 5 — GPT-4.1 nano ne validera que les clauses les plus explicites

Hypothèse formulée avant modification : le modèle nano, orienté classification,
sera assez conservateur pour garder WRONG_VALUE à zéro.

Changement : `configs/policybot.yaml`, uniquement
`contract_extraction.model`, de `openai/gpt-5.6-luna` à
`openai/gpt-4.1-nano`.
Résultat : MATCH 14 / WRONG_ABSTAIN 30 / WRONG_VALUE 4
Écart à la baseline : MATCH +9 / WRONG_ABSTAIN -13 / WRONG_VALUE +4.
Erreurs : résidence, sous-traitants, authentification et réponse aux incidents,
toutes pour ChatGPT.
Verdict : annulé — quatre valeurs erronées; le modèle initial a été restauré.

### Synthèse

Retenu : rien. Aucun changement d'extraction ne respecte le garde-fou de zéro
hausse de WRONG_VALUE. Le meilleur signal prudent est l'itération 3
(11 / 36 / 1), mais il reste inadmissible. Sur trois cas golden seulement, les
écarts observés sont des signaux et non une validation générale.

Écarté :

- budget de sortie à 1 024 : débloque le modèle initial mais introduit deux
  erreurs;
- Gemini 2.5 Flash Lite : meilleur nombre brut de MATCH, au prix de cinq
  erreurs;
- Claude 3 Haiku : une erreur persistante sur la sémantique de la divulgation
  des sous-traitants;
- GPT-4o mini : surclasse l'authentification de deux offres;
- GPT-4.1 nano : quatre surinterprétations concentrées sur ChatGPT.

À creuser : isoler les erreurs récurrentes par champ avec des consignes
négatives ciblées (`sub_processors`, `data_residency`,
`authentication_support`, `incident_response`); vérifier si la vérité terrain
`chatgpt.sub_processors: undisclosed` correspond toujours aux pages publiques
collectées; tester une passe de calibration qui exige deux indices indépendants
pour les niveaux forts; obtenir un budget OpenRouter suffisant pour mesurer le
modèle initial hors échec HTTP 402. Si l'ancrage strict des citations augmente
les abstentions, le documenter seulement : `_quote_is_anchored()` et `_accept()`
restent des garde-fous de conception et n'ont pas été modifiés.
