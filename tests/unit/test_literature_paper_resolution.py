from __future__ import annotations

from pubtator_link.models.literature_graph import LiteratureAvailability, LiteraturePaper
from pubtator_link.models.publication_metadata import PublicationAuthor, PublicationMetadata
from pubtator_link.services.literature_paper_resolution import (
    merge_literature_availability,
    paper_from_publication_metadata,
)


def test_pmcid_means_pmc_full_text_but_not_open_access_by_itself() -> None:
    metadata = PublicationMetadata(
        pmid="28386255",
        doi="10.3389/fimmu.2017.00253",
        pmcid="PMC5362626",
        title="Familial Mediterranean Fever",
        journal="Frontiers in Immunology",
        pub_year=2017,
        publication_types=["Review"],
        authors=[PublicationAuthor(last_name="Ozen", initials="S")],
        coverage="full_text",
    )

    paper = paper_from_publication_metadata(metadata, include_authors=True)

    assert paper.pmid == "28386255"
    assert paper.pmcid == "PMC5362626"
    assert paper.availability.has_pmc_full_text is True
    assert paper.availability.is_open_access is False
    assert paper.status == "resolved_full_text_candidate"
    assert paper.authors[0].name == "Ozen S"


def test_open_access_requires_explicit_availability_signal() -> None:
    metadata = PublicationMetadata(
        pmid="26802180",
        doi="10.1136/annrheumdis-2015-208690",
        title="EULAR recommendations for the management of familial Mediterranean fever",
        coverage="abstract_only",
    )
    explicit_oa = LiteratureAvailability(
        is_open_access=True,
        oa_status="bronze",
        full_text_url="https://example.org/eular",
    )

    paper = paper_from_publication_metadata(metadata, availability=explicit_oa)

    assert paper.availability.has_pmc_full_text is False
    assert paper.availability.is_open_access is True
    assert paper.availability.oa_status == "bronze"
    assert paper.status == "resolved_full_text_candidate"


def test_availability_merge_preserves_pmc_and_explicit_oa_independently() -> None:
    merged = merge_literature_availability(
        LiteraturePaper(
            pmid="1",
            pmcid="PMC1",
            availability=LiteratureAvailability(has_pmc_full_text=True),
        ),
        LiteraturePaper(
            pmid="1",
            availability=LiteratureAvailability(
                is_open_access=True,
                oa_status="green",
                license_or_access_hint="cc-by",
            ),
        ),
    )

    assert merged.availability.has_pmc_full_text is True
    assert merged.availability.is_open_access is True
    assert merged.availability.oa_status == "green"
    assert merged.availability.license_or_access_hint == "cc-by"
