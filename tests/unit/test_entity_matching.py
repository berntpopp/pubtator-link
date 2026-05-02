from pubtator_link.services.entity_matching import synonyms_from_entity_item


def test_synonyms_from_entity_item_uses_upstream_and_match_text() -> None:
    item = {
        "synonyms": ["MEFV", "FMF gene", "MEFV"],
        "match": "Matched on synonyms <m>pyrin</m>, <m>marenostrin</m>",
    }

    assert synonyms_from_entity_item(item) == ["MEFV", "FMF gene", "pyrin", "marenostrin"]
