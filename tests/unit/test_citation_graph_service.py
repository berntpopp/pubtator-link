from __future__ import annotations

import asyncio

import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteratureGraphProvenance,
    LiteraturePaper,
    PublicationCitationGraphRequest,
)
from pubtator_link.models.publication_metadata import (
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)
from pubtator_link.services.citation_graph import CitationGraphService


def assert_no_prepare_mode(payload: object) -> None:
    assert "prepare_mode" not in str(payload)


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


class RawBibliographyCrossref:
    async def get_work(self, doi: str) -> dict[str, str]:
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi="10.1000/raw-reference",
                title=(
                    "Author A, Author B. Clean PubMed title for resolved reference. "
                    "Journal. 2020;1:1-2. https://doi.org/10.1000/raw-reference."
                ),
                provenance=[LiteratureGraphProvenance(provider="crossref", source_id=work["DOI"])],
            )
        ]


class LargeCrossref:
    async def get_work(self, doi: str) -> dict[str, str]:
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi=f"10.1000/large-{index}",
                title=f"Large reference {index} " + ("literature graph payload " * 40),
            )
            for index in range(25)
        ]


class MixedLargeCrossref:
    async def get_work(self, doi: str) -> dict[str, str]:
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                pmid=f"30{index}",
                doi=f"10.1000/reference-{index}",
                title=(
                    f"Familial Mediterranean fever colchicine reference {index}"
                    if index < 4
                    else f"Methodology reference {index} " + ("risk of bias reporting " * 30)
                ),
                year=2020 + (index % 5),
            )
            for index in range(20)
        ]


class LargeEuropePmc:
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                pmid=f"40{index}",
                doi=f"10.1000/cited-by-{index}",
                title=(
                    f"EULAR familial Mediterranean fever update citing paper {index}"
                    if index < 4
                    else f"Broad immunology citing paper {index} "
                    + ("long compact payload text " * 30)
                ),
                year=2021 + (index % 4),
            )
            for index in range(min(limit, 20))
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


class ProviderStartBarrier:
    def __init__(self, expected: int) -> None:
        self.expected = expected
        self.started: list[str] = []
        self.release = asyncio.Event()

    async def arrive(self, name: str) -> None:
        self.started.append(name)
        if len(self.started) >= self.expected:
            self.release.set()
        await self.release.wait()


class CoordinatedCrossref:
    def __init__(self, barrier: ProviderStartBarrier) -> None:
        self.barrier = barrier

    async def get_work(self, doi: str) -> dict[str, str]:
        await self.barrier.arrive("crossref_references")
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi="10.1000/coordinated-crossref-reference",
                title="Coordinated Crossref reference",
                provenance=[LiteratureGraphProvenance(provider="crossref", source_id=work["DOI"])],
            )
        ]


class CoordinatedOpenAlex:
    def __init__(self, barrier: ProviderStartBarrier) -> None:
        self.barrier = barrier

    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        return LiteraturePaper(doi=doi, pmid="40562663")

    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        await self.barrier.arrive("openalex_references")
        return [
            LiteraturePaper(
                doi="10.1000/coordinated-openalex-reference",
                title="Coordinated OpenAlex reference",
                provenance=[LiteratureGraphProvenance(provider="openalex", source_id=doi)],
            )
        ][:limit]

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        await self.barrier.arrive("openalex_cited_by")
        return [
            LiteraturePaper(
                pmid="40600002",
                doi="10.1000/coordinated-openalex-citing",
                title="Coordinated OpenAlex citing paper",
                provenance=[LiteratureGraphProvenance(provider="openalex", source_id=doi)],
            )
        ][:limit]


class CoordinatedEuropePmc:
    def __init__(self, barrier: ProviderStartBarrier) -> None:
        self.barrier = barrier

    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        await self.barrier.arrive("europe_pmc_cited_by")
        return [
            LiteraturePaper(
                pmid="40600001",
                doi="10.1000/coordinated-europe-pmc-citing",
                title="Coordinated Europe PMC citing paper",
                provenance=[LiteratureGraphProvenance(provider="europe_pmc", source_id=pmid)],
            )
        ][:limit]


