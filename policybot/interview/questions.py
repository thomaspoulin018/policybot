from policybot.models import QuestionSpec, QuestionOption


def data_description_question() -> QuestionSpec:
    return QuestionSpec(
        id="data_description",
        header="Type de données",
        question="Quel type de données comptez-vous soumettre à l'outil ?",
        multi_select=False,
        allow_other=True,
        options=[
            QuestionOption(label="Information déjà publique",
                           description="Statistiques publiées, communiqués, code public"),
            QuestionOption(label="Documents internes de travail",
                           description="Notes, brouillons, code applicatif privé"),
            QuestionOption(label="Renseignements personnels",
                           description="Noms, dossiers, coordonnées de personnes"),
            QuestionOption(label="Données stratégiques / confidentielles",
                           description="Informations sensibles pour l'institution"),
        ],
    )


def usage_details_question() -> QuestionSpec:
    return QuestionSpec(
        id="usage_details",
        header="Utilisation",
        question="Comment comptez-vous utiliser les résultats ?",
        multi_select=True,
        allow_other=True,
        options=[
            QuestionOption(label="Prise de décision"),
            QuestionOption(label="Publication"),
            QuestionOption(label="Intrant dans un autre processus"),
            QuestionOption(label="Aide à la rédaction / diffusion interne"),
        ],
    )
