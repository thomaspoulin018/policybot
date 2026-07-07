from policybot.web.wizard_state import WizardState, compose_description


def test_compose_description_joins_labels_and_free_text():
    result = compose_description(
        ["Renseignements personnels", "Documents internes de travail"],
        "des courriels d'étudiants",
    )
    assert result == "Renseignements personnels; Documents internes de travail; des courriels d'étudiants"


def test_compose_description_with_only_free_text():
    assert compose_description([], "info publique") == "info publique"


def test_compose_description_with_only_labels():
    assert compose_description(["Info déjà publique"], "") == "Info déjà publique"


def test_to_hidden_fields_only_emits_nonempty_values():
    state = WizardState(tool_name="ChatGPT", data_checked=["A", "B"])
    fields = state.to_hidden_fields()
    assert ("tool_name", "ChatGPT") in fields
    assert ("data_checked", "A") in fields
    assert ("data_checked", "B") in fields
    assert not any(name == "tool_type_override" for name, _ in fields)
    assert not any(name == "automated_decisions" for name, _ in fields)


def test_to_hidden_fields_emits_automated_decisions_only_when_true():
    state = WizardState(automated_decisions=True)
    fields = state.to_hidden_fields()
    assert ("automated_decisions", "true") in fields


def test_from_form_roundtrips_single_and_repeated_fields():
    form = {
        "tool_name": "ChatGPT",
        "tool_type_override": "publique",
        "data_checked": ["Renseignements personnels", "Documents internes de travail"],
        "data_free_text": "notes de cours",
        "usage_description": "Résumer des articles",
        "mode": "api",
        "result_use_checked": "Publication",
        "result_use_free_text": "",
        "automated_decisions": "true",
    }
    state = WizardState.from_form(form)
    assert state.tool_name == "ChatGPT"
    assert state.tool_type_override == "publique"
    assert state.data_checked == ["Renseignements personnels", "Documents internes de travail"]
    assert state.data_free_text == "notes de cours"
    assert state.mode == "api"
    assert state.result_use_checked == ["Publication"]
    assert state.automated_decisions is True


def test_from_form_defaults_on_missing_keys():
    state = WizardState.from_form({})
    assert state.tool_name == ""
    assert state.tool_type_override is None
    assert state.data_checked == []
    assert state.mode is None
    assert state.automated_decisions is False
