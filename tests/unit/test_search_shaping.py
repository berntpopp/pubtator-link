from pubtator_link.services.search_shaping import (
    selected_search_items,
    shaped_search_response,
    shaped_search_result,
)


def test_shaped_search_response_can_merge_basic_metadata() -> None:
    raw = {
        "query": "MEFV",
        "total": 1,
        "results": [{"pmid": "33454820", "title": "Title from search", "authors": []}],
    }
    metadata_by_pmid = {
        "33454820": {
            "pmid": "33454820",
            "authors": [
                {
                    "last_name": "Kavrul Kayaalp",
                    "initials": "GK",
                    "display_name": "Kavrul Kayaalp GK",
                }
            ],
            "journal": "Rheumatology International",
            "pub_year": 2022,
            "pub_date": "2022 Jan",
            "doi": "10.1007/s00296-020-04776-1",
            "pmcid": "PMC7811395",
            "publication_types": ["Journal Article"],
        }
    }

    shaped = shaped_search_response(
        raw=raw,
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="basic",
        metadata_by_pmid=metadata_by_pmid,
    )

    result = shaped.results[0]
    assert result.authors == []
    assert result.first_author_et_al == "Kavrul Kayaalp GK"
    assert result.journal == "Rheumatology International"
    assert result.pub_year == 2022
    assert result.pub_date == "2022 Jan"
    assert result.volume is None


def test_shaped_search_response_full_metadata_keeps_author_array() -> None:
    shaped = shaped_search_response(
        raw={"total": 1, "results": [{"pmid": "33454820", "title": "Title"}]},
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="full",
        metadata_by_pmid={
            "33454820": {
                "authors": [
                    {"display_name": "Kavrul Kayaalp GK"},
                    {"display_name": "Ozen S"},
                ],
            }
        },
    )

    result = shaped.results[0]
    assert [author.display_name for author in result.authors] == [
        "Kavrul Kayaalp GK",
        "Ozen S",
    ]
    assert result.first_author_et_al == "Kavrul Kayaalp GK et al."


def test_shaped_search_response_full_metadata_includes_mesh_and_citations() -> None:
    shaped = shaped_search_response(
        raw={"total": 1, "results": [{"pmid": "33454820", "title": "Title"}]},
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="full",
        metadata_by_pmid={
            "33454820": {
                "mesh_headings": ["Familial Mediterranean Fever"],
                "nlm_citation": "NLM",
                "bibtex": "@article{pmid33454820}",
            }
        },
    )

    result = shaped.results[0]
    assert result.mesh_headings == ["Familial Mediterranean Fever"]
    assert result.nlm_citation == "NLM"
    assert result.bibtex == "@article{pmid33454820}"


def test_shaped_search_result_includes_recommended_citation() -> None:
    shaped = shaped_search_response(
        raw={
            "total": 1,
            "results": [
                {
                    "pmid": "33454820",
                    "title": "Clinical and genetic findings in children with MEFV variants",
                    "journal": "Rheumatology International",
                    "date": "2022",
                    "doi": "10.1007/s00296-020-04776-1",
                    "authors": ["Kavrul Kayaalp GK", "Ozen S"],
                }
            ],
        },
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
    )

    assert (
        shaped.results[0].recommended_citation
        == "Kavrul Kayaalp GK et al. Clinical and genetic findings in children with "
        "MEFV variants. Rheumatology International. 2022. PMID:33454820. "
        "doi:10.1007/s00296-020-04776-1."
    )


def test_shaped_search_response_none_metadata_preserves_existing_values() -> None:
    shaped = shaped_search_response(
        raw={
            "total": 1,
            "results": [{"pmid": "33454820", "title": "Title", "journal": "Search Journal"}],
        },
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="compact",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="none",
        metadata_by_pmid={"33454820": {"journal": "Metadata Journal"}},
    )

    assert shaped.results[0].journal == "Search Journal"


