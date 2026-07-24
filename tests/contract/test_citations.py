from policybot.contract.citations import build_deep_link, validated_citation


def test_valid_offsets_extract_and_anchor_the_page_quote():
    text = "Avant. La donnée reste chiffrée en transit et au repos. Après."
    begin = text.index("La donnée")
    end = text.index(". Après")
    citation = validated_citation(
        url="https://vendor.test/security",
        title="Security",
        page_text=text,
        quote_text=text[begin:end],
        begin=begin,
        end=end,
    )
    assert citation is not None
    assert citation.anchored is True
    assert citation.begin == begin
    assert ":~:text=" in citation.deep_link


def test_incoherent_offsets_are_recomputed_from_verbatim_quote():
    text = "Le fournisseur publie un plan de réponse aux incidents."
    citation = validated_citation(
        url="https://vendor.test/security",
        title="",
        page_text=text,
        quote_text="un plan de réponse aux incidents",
        begin=999,
        end=1000,
    )
    assert citation is not None
    assert text[citation.begin:citation.end] == "un plan de réponse aux incidents"


def test_unanchored_quote_is_rejected():
    assert validated_citation(
        url="https://vendor.test",
        title="",
        page_text="Texte de la page.",
        quote_text="Texte inventé.",
    ) is None


def test_long_quote_uses_start_and_end_anchors():
    link = build_deep_link(
        "https://vendor.test/page",
        "un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze",
    )
    assert link.startswith("https://vendor.test/page#:~:text=")
    assert "," in link
