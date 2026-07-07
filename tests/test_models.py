# tests/test_models.py
from datetime import date
from policybot.models import (
    QuestionSpec, QuestionOption, RiskFactor, Usage, InterviewState, RequestInfo,
    ContractFacts,
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
