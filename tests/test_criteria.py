from policybot.criteria import ARP_CRITERIA, USAGE_CRITERIA


def test_arp_criteria_has_thirteen_unique_entries():
    assert len(ARP_CRITERIA) == 13
    names = [criterion for _, criterion, _ in ARP_CRITERIA]
    assert len(names) == len(set(names))


def test_arp_criteria_categories_match_document():
    categories = {category for category, _, _ in ARP_CRITERIA}
    assert categories == {
        "Souveraineté et hébergement des données",
        "Sécurité de l'information",
        "Conformité légale et contractuelle",
    }


def test_usage_criteria_has_eleven_unique_entries():
    assert len(USAGE_CRITERIA) == 11
    names = [criterion for _, criterion, _ in USAGE_CRITERIA]
    assert len(names) == len(set(names))


def test_usage_criteria_categories_match_document():
    categories = {category for category, _, _ in USAGE_CRITERIA}
    assert categories == {
        "Gestion des données",
        "Éthique et fiabilité des résultats",
        "Risques organisationnels",
    }


def test_every_entry_has_a_non_empty_description():
    for _, _, description in ARP_CRITERIA + USAGE_CRITERIA:
        assert description.strip()