def test_shaped_search_response_partial_metadata_preserves_existing_values() -> None:
    shaped = shaped_search_response(
        raw={
            "total": 1,
            "results": [
                {
                    "pmid": "33454820",
                    "title": "Title",
                    "journal": "Search Journal",
                    "authors": ["Search Author"],
                    "doi": "10.1000/search",
                }
            ],
        },
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="basic",
        metadata_by_pmid={"33454820": {"journal": None, "authors": [], "doi": None}},
    )

    result = shaped.results[0]
    assert result.journal == "Search Journal"
    assert [author.display_name for author in result.authors] == ["Search Author"]
    assert result.doi == "10.1000/search"


def test_search_result_authors_are_publication_author_shape() -> None:
    shaped = shaped_search_response(
        raw={
            "total": 1,
            "results": [
                {
                    "pmid": "1",
                    "title": "T",
                    "authors": [{"last_name": "Smith", "initials": "J"}],
                }
            ],
        },
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
    )

    assert shaped.results[0].authors[0].last_name == "Smith"
    assert shaped.results[0].authors[0].initials == "J"


def test_shaped_search_response_metadata_does_not_overwrite_search_values() -> None:
    shaped = shaped_search_response(
        raw={
            "total": 1,
            "results": [
                {
                    "pmid": "33454820",
                    "title": "Title",
                    "journal": "Search Journal",
                    "authors": ["Search Author"],
                    "pub_date": "2021 Dec",
                    "doi": "10.1000/search",
                    "pmcid": "PMCSEARCH",
                    "publication_types": ["Search Type"],
                }
            ],
        },
        query="MEFV",
        page=1,
        sort=None,
        filters=None,
        sections=None,
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        limit=None,
        guideline_boost=False,
        metadata="basic",
        metadata_by_pmid={
            "33454820": {
                "journal": "Metadata Journal",
                "authors": ["Metadata Author"],
                "pub_date": "2022 Jan",
                "doi": "10.1000/metadata",
                "pmcid": "PMCMETA",
                "publication_types": ["Metadata Type"],
            }
        },
    )

    result = shaped.results[0]
    assert result.journal == "Search Journal"
    assert [author.display_name for author in result.authors] == ["Search Author"]
    assert result.pub_date == "2021 Dec"
    assert result.doi == "10.1000/search"
    assert result.pmcid == "PMCSEARCH"
    assert result.publication_types == ["Search Type"]


def test_guideline_boost_prioritizes_named_consensus_guidelines() -> None:
    items = [
        {
            "pmid": "1",
            "title": "Familial Mediterranean fever review",
            "abstract": "General review of MEFV.",
            "publication_types": ["Review"],
        },
        {
            "pmid": "2",
            "title": "EULAR recommendations for the management of familial Mediterranean fever",
            "abstract": "Ozen 2016 consensus recommendations.",
            "publication_types": ["Practice Guideline"],
        },
    ]

    selected = selected_search_items(items, guideline_boost=True, limit=2)

    assert [item["pmid"] for item in selected] == ["2", "1"]


def test_guideline_boost_uses_title_signals_without_publication_types() -> None:
    items = [
        {
            "pmid": "1",
            "title": "Familial Mediterranean fever review",
            "abstract": "General review of MEFV.",
            "publication_types": [],
        },
        {
            "pmid": "2",
            "title": (
                "EULAR recommendations and systematic review for familial Mediterranean fever"
            ),
            "abstract": "Consensus guidance from SHARE and PRES.",
            "publication_types": [],
        },
    ]

    selected = selected_search_items(items, guideline_boost=True, limit=2)
    result = shaped_search_result(
        item=selected[0],
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        guideline_boost=True,
        metadata="none",
    )

    assert [item["pmid"] for item in selected] == ["2", "1"]
    assert "eular" in result.ranking_reasons
    assert "recommendation" in result.ranking_reasons
    assert "systematic review" in result.ranking_reasons


def test_guideline_rank_features_include_reasons() -> None:
    result = shaped_search_result(
        item={
            "pmid": "2",
            "title": "EULAR recommendations for FMF",
            "abstract": "Consensus guidance.",
            "publication_types": ["Practice Guideline"],
        },
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        guideline_boost=True,
        metadata="none",
    )

    assert result.rank_features is not None
    assert result.rank_features["guideline_boost"] > 0
    assert "practice guideline" in result.ranking_reasons
    assert "eular" in result.ranking_reasons
