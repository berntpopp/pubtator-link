from __future__ import annotations

import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
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


class FakeOpenAlex:
    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        assert doi == "10.1016/j.ard.2025.05.020"
        return [
            LiteraturePaper(
                openalex_id="https://openalex.org/W999",
                title="OpenAlex reference",
                provenance=[LiteratureGraphProvenance(provider="openalex", source_id=doi)],
            )
        ][:limit]

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        assert doi == "10.1016/j.ard.2025.05.020"
        return [
            LiteraturePaper(
                doi="10.1000/openalex-citing",
                title="OpenAlex citing paper",
                provenance=[LiteratureGraphProvenance(provider="openalex", source_id=doi)],
            )
        ][:limit]


class FakeUnpaywall:
    async def get_oa_status(self, doi: str):
        assert doi in {"10.1000/primary-study", "10.1000/openalex-citing"}
        return LiteratureAvailability(
            is_open_access=True,
            full_text_url=f"https://example.org/{doi}",
            oa_status="green",
        )


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


class BatchResolvingDiscovery:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append(ids)
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1000/primary-study",
                        input_kind="doi",
                        status="resolved",
                        pmid="30000001",
                        doi="10.1000/primary-study",
                    )
                ]
            },
        )()


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
async def test_doi_references_direction_reports_empty_identifier_resolution_status() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
        )
    )

    assert any(
        status.provider == "identifier_resolution"
        and status.operation == "doi_to_pmid"
        and status.status == "empty"
        for status in response.identifier_resolution_status
    )


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
async def test_pmid_references_direction_reports_doi_required_reference_providers_skipped() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        openalex=FakeOpenAlex(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="references")
    )

    skipped = [
        status
        for status in response.references_status
        if status.operation == "references" and status.status == "skipped"
    ]

    assert {(status.provider, status.message) for status in skipped} == {
        ("crossref", "DOI required"),
        ("openalex", "DOI required"),
    }


@pytest.mark.asyncio
async def test_pmid_cited_by_direction_reports_openalex_doi_required_skipped() -> None:
    service = CitationGraphService(
        europe_pmc=FakeEuropePmc(),
        openalex=FakeOpenAlex(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="cited_by")
    )

    assert any(
        status.provider == "openalex"
        and status.operation == "cited_by"
        and status.status == "skipped"
        and status.message == "DOI required"
        for status in response.cited_by_status
    )


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


@pytest.mark.asyncio
async def test_openalex_fallback_and_unpaywall_enrichment_are_wired() -> None:
    service = CitationGraphService(
        crossref=None,
        europe_pmc=None,
        openalex=FakeOpenAlex(),
        unpaywall=FakeUnpaywall(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
            include_open_access_status=True,
        )
    )

    assert response.references[0].openalex_id == "https://openalex.org/W999"
    assert response.cited_by[0].doi == "10.1000/openalex-citing"
    assert response.cited_by[0].availability.is_open_access is True
    assert response.cited_by[0].status == "resolved_full_text_candidate"


class CountingUnpaywall:
    async def get_oa_status(self, doi: str):
        return LiteratureAvailability(
            is_open_access=True,
            full_text_url=f"https://example.org/{doi}",
            oa_status="green",
        )


@pytest.mark.asyncio
async def test_open_access_status_counts_multiple_successful_unpaywall_lookups() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        openalex=FakeOpenAlex(),
        unpaywall=CountingUnpaywall(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
            include_open_access_status=True,
        )
    )

    unpaywall_status = [
        status
        for status in response.open_access_status
        if status.provider == "unpaywall"
        and status.operation == "open_access"
        and status.status == "success"
    ]

    assert len(unpaywall_status) == 1
    assert unpaywall_status[0].result_count == 3


@pytest.mark.asyncio
async def test_include_open_access_status_false_skips_unpaywall() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=None,
        unpaywall=FakeUnpaywall(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            include_open_access_status=False,
        )
    )

    assert response.references[0].availability.is_open_access is False


class DisabledUnpaywall:
    async def get_oa_status(self, doi: str):
        from pubtator_link.models.literature_graph import ProviderWarning

        return ProviderWarning(
            provider="unpaywall",
            status="provider_disabled",
            retryable=False,
            message="UNPAYWALL_EMAIL is not configured.",
        )


@pytest.mark.asyncio
async def test_citation_graph_compact_returns_candidates_status_and_no_metadata_duplicates() -> (
    None
):
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        openalex=FakeOpenAlex(),
        unpaywall=DisabledUnpaywall(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
            response_mode="compact",
        )
    )

    assert response.meta.response_mode == "compact"
    assert response.references == []
    assert response.cited_by == []
    assert response.metadata_only == []
    assert response.reference_candidates
    assert response.cited_by_candidates
    assert response.candidate_pmids == ["40600001"]
    assert any(status.operation == "references" for status in response.references_status)
    assert any(status.operation == "cited_by" for status in response.cited_by_status)
    assert len([s for s in response.open_access_status if s.provider == "unpaywall"]) == 1


@pytest.mark.asyncio
async def test_citation_graph_full_preserves_existing_arrays() -> None:
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
            response_mode="full",
        )
    )

    assert response.references
    assert response.cited_by
    assert response.meta.response_mode == "full"


@pytest.mark.asyncio
async def test_citation_graph_batches_reference_doi_resolution() -> None:
    discovery = BatchResolvingDiscovery()
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=discovery,
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
            resolve_reference_pmids=True,
            max_reference_resolution=20,
        )
    )

    assert discovery.calls == [["10.1016/j.ard.2025.05.020"], ["10.1000/primary-study"]]
    assert response.reference_candidates[0].pmid == "30000001"
    assert "resolved_pmid_from_doi" in response.reference_candidates[0].rank_reasons
    assert any(
        status.operation == "doi_to_pmid" for status in response.identifier_resolution_status
    )
