import pytest
from pydantic import ValidationError

from pubtator_link.models.publication_metadata import (
    PublicationAuthor,
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)


def test_publication_metadata_accepts_complete_citation_fields() -> None:
    metadata = PublicationMetadata(
        pmid="33454820",
        title="Adherence to best practice consensus guidelines for familial Mediterranean fever",
        journal="Rheumatology International",
        pub_year=2022,
        pub_date="2022 Jan",
        volume="42",
        issue="1",
        pages="87-94",
        doi="10.1007/s00296-020-04776-1",
        pmcid="PMC7811395",
        authors=[
            PublicationAuthor(
                last_name="Kavrul Kayaalp",
                fore_name="Gul",
                initials="GK",
                collective_name=None,
            )
        ],
        publication_types=["Journal Article"],
        mesh_headings=["Familial Mediterranean Fever"],
        nlm_citation="Kavrul Kayaalp G. Rheumatol Int. 2022;42(1):87-94.",
        bibtex="@article{pmid33454820,title={Adherence to best practice consensus guidelines for familial Mediterranean fever}}",
        coverage="full_text",
        coverage_reason="pmc_oa_bioc",
    )

    assert metadata.authors[0].display_name == "Kavrul Kayaalp GK"
    assert metadata.vancouver_author_string == "Kavrul Kayaalp GK"
    assert metadata.citation_key == "PMID:33454820"


def test_publication_metadata_request_normalizes_pmids() -> None:
    request = PublicationMetadataRequest(
        pmids=[" PMID:33454820 ", " ", "33726481", "33454820"],
        include_mesh=True,
    )

    assert request.pmids == ["33454820", "33726481"]
    assert request.include_mesh is True
    assert request.include_publication_types is True
    assert request.include_citations == "both"
    assert request.include_coverage is True


def test_publication_metadata_response_preserves_failed_pmids() -> None:
    response = PublicationMetadataResponse(
        success=True,
        metadata=[],
        failed_pmids={"0": "invalid PMID"},
        _meta={"next_commands": []},
    )

    assert response.failed_pmids == {"0": "invalid PMID"}


def test_publication_metadata_response_serializes_meta_alias() -> None:
    response = PublicationMetadataResponse(
        metadata=[],
        _meta={"next_commands": []},
    )

    dumped = response.model_dump(by_alias=True)

    assert dumped["_meta"] == {"next_commands": []}
    assert "meta" not in dumped


def test_publication_metadata_rejects_blank_normalized_pmid() -> None:
    with pytest.raises(ValidationError):
        PublicationMetadata(pmid="PMID: ")


def test_vancouver_author_string_limits_authors_and_appends_et_al() -> None:
    metadata = PublicationMetadata(
        pmid="33454820",
        authors=[
            PublicationAuthor(last_name=f"Author{index}", initials=f"A{index}")
            for index in range(1, 8)
        ],
    )

    assert metadata.vancouver_author_string == (
        "Author1 A1, Author2 A2, Author3 A3, Author4 A4, Author5 A5, Author6 A6, et al"
    )


def test_publication_metadata_request_rejects_too_many_pmids() -> None:
    with pytest.raises(ValidationError):
        PublicationMetadataRequest(pmids=[str(index) for index in range(101)])


def test_publication_metadata_request_rejects_only_blank_pmids() -> None:
    with pytest.raises(ValidationError):
        PublicationMetadataRequest(pmids=[" ", "PMID:  "])


def test_publication_metadata_request_rejects_nonnumeric_pmids() -> None:
    with pytest.raises(ValidationError):
        PublicationMetadataRequest(pmids=["not-a-pmid"])


def test_publication_author_display_name_fallbacks() -> None:
    assert (
        PublicationAuthor(
            last_name="Ignored",
            initials="IG",
            fore_name="Ignored Fore",
            collective_name="Study Group",
        ).display_name
        == "Study Group"
    )
    assert PublicationAuthor(last_name="Smith", fore_name="Jane").display_name == "Smith"
    assert PublicationAuthor(fore_name="Jane").display_name == "Jane"


def test_review_rerag_exports_coverage_tier_alias() -> None:
    from pubtator_link.models.review_rerag import CoverageTier, SourceCoverage

    assert CoverageTier == SourceCoverage


def test_publication_metadata_coverage_reason_allows_plan_values_and_none() -> None:
    assert PublicationMetadata(pmid="33454820", coverage_reason="pmc_oa_bioc").coverage_reason == (
        "pmc_oa_bioc"
    )
    assert PublicationMetadata(pmid="33454820", coverage_reason=None).coverage_reason is None


def test_publication_metadata_rejects_unknown_coverage_reason() -> None:
    with pytest.raises(ValidationError):
        PublicationMetadata.model_validate(
            {"pmid": "33454820", "coverage_reason": "arbitrary_reason"}
        )
