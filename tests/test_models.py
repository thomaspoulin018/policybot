# tests/test_models.py
from datetime import date
from policybot.models import (
    QuestionSpec, QuestionOption, RiskFactor, Usage, InterviewState, RequestInfo,
    ContractFacts, ToolRef, QualificationProfile,
)


def test_questionspec_defaults():
    q = QuestionSpec(
        id="data_description",
        header="Type de données",
        question="Quel type de données?",
        options=[QuestionOption(label="Info publique", description="Web, docs publics")],
    )
    assert q.multi_select is False
    assert q.allow_other is True
    assert q.options[0].label == "Info publique"


def test_riskfactor_requires_origin_and_proposed():
    rf = RiskFactor(
        category="Gestion des données", criterion="Fuite de données",
        inherent="E", residual="M", origin="rule", proposed=True,
    )
    assert rf.origin == "rule"
    assert rf.proposed is True


def test_riskfactor_residual_defaults_to_empty_for_officer_review():
    rf = RiskFactor(
        category="Gestion des données", criterion="Fuite de données",
        inherent="E", origin="rule",
    )

    assert rf.residual is None


def test_interviewstate_starts_empty():
    st = InterviewState(interview_id="abc", request=RequestInfo(numero="IAG-2026-001"))
    assert st.status == "in_progress"
    assert st.usages == []
    assert st.tools == []


def test_contractfacts_new_fields_default_to_unknown():
    facts = ContractFacts()
    assert facts.encryption_standard == "unknown"
    assert facts.ip_ownership == "unknown"


def test_contractfacts_accepts_explicit_encryption_and_ip_values():
    facts = ContractFacts(encryption_standard="strong", ip_ownership="customer")
    assert facts.encryption_standard == "strong"
    assert facts.ip_ownership == "customer"


def test_qualificationprofile_defaults_to_empty_values():
    profile = QualificationProfile()
    assert profile.nb_utilisateurs_vises is None
    assert profile.fonctions_roles == ""
    assert profile.niveau_maitrise_ti is None
    assert profile.formation_iag_recue is None
    assert profile.acces_protege_a_ou_plus is None
    assert profile.besoin_affaires == ""
    assert profile.urgence_percue is None
    assert profile.cout_annuel_par_utilisateur == ""
    assert profile.mode_acquisition is None
    assert profile.responsable_budgetaire == ""


def test_interviewstate_defaults_to_empty_qualification_profile():
    st = InterviewState(interview_id="abc", request=RequestInfo(numero="IAG-2026-001"))
    assert st.qualification == QualificationProfile()


def test_toolref_defaults_version_plan_tarifaire_to_empty_string():
    ref = ToolRef(name="ChatGPT")
    assert ref.version_plan_tarifaire == ""


def test_usage_defaults_new_section3_fields_to_empty():
    usage = Usage()
    assert usage.frequence_utilisation == ""
    assert usage.nb_utilisateurs is None
    assert usage.systemes_api_cibles == ""
