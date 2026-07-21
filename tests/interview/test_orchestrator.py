import pytest
from policybot.models import ArpRecord, ContractFacts, RequestInfo, QualificationProfile
from policybot.llm.fake import FakeLLMProvider
from policybot.preapproved.store import PreApprovedStore
from policybot.interview.orchestrator import Interview, UnknownToolError
from tests.helpers.arp_fixtures import DEFAULT_EVIDENCE, arp_extraction_responses, exa_evidence


def _terms_get(url):
    # Les CGU simulées incluent DEFAULT_EVIDENCE : l'extraction rejette toute
    # valeur dont la citation n'est pas ancrée dans la preuve, et c'est de ce
    # texte que `arp_extraction_responses` tire la sienne.
    return (
        "<html><body>We may use your content to train our models. "
        f"{DEFAULT_EVIDENCE}</body></html>"
    )


def test_protege_b_into_public_tool_is_refused(tmp_path):
    # A matrix refusal must stop after the data-classifier call.
    llm = FakeLLMProvider(json_responses=[
        {"already_public": False, "contains_personal_info": True,
         "strategic_sensitive": True, "internal_nonpublic": True,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(
            training_default="yes", data_retention="indefinite",
            data_residency="us", sub_processors="undisclosed",
            provider_human_access="no",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(
        llm=llm, store=store,
        exa_search=lambda tool_name, offering: exa_evidence(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    )
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
    assert state.tools[0].arp is None
    assert len(llm.calls) == 1  # Only the data classifier ran.


def test_public_data_public_tool_authorised(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
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
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-010"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )
    assert state.tools[0].arp is not None
    assert len(state.tools[0].arp.criteria) == 13


def test_assess_reuses_cached_arp_record_on_second_call(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
    usage_inputs = [{"description": "Chercher de l'info publique",
                     "data_description": "information publique sur le web",
                     "automated_decisions": False, "mode": ["prompt"], "result_use": []}]
    itv.assess(request=RequestInfo(numero="IAG-2026-011"), tool_name="ChatGPT",
               usage_inputs=usage_inputs)
    state2 = itv.assess(request=RequestInfo(numero="IAG-2026-012"), tool_name="ChatGPT",
                        usage_inputs=usage_inputs)
    assert state2.tools[0].arp is not None


def test_assess_refreshes_stale_cached_arp_record(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    store.save_arp(ArpRecord(
        tool_name="ChatGPT",
        iag_type="publique",
        contract_facts=ContractFacts(training_default="yes"),
        schema_version=1,
    ))
    itv = Interview(
        llm=llm, store=store,
        exa_search=lambda tool_name, offering: exa_evidence(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    )

    state = itv.assess(
        request=RequestInfo(numero="IAG-2026-STALE"),
        tool_name="ChatGPT",
        usage_inputs=[{"description": "Chercher de l'info publique",
                       "data_description": "information publique sur le web",
                       "automated_decisions": False, "mode": ["prompt"], "result_use": []}],
    )

    assert state.tools[0].arp is not None
    assert state.tools[0].arp.schema_version == 4
    assert state.tools[0].arp.contract_facts.training_default == "no"
    assert store.get_arp("ChatGPT").schema_version == 4


@pytest.mark.parametrize(
    ("mode", "reuses_cached", "replaces_cached"),
    [
        ("read_write", True, False),
        ("read_only", True, False),
        ("refresh", False, True),
        ("disabled", False, False),
    ],
)
def test_arp_cache_modes(tmp_path, mode, reuses_cached, replaces_cached):
    cached = ArpRecord(
        tool_name="ChatGPT",
        iag_type="publique",
        contract_facts=ContractFacts(training_default="yes"),
        schema_version=4,
        terms_snapshot="cached-marker",
    )
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    store.save_arp(cached)
    responses = []
    llm = FakeLLMProvider(json_responses=responses)
    itv = Interview(
        llm=llm,
        store=store,
        arp_cache_mode=mode,
    )

    resolved = itv._resolve_arp("ChatGPT", "publique")
    stored = store.get_arp("ChatGPT")

    assert (resolved.terms_snapshot == "cached-marker") is reuses_cached
    assert (stored.terms_snapshot != "cached-marker") is replaces_cached
    assert llm.tasks == []


def test_read_only_cache_miss_fetches_without_saving(tmp_path):
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    llm = FakeLLMProvider(json_responses=[])
    itv = Interview(
        llm=llm,
        store=store,
        arp_cache_mode="read_only",
    )

    resolved = itv._resolve_arp("ChatGPT", "publique")

    assert resolved.schema_version == 4
    assert store.get_arp("ChatGPT") is None
    assert llm.tasks == []

def test_unregistered_tool_without_override_raises_unknown_tool_error(tmp_path):
    llm = FakeLLMProvider(json_responses=[])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
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
        *arp_extraction_responses(
            training_default="no", data_retention="limited", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
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
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
    qualification = QualificationProfile(
        nb_utilisateurs_vises=12,
        fonctions_roles="conseillers",
        formation_iag_recue="aucune",
    )
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
    assert any("formation préalable" in condition.lower() for condition in state.usages[0].conditions)


def test_assess_defaults_qualification_and_new_usage_fields_when_omitted(tmp_path):
    llm = FakeLLMProvider(json_responses=[
        {"already_public": True, "contains_personal_info": False,
         "strategic_sensitive": False, "internal_nonpublic": False,
         "highly_sensitive_secret": False, "confidence": 0.9},
        *arp_extraction_responses(
            training_default="no", data_retention="none", data_residency="quebec",
            sub_processors="disclosed", provider_human_access="yes",
        ),
    ])
    store = PreApprovedStore(str(tmp_path / "pb.db"))
    itv = Interview(llm=llm, store=store)
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