class EularOpenAlexFallback:
    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        assert doi == "10.1136/annrheumdis-2015-208690"
        return LiteraturePaper(doi=doi, pmid="26802180")

    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        return []

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        return []


class FakeUnpaywall:
    async def get_oa_status(self, doi: str):
        assert doi in {"10.1000/primary-study", "10.1000/openalex-citing"}
        return LiteratureAvailability(
            is_open_access=True,
            full_text_url=f"https://example.org/{doi}",
            oa_status="green",
        )


class ManyDoiCrossref:
    async def get_work(self, doi: str) -> dict[str, str]:
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, str]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi=f"10.1000/open-access-{index}",
                title=f"Open access candidate {index}",
                provenance=[LiteratureGraphProvenance(provider="crossref", source_id=work["DOI"])],
            )
            for index in range(5)
        ]


class GatedUnpaywall:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self.release = asyncio.Event()

    async def get_oa_status(self, doi: str):
        self.calls.append(doi)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if len(self.calls) >= 3:
            self.release.set()
        await self.release.wait()
        await asyncio.sleep(0)
        self.in_flight -= 1
        return LiteratureAvailability(
            is_open_access=True,
            full_text_url=f"https://example.org/{doi}",
            oa_status="green",
        )


class FakeDiscovery:
    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        return type("ArticleIdConversionResponse", (), {"records": []})()

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return None


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

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return None


class ReferenceResolvingDiscovery:
    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        records = []
        for doi in ids:
            pmid = {
                "10.1016/j.ard.2025.05.020": "40562663",
                "10.1000/raw-reference": "999999",
            }.get(doi)
            if pmid is None:
                continue
            records.append(
                ArticleIdConversionRecord(
                    input_id=doi,
                    input_kind="doi",
                    status="resolved",
                    pmid=pmid,
                    doi=doi,
                )
            )
        return type("ArticleIdConversionResponse", (), {"records": records})()

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return {
            "10.1016/j.ard.2025.05.020": "40562663",
            "10.1000/raw-reference": "999999",
        }.get(doi)


class FakeMetadata:
    async def get_metadata(self, request):
        return PublicationMetadataResponse(metadata=[], failed_pmids={})


class MetadataForResolvedReferences:
    async def get_metadata(self, request):
        from pubtator_link.models.publication_metadata import PublicationMetadata

        records = {
            "40562663": PublicationMetadata(
                pmid="40562663",
                doi="10.1016/j.ard.2025.05.020",
                title="Source article",
                pub_year=2025,
            ),
            "999999": PublicationMetadata(
                pmid="999999",
                doi="10.1000/raw-reference",
                title="Clean PubMed title for resolved reference",
                journal="Journal",
                pub_year=2020,
                coverage="abstract_only",
            ),
        }
        return PublicationMetadataResponse(
            metadata=[records[pmid] for pmid in request.pmids if pmid in records],
            failed_pmids={},
        )


class MetadataWithSourceDoi:
    async def get_metadata(self, request):
        from pubtator_link.models.publication_metadata import PublicationMetadata

        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=request.pmids[0],
                    doi="10.1016/j.ard.2025.05.020",
                    title="EULAR/PReS familial Mediterranean fever recommendations",
                    journal="Annals of the Rheumatic Diseases",
                    pub_year=2025,
                )
            ],
            failed_pmids={},
        )


class MetadataWithPmcid:
    async def get_metadata(self, request):
        from pubtator_link.models.publication_metadata import PublicationMetadata

        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid="28386255",
                    doi="10.3389/fimmu.2017.00253",
                    pmcid="PMC5362626",
                    title="Familial Mediterranean Fever",
                    journal="Frontiers in Immunology",
                    pub_year=2017,
                    coverage="full_text",
                )
            ],
            failed_pmids={},
        )


