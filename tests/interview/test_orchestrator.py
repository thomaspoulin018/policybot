import pytest
from policybot.models import RequestInfo, QualificationProfile
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview, UnknownToolError


def _terms_get(url):
    return "<html><body>We may use your content to train our models.</body></html>"


def test_protege_b_into_public_tool_is_refused(tmp_path):
    # LLM calls in order: (1) data classifier signals, (2) ARP contract facts.
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "yes", "data_retention": "indefinite",
         "data_residency": "us", "sub_processors": "undisclosed",
         "human_review": "no", "extraction_confidence": 0.8},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-001"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Résumer des rapports financiers",
                       "data_description": "données stratégiques et renseignements personnels",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.tools[0].iag_type == "publique"
    assert state.usages[0].data_classification == "Protégé B"
    assert state.usages[0].matrix_result == "INTERDIT"
    assert state.usages[0].verdict == "Refuser"
    assert state.result_global.recommendation == "Refuser"


def test_public_data_public_tool_authorised(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-002"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.usages[0].verdict == "Autoriser"
    assert state.result_global.recommendation == "Autoriser"


def test_assess_attaches_arp_record_to_tool_ref(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-010"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.tools[0].arp is not None
    assert len(state.tools[0].arp.criteria) == 8


def test_assess_reuses_cached_arp_record_on_second_call(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    usage_inputs = [{"description": "Chercher de l'info publique",
                     "data_description": "information publique sur le web",
                     "automated_decisions": False, "mode": ["prompt"], "result_use": []}]
    itv.assess(request=RequestInfo(numero="IAG-2026-011"), tool_name="ChatGPT",
               usage_inputs=usage_inputs)
    state2 = itv.assess(request=RequestInfo(numero="IAG-2026-012"), tool_name="ChatGPT",
                        usage_inputs=usage_inputs)
    assert state2.tools[0].arp is not None


def test_unregistered_tool_without_override_raises_unknown_tool_error(tmp_path):
    llm = FakeLLMProvider(json_responses=[])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    with pytest.raises(UnknownToolError):
        itv.assess(
            request=RequestInfo(numero="IAG-2026-003"),
            tool_name="OutilInconnu",
            usage_inputs=[{"description": "Résumer un document",
                           "data_description": "notes internes",
                           "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
        )


def test_unregistered_tool_with_override_uses_override_iag_type(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "limited", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-006"),
        tool_name="OutilInconnu",
        usage_inputs=[{"description": "Résumer des notes internes",
                       "data_description": "notes internes non publiques",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
        iag_type_override="circuit_ferme",
    )
    assert state.tools[0].iag_type == "circuit_ferme"
    assert state.usages[0].data_classification == "Protégé A"
    assert state.usages[0].matrix_result == "PERMIS"
    assert state.usages[0].verdict != "Refuser"


def test_assess_stores_qualification_profile_and_tool_version(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    qualification = QualificationProfile(nb_utilisateurs_vises=12, fonctions_roles="conseillers")
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-010"),
        tool_name="ChatGPT",
        usage_inputs=[{
            "description": "Chercher de l'info publique",
            "data_description": "information publique sur le web",
            "automated_decisions": False, "mode": ["prompt"], "result_use": [],
            "frequence_utilisation": "quotidienne", "nb_utilisateurs": 5,
            "systemes_api_cibles": "",
        }],
        qualification=qualification,
        tool_version_plan_tarifaire="Plan Plus",
    )
    assert state.qualification.nb_utilisateurs_vises == 12
    assert state.qualification.fonctions_roles == "conseillers"
    assert state.tools[0].version_plan_tarifaire == "Plan Plus"
    assert state.usages[0].frequence_utilisation == "quotidienne"
    assert state.usages[0].nb_utilisateurs == 5


def test_assess_defaults_qualification_and_new_usage_fields_when_omitted(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        {"trains_on_input": "no", "data_retention": "none", "data_residency": "canada",
         "sub_processors": "disclosed", "human_review": "yes", "extraction_confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store, http_get=_terms_get)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-011"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.qualification == QualificationProfile()
    assert state.tools[0].version_plan_tarifaire == ""
    assert state.usages[0].frequence_utilisation == ""
    assert state.usages[0].nb_utilisateurs is None
