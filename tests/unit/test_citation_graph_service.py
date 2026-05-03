from __future__ import annotations

import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.models.literature_graph import (
    LiteratureGraphProvenance,
    LiteraturePaper,
    PublicationCitationGraphRequest,
)
from pubtator_link.models.publication_metadata import PublicationMetadataResponse
from pubtator_link.services.citation_graph import CitationGraphService


class FakeCrossref:
    async def get_work(self, doi: str) -> dict[str, str]:
        assert doi == "10.1016/j.ard.2025.05.020"
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi="10.1000/primary-study",
                title="Primary trial",
                provenance=[
                    LiteratureGraphProvenance(
                        provider="crossref",
                        source_id=work["DOI"],
                    )
                ],
            )
        ]


class FakeEuropePmc:
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        assert pmid == "40562663"
        return [
            LiteraturePaper(
                pmid="40600001",
                doi="10.1000/citing-study",
                title="Citing study",
                status="resolved_full_text_candidate",
                provenance=[LiteratureGraphProvenance(provider="europe_pmc", source_id="40600001")],
            )
        ]


class FailingEuropePmc:
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        raise RuntimeError("Europe PMC unavailable")


class FakeDiscovery:
    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        return type("ArticleIdConversionResponse", (), {"records": []})()


class ResolvingDiscovery:
    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        assert ids == ["10.1016/j.ard.2025.05.020"]
        assert source == "doi"
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1016/j.ard.2025.05.020",
                        input_kind="doi",
                        status="resolved",
                        pmid="40562663",
                        doi="10.1016/j.ard.2025.05.020",
                    )
                ]
            },
        )()


class FakeMetadata:
    async def get_metadata(self, request):
        return PublicationMetadataResponse(metadata=[], failed_pmids={})


class RecordingMetadata:
    def __init__(self) -> None:
        self.called = False

    async def get_metadata(self, request):
        self.called = True
        return PublicationMetadataResponse(metadata=[], failed_pmids={})


@pytest.mark.asyncio
async def test_doi_references_direction_returns_crossref_references() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
        )
    )

    assert response.source.doi == "10.1016/j.ard.2025.05.020"
    assert response.references[0].doi == "10.1000/primary-study"
    assert response.references[0].provenance[0].provider == "crossref"
    assert response.candidate_pmids == []


@pytest.mark.asyncio
async def test_pmid_cited_by_direction_returns_europe_pmc_citations() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="cited_by")
    )

    assert response.source.pmid == "40562663"
    assert response.cited_by[0].pmid == "40600001"
    assert response.candidate_pmids == ["40600001"]


@pytest.mark.asyncio
async def test_both_direction_with_pmid_and_failing_europe_pmc_keeps_references_warning() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FailingEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="40562663",
            direction="both",
        )
    )

    assert any(
        warning.provider == "europe_pmc" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )


@pytest.mark.asyncio
async def test_doi_both_direction_reports_partial_identifier_resolution_warning() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
        )
    )

    assert any(
        warning.provider == "identifier_resolution"
        and warning.status == "partial_identifier_resolution"
        for warning in response.meta.warnings
    )
    assert not any(
        warning.provider == "europe_pmc" and warning.status == "provider_failed"
        for warning in response.meta.warnings
    )


@pytest.mark.asyncio
async def test_doi_both_direction_uses_resolved_pmid_for_cited_by() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
        )
    )

    assert response.source.pmid == "40562663"
    assert response.source.doi == "10.1016/j.ard.2025.05.020"
    assert response.cited_by[0].pmid == "40600001"
    assert not response.meta.warnings


@pytest.mark.asyncio
async def test_resolve_metadata_false_skips_metadata_lookup() -> None:
    metadata = RecordingMetadata()
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=metadata,
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="cited_by",
            resolve_metadata=False,
        )
    )

    assert response.source.pmid == "40562663"
    assert response.source.doi == "10.1016/j.ard.2025.05.020"
    assert response.cited_by[0].pmid == "40600001"
    assert metadata.called is False
