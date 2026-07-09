"""Fixed criteria tables mirroring the reference Grille document.

Each tuple is ``(category, criterion, description)`` in document order.
Rendering relies on this order to keep the report aligned with the official
form.
"""

ARP_CRITERIA: list[tuple[str, str, str]] = [
    (
        "Souveraineté et hébergement des données",
        "Localisation des serveurs",
        "Les données sont-elles hébergées au Québec ou dans une juridiction équivalente ?",
    ),
    (
        "Souveraineté et hébergement des données",
        "Juridiction applicable",
        "Quelle loi s'applique en cas de litige ? Risque d'accès par des autorités étrangères (ex. : Cloud Act US) ?",
    ),
    (
        "Souveraineté et hébergement des données",
        "Dépendance technologique",
        "Le produit augmente-t-il la dépendance envers des fournisseurs étrangers?",
    ),
    (
        "Souveraineté et hébergement des données",
        "Données soumises utilisées pour entraînement du modèle",
        "Les requêtes soumises sont-elles utilisées pour améliorer ou entraîner le modèle ? Opt-out disponible ?",
    ),
    (
        "Souveraineté et hébergement des données",
        "Garanties contractuelles de non-divulgation",
        "Le contrat interdit-il explicitement la réutilisation des données soumises ?",
    ),
    (
        "Sécurité de l'information",
        "Mécanismes d'authentification",
        "L'outil supporte-t-il l'authentification forte (SSO, MFA) ? Intégrable avec l'infrastructure UQAM ?",
    ),
    (
        "Sécurité de l'information",
        "Chiffrement des données",
        "Les données sont-elles chiffrées de bout en bout en transit et au repos ? Quel standard (AES-256, TLS 1.3) ?",
    ),
    (
        "Sécurité de l'information",
        "Journalisation et traçabilité",
        "L'outil génère-t-il des journaux d'accès et des journaux permettant d'auditer les entrées (prompts) et les sorties? Accessibles par l'organisation ?",
    ),
    (
        "Sécurité de l'information",
        "Utilisation des entrées et des sorties",
        "Existe-t-il une façon d'interdire le réentraînement du modèle à partir des données soumises par l'utilisateur et de celles qui sont produites?",
    ),
    (
        "Sécurité de l'information",
        "Gestion des incidents",
        "Le fournisseur dispose-t-il d'un plan de réponse aux incidents ? Délais de notification en cas de brèche ?",
    ),
    (
        "Conformité légale et contractuelle",
        "Propriété intellectuelle",
        "Qui détient les droits sur les contenus générés ? Le contrat préserve-t-il la PI de l'UQAM ?",
    ),
    (
        "Conformité légale et contractuelle",
        "Conditions d'utilisation acceptables",
        "Les conditions d'utilisation sont-elles acceptables pour un usage institutionnel ? Clauses problématiques ?",
    ),
    (
        "Conformité légale et contractuelle",
        "Compatibilité licence usage gouvernemental",
        "La licence permet-elle un usage par une institution d'enseignement supérieur québécoise ?",
    ),
]

USAGE_CRITERIA: list[tuple[str, str, str]] = [
    (
        "Gestion des données",
        "Fuite de données confidentielles",
        "Risque de soumettre des données institutionnelles sensibles ou stratégiques à un outil public non sécurisé.",
    ),
    (
        "Gestion des données",
        "Mauvaise classification des données",
        "Le personnel soumet des données d'une classification supérieure à ce que l'outil permet.",
    ),
    (
        "Gestion des données",
        "Utilisation de données pour entraînement",
        "Les données soumises pourraient être réutilisées par le fournisseur pour entraîner son modèle.",
    ),
    (
        "Gestion des données",
        "Compatibilité avec la LAI/PRP",
        "Les conditions du fournisseur sont-elles compatibles avec la Loi sur l'accès et la protection des renseignements personnels du Québec ?",
    ),
    (
        "Éthique et fiabilité des résultats",
        "Hallucinations et erreurs factuelles",
        "L'outil génère des informations inexactes présentées comme vraies. Risque de décisions basées sur des données erronées.",
    ),
    (
        "Éthique et fiabilité des résultats",
        "Biais algorithmiques",
        "Les résultats reflètent des biais présents dans les données d'entraînement, pouvant mener à des conclusions discriminatoires.",
    ),
    (
        "Éthique et fiabilité des résultats",
        "Supervision humaine insuffisante",
        "Les décisions ou contenus générés sont utilisés sans validation humaine adéquate avant diffusion ou action.",
    ),
    (
        "Éthique et fiabilité des résultats",
        "Propriété intellectuelle du contenu généré",
        "Les contenus générés pourraient reproduire du matériel protégé ou créer des ambiguïtés sur la propriété des livrables.",
    ),
    (
        "Risques organisationnels",
        "Formation insuffisante du personnel",
        "Le personnel utilise l'outil sans formation adéquate, augmentant le risque d'erreurs et de non-conformité.",
    ),
    (
        "Risques organisationnels",
        "Dépendance technologique",
        "Risque de surconfiance ou de dépendance à l'outil au détriment du jugement professionnel.",
    ),
    (
        "Risques organisationnels",
        "Image et réputation institutionnelle",
        "Publication de contenus générés incorrects ou inappropriés associés à l'UQAM.",
    ),
]
