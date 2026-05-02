from pubtator_link.services.search_shaping import shaped_search_response


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
    assert result.authors[0].display_name == "Kavrul Kayaalp GK"
    assert result.journal == "Rheumatology International"
    assert result.pub_year == 2022
    assert result.pub_date == "2022 Jan"
    assert result.volume is None


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