class RecordingMetadata:
    def __init__(self) -> None:
        self.called = False

    async def get_metadata(self, request):
        self.called = True
        return PublicationMetadataResponse(metadata=[], failed_pmids={})


@pytest.mark.asyncio
async def test_citation_graph_metadata_resolution_remains_single_pmid_public_request() -> None:
    from pubtator_link.models.publication_metadata import PublicationMetadata

    class SinglePmidMetadata:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def get_metadata(self, request):
            self.requests.append(request)
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="28386255",
                        title="Fake service metadata title",
                    )
                ],
                failed_pmids={},
            )

    metadata = SinglePmidMetadata()
    service = CitationGraphService(metadata_service=metadata)

    result = await service._metadata_for_pmid("28386255")

    assert result is not None
    assert result.pmid == "28386255"
    assert result.title == "Fake service metadata title"
    assert len(metadata.requests) == 1
    request = metadata.requests[0]
    assert isinstance(request, PublicationMetadataRequest)
    assert request.pmids == ["28386255"]
    assert request.include_mesh is False
    assert request.include_publication_types is True
    assert request.include_citations == "none"
    assert request.include_coverage is True


@pytest.mark.asyncio
async def test_citation_graph_resolved_references_prefer_pubmed_titles() -> None:
    service = CitationGraphService(
        crossref=RawBibliographyCrossref(),
        discovery_service=ReferenceResolvingDiscovery(),
        metadata_service=MetadataForResolvedReferences(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="40562663",
            direction="references",
            max_results=5,
        )
    )

    assert response.references[0].pmid == "999999"
    assert response.references[0].title == "Clean PubMed title for resolved reference"
    assert "Author A" not in (response.references[0].title or "")


@pytest.mark.asyncio
async def test_citation_graph_exposes_top_level_timed_provider_status() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        metadata_service=MetadataWithSourceDoi(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="references")
    )

    assert response.provider_status == response.meta.provider_status
    crossref_status = next(
        status
        for status in response.provider_status
        if status.provider == "crossref" and status.operation == "references"
    )
    assert crossref_status.elapsed_ms is not None


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

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return None


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
async def test_citation_graph_source_uses_shared_metadata_availability() -> None:
    service = CitationGraphService(
        discovery_service=FakeDiscovery(),
        metadata_service=MetadataWithPmcid(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="28386255",
            direction="cited_by",
            response_mode="compact",
        )
    )

    assert response.source.pmcid == "PMC5362626"
    assert response.source.availability.has_pmc_full_text is True
    assert response.source.availability.is_open_access is False


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
async def test_pmid_cited_by_status_keeps_europe_pmc_before_openalex_skip() -> None:
    service = CitationGraphService(
        europe_pmc=FakeEuropePmc(),
        openalex=FakeOpenAlex(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="cited_by")
    )

    assert [(status.provider, status.status) for status in response.cited_by_status] == [
        ("europe_pmc", "success"),
        ("openalex", "skipped"),
    ]


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
async def test_citation_graph_resolves_eular_doi_with_openalex_fallback() -> None:
    service = CitationGraphService(
        openalex=EularOpenAlexFallback(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1136/annrheumdis-2015-208690",
            direction="cited_by",
            resolve_metadata=False,
        )
    )

    assert response.source.pmid == "26802180"
    assert response.source.doi == "10.1136/annrheumdis-2015-208690"
    assert any(
        status.provider == "openalex"
        and status.operation == "doi_to_pmid"
        and status.status == "success"
        and status.result_count == 1
        for status in response.identifier_resolution_status
    )


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


