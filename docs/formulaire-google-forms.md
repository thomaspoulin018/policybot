# Formulaire Google Forms — demande d'utilisation d'un outil d'IAG

Généré par `policybot devis-formulaire`. **Ne pas modifier à la main** :
la source de vérité est `configs/formulaire.yaml`. Régénérer avec

    policybot devis-formulaire > docs/formulaire-google-forms.md

Le formulaire réel est créé par `policybot creer-formulaire`. L'ingestion
s'appuie sur les `questionId`, donc les intitulés peuvent être reformulés sans
casser le mapping.

```text
Demande d'utilisation d'un outil d'IA générative
================================================

Ce formulaire sert à documenter une demande d'utilisation d'un outil d'IA
générative. Il ne rend aucune décision : il produit un dossier de constats
sourcés qu'une personne responsable examine ensuite.

Une réponse = un usage. Si tu prévois plusieurs usages distincts du même
outil, remplis le formulaire une fois par usage.

Ne colle jamais de données réelles dans tes réponses : décris-les.

Page 1 — Outils déjà approuvés
------------------------------
  Avant de remplir quoi que ce soit : si l'outil que tu veux utiliser
  figure dans la liste ci-dessous, il a déjà été évalué et approuvé.

  N'utilise pas ce formulaire : écris directement à la sécurité informatique
  (ADRESSE À COMPLÉTER) pour demander l'accès.

  Continue seulement si ton outil n'apparaît pas dans la liste, ou si
  ton usage sort de ce qui a été approuvé pour cet outil.

  - À COMPLÉTER — Aucun outil approuvé n'est encore inscrit dans le catalogue

Section 1 — La demande
----------------------

 1. Nom du demandeur [obligatoire]
    type   : texte
    champ  : demandeur

 2. Unité administrative [obligatoire]
    type   : texte
    champ  : unite

Section 2 — L'outil et son offre contractuelle
----------------------------------------------
  Les questions 5 à 10 déterminent l'identité de l'offre contractuelle
  évaluée. Sans forfait ni type de contrat, une garantie réservée aux
  offres Entreprise peut être attribuée à tort à une offre grand public.

 3. Quel outil d'IA générative comptes-tu utiliser ? [obligatoire]
    type   : texte
    champ  : tool_name
    aide   : Nom commercial de l'outil, par exemple ChatGPT, Microsoft Copilot, Gemini.

 4. Type d'outil, si l'outil n'est pas dans notre registre
    type   : choix
    champ  : tool_type_override
    choix  : IAG publique — Ex. ChatGPT, Claude.ai, Perplexity
    choix  : IAG circuit fermé — Ex. Microsoft Copilot Entreprise
    choix  : IAG souveraine — Hébergée au Québec
    choix  : IAG gouvernementale — Hébergée par l'UQAM / le gouvernement
    aide   : À remplir seulement si l'outil est peu connu ; sinon laisser vide.

 5. Version ou plan tarifaire
    type   : texte
    champ  : version_plan_tarifaire
    aide   : Ex. Plan Plus, Licence institutionnelle Entreprise, Workspace Business.

 6. Mode de déploiement
    type   : choix
    champ  : deployment_mode
    choix  : Service public
    choix  : Service institutionnel géré
    choix  : Hébergement souverain
    choix  : Hébergement gouvernemental
    choix  : Sur site
    aide   : Laisser vide pour le déduire du type d'outil.

 7. Type de contrat
    type   : choix
    champ  : contract_type
    choix  : Conditions grand public
    choix  : Contrat institutionnel
    choix  : Entente gouvernementale
    choix  : Entente de traitement des données
    aide   : Laisser vide pour le déduire du plan tarifaire.

 8. Version du contrat
    type   : texte
    champ  : contract_version
    aide   : Ex. DPA-2026-07.

 9. Date d'effet du contrat
    type   : date
    champ  : contract_effective_date

10. Territoire ou compétence applicable
    type   : texte
    champ  : jurisdiction
    aide   : Ex. Québec, Canada ; Californie, États-Unis.

Section 3 — Qui utilisera l'outil
---------------------------------

11. Nombre d'utilisateurs visés
    type   : nombre
    champ  : nb_utilisateurs_vises
    aide   : Indique un nombre entier, en chiffres seulement — par exemple 25.
             N'écris pas « une vingtaine » ni « env. 25 » : la réponse serait rejetée.

12. Fonctions et rôles concernés
    type   : texte_long
    champ  : fonctions_roles

13. Niveau de maîtrise numérique
    type   : choix
    champ  : niveau_maitrise_ti
    choix  : Débutant
    choix  : Intermédiaire
    choix  : Avancé

14. Formation en IAG reçue
    type   : choix
    champ  : formation_iag_recue
    choix  : Aucune — Aucune formation formelle ou rappel sur les bonnes pratiques.
    choix  : Partielle — Quelques notions vues, mais pas encore un parcours complet.
    choix  : Complète (MCN) — Le groupe a déjà suivi la formation complète prévue par l'organisation.

15. Accès à de l'information Protégé A ou plus
    type   : choix
    champ  : acces_protege_a_ou_plus
    choix  : Oui — Le groupe a accès à de l'information Protégé A, B ou plus.
    choix  : Non — Le groupe ne manipule pas ce niveau d'information dans son travail courant.
    choix  : À vérifier — L'information n'est pas confirmée pour l'instant.

Section 4 — Les données soumises
--------------------------------

16. Quel type de données comptez-vous soumettre à l'outil ?
    type   : choix_multiple
    champ  : data_checked
    choix  : Information déjà publique — Statistiques publiées, communiqués, code public
    choix  : Documents internes de travail — Notes, brouillons, code applicatif privé
    choix  : Renseignements personnels — Noms, dossiers, coordonnées de personnes
    choix  : Données stratégiques / confidentielles — Informations sensibles pour l'institution

17. Décris ces données dans tes mots [obligatoire]
    type   : texte_long
    champ  : data_free_text
    aide   : Décris la NATURE des données, jamais les données elles-mêmes.
             Ne colle ici aucun nom, aucun numéro de dossier, aucun extrait réel.
             Exemple correct : « notes de travail internes non publiques, sans
             renseignement personnel ».

Section 5 — L'usage prévu
-------------------------

18. Comment vas-tu utiliser cet outil ? [obligatoire]
    type   : texte_long
    champ  : usage_description

19. Mode d'utilisation
    type   : choix
    champ  : mode
    choix  : Messages directs (prompt)
    choix  : Intégration technique (API)

20. Fréquence d'utilisation
    type   : texte
    champ  : frequence_utilisation

21. Nombre d'utilisateurs pour cet usage
    type   : nombre
    champ  : nb_utilisateurs
    aide   : Indique un nombre entier, en chiffres seulement — par exemple 25.
             N'écris pas « une vingtaine » ni « env. 25 » : la réponse serait rejetée.

22. Systèmes ou API visés par l'intégration
    type   : texte
    champ  : systemes_api_cibles

23. Comment comptez-vous utiliser les résultats ?
    type   : choix_multiple
    champ  : result_use_checked
    choix  : Prise de décision
    choix  : Publication
    choix  : Intrant dans un autre processus
    choix  : Aide à la rédaction / diffusion interne

24. Précisions sur l'utilisation des résultats
    type   : texte
    champ  : result_use_free_text

25. Les résultats déclenchent-ils une décision sans révision humaine ?
    type   : oui_non
    champ  : automated_decisions

Section 6 — Le contexte d'affaires
----------------------------------

26. Quel besoin d'affaires cet outil répond-il ? [obligatoire]
    type   : texte_long
    champ  : besoin_affaires

27. Gains qualitatifs attendus
    type   : texte_long
    champ  : gains_qualitatifs

28. Gains quantitatifs attendus
    type   : texte_long
    champ  : gains_quantitatifs

29. Alternatives considérées
    type   : texte_long
    champ  : alternatives_considerees

30. Urgence perçue
    type   : choix
    champ  : urgence_percue
    choix  : Faible
    choix  : Modérée
    choix  : Élevée

31. Coût annuel par utilisateur
    type   : texte
    champ  : cout_annuel_par_utilisateur

32. Coût total annuel
    type   : texte
    champ  : cout_total_annuel

33. Mode d'acquisition
    type   : choix
    champ  : mode_acquisition
    choix  : Achat direct
    choix  : Via SEAO
    choix  : Via appel d'offres
    choix  : Contrat existant

34. Durée du contrat
    type   : texte
    champ  : duree_contrat

35. Responsable budgétaire
    type   : texte
    champ  : responsable_budgetaire

35 questions.
```