@pytest.mark.asyncio
async def test_citation_graph_runs_independent_provider_lanes_concurrently() -> None:
    barrier = ProviderStartBarrier(expected=4)
    service = CitationGraphService(
        crossref=CoordinatedCrossref(barrier),
        europe_pmc=CoordinatedEuropePmc(barrier),
        openalex=CoordinatedOpenAlex(barrier),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await asyncio.wait_for(
        service.get_citation_graph(
            PublicationCitationGraphRequest(
                doi="10.1016/j.ard.2025.05.020",
                direction="both",
                resolve_metadata=False,
                resolve_reference_pmids=False,
                include_open_access_status=False,
            )
        ),
        timeout=0.5,
    )

    assert barrier.started == [
        "crossref_references",
        "openalex_references",
        "europe_pmc_cited_by",
        "openalex_cited_by",
    ]
    assert [status.status for status in response.references_status] == ["success", "success"]
    assert [status.status for status in response.cited_by_status] == ["success", "success"]
    assert [paper.doi for paper in response.references] == [
        "10.1000/coordinated-crossref-reference",
        "10.1000/coordinated-openalex-reference",
    ]
    assert response.candidate_pmids == ["40600001", "40600002"]


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
async def test_open_access_enrichment_uses_bounded_concurrency() -> None:
    unpaywall = GatedUnpaywall()
    service = CitationGraphService(
        crossref=ManyDoiCrossref(),
        unpaywall=unpaywall,
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await asyncio.wait_for(
        service.get_citation_graph(
            PublicationCitationGraphRequest(
                doi="10.1016/j.ard.2025.05.020",
                direction="references",
                include_open_access_status=True,
                resolve_reference_pmids=False,
                max_results=5,
            )
        ),
        timeout=0.5,
    )

    assert len(unpaywall.calls) == 5
    assert unpaywall.max_in_flight == 3
    assert all(paper.availability.is_open_access for paper in response.references)
    assert response.open_access_status[0].result_count == 5


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


class NoMatchUnpaywall:
    async def get_oa_status(self, doi: str):
        from pubtator_link.models.literature_graph import ProviderWarning

        return ProviderWarning(
            provider="unpaywall",
            status="provider_no_match",
            retryable=False,
            message="No Unpaywall record for DOI.",
        )


@pytest.mark.asyncio
async def test_citation_graph_treats_unpaywall_no_match_as_empty_status() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=None,
        unpaywall=NoMatchUnpaywall(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
        )
    )

    assert response.meta.warnings == []
    assert response.open_access_status[0].provider == "unpaywall"
    assert response.open_access_status[0].status == "empty"


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
    serialized = response.model_dump(by_alias=True)
    assert "references" not in serialized
    assert "cited_by" not in serialized
    assert response.reference_candidates == []
    assert response.cited_by_candidates
    assert response.candidate_pmids == ["40600001"]
    assert response.actionable_pmid_count == len(response.candidate_pmids)
    assert response.metadata_only_count == 3
    assert response.unresolved_doi_count == 2
    assert response.compact_status["references"] == "candidates_only"
    assert response.compact_status["cited_by"] == "candidates_only"
    assert_no_prepare_mode(response.meta.next_commands)
    assert any(status.operation == "references" for status in response.references_status)
    assert any(status.operation == "cited_by" for status in response.cited_by_status)
    assert len([s for s in response.open_access_status if s.provider == "unpaywall"]) == 1
    unpaywall_warnings = [
        warning for warning in response.meta.warnings if warning.provider == "unpaywall"
    ]
    assert len(unpaywall_warnings) == 1
    assert "repeated" in unpaywall_warnings[0].message


@pytest.mark.asyncio
async def test_citation_graph_compact_hides_unresolved_doi_candidate_rows() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
            resolve_reference_pmids=False,
        )
    )

    assert response.unresolved_doi_count == 1
    assert response.reference_candidates == []
    assert response.meta.omitted_counts["doi_only_unresolved"] == 1


@pytest.mark.asyncio
async def test_citation_graph_compact_populates_cache_snapshot_and_versions() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
        )
    )

    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert response.meta.snapshot_date is not None
    assert response.meta.source_versions["payload_contract"] == (
        "literature_graph_payload_controls_v1"
    )
    assert response.meta.source_versions["pubmed"] == "live"
    assert response.meta.source_versions["crossref"] == "live"
    assert any(
        command["arguments"]["response_mode"] == "full" for command in response.meta.next_commands
    )
    assert any(
        command["arguments"]["response_mode"] == "nodes_edges"
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_citation_graph_compact_reports_budget_truncation() -> None:
    service = CitationGraphService(
        crossref=LargeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
            resolve_reference_pmids=False,
            max_results=25,
        )
    )

    assert response.meta.truncated is True
    assert response.meta.budget_advice is not None
    assert response.meta.omitted_counts
    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature


@pytest.mark.asyncio
async def test_citation_graph_compact_preserves_cited_by_stubs_under_budget_pressure() -> None:
    service = CitationGraphService(
        crossref=MixedLargeCrossref(),
        europe_pmc=LargeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=MetadataWithSourceDoi(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="40562663",
            direction="both",
            response_mode="compact",
            max_results=20,
            resolve_reference_pmids=False,
        )
    )

    assert response.meta.truncated is True
    assert len(response.cited_by_candidates) >= 3
    assert response.cited_by_top_pmids[:3] == [
        candidate.pmid for candidate in response.cited_by_candidates[:3]
    ]
    assert response.reference_top_pmids


@pytest.mark.asyncio
async def test_citation_graph_compact_exposes_hidden_lane_counts_and_samples() -> None:
    service = CitationGraphService(
        crossref=MixedLargeCrossref(),
        europe_pmc=LargeEuropePmc(),
        metadata_service=MetadataWithSourceDoi(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="40562663",
            direction="both",
            response_mode="compact",
            max_results=20,
            query="familial Mediterranean fever",
        )
    )

    assert response.reference_pmid_count == 20
    assert response.cited_by_pmid_count == 20
    assert response.reference_sample_pmids[:3] == ["300", "301", "302"]
    assert response.cited_by_sample_pmids[:3] == ["400", "401", "402"]


@pytest.mark.asyncio
async def test_citation_graph_scores_candidates_against_query() -> None:
    service = CitationGraphService(
        crossref=MixedLargeCrossref(),
        europe_pmc=LargeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=MetadataWithSourceDoi(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="40562663",
            direction="both",
            response_mode="compact",
            max_results=8,
            resolve_reference_pmids=False,
            query="familial Mediterranean fever colchicine guideline",
        )
    )

    candidates = [*response.reference_candidates, *response.cited_by_candidates]
    assert candidates
    assert all(candidate.score is not None for candidate in candidates)
    assert all(candidate.relevance_to_query is not None for candidate in candidates)
    assert "query_term_overlap" in candidates[0].rank_reasons


@pytest.mark.asyncio
async def test_citation_graph_compact_status_marks_unrequested_direction() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
        )
    )

    assert response.reference_candidates == []
    assert response.cited_by_candidates == []
    assert response.compact_status["references"] == "candidates_only"
    assert response.compact_status["cited_by"] == "not_requested"
    assert response.meta.omitted_counts["doi_only_unresolved"] == 1


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
async def test_citation_graph_nodes_edges_returns_topology_without_full_arrays() -> None:
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
            response_mode="nodes_edges",
        )
    )

    assert response.meta.response_mode == "nodes_edges"
    assert response.references == []
    assert response.cited_by == []
    assert response.metadata_only == []
    assert response.reference_candidates == []
    assert response.cited_by_candidates == []
    assert response.nodes
    assert response.edges


@pytest.mark.asyncio
async def test_citation_graph_full_computes_response_size_class() -> None:
    service = CitationGraphService(
        crossref=LargeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="full",
            max_results=50,
            resolve_reference_pmids=False,
        )
    )

    assert response.meta.response_size_class in {"medium", "large"}


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
