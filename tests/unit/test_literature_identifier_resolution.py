from __future__ import annotations

import httpx
import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.models.literature_graph import LiteraturePaper
from pubtator_link.services.literature_identifier_resolution import DoiPmidResolver


class RecordingDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append((ids, source))
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1000/a",
                        input_kind="doi",
                        status="resolved",
                        pmid="100",
                        doi="10.1000/a",
                    ),
                    ArticleIdConversionRecord(
                        input_id="10.1000/b",
                        input_kind="doi",
                        status="unresolved",
                        doi="10.1000/b",
                    ),
                ]
            },
        )()


class NoMatchDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append((ids, source))
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id=doi,
                        input_kind="doi",
                        status="unresolved",
                        doi=doi,
                    )
                    for doi in ids
                ]
            },
        )()


class OpenAlexPmidLookup:
    def __init__(self, pmid: str | None) -> None:
        self.pmid = pmid
        self.calls: list[str] = []

    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        self.calls.append(doi)
        return LiteraturePaper(doi=doi, pmid=self.pmid)


class PubMedPmidLookup:
    def __init__(self, pmid: str | None) -> None:
        self.pmid = pmid
        self.calls: list[str] = []

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        self.calls.append(doi)
        return self.pmid


class FailingOpenAlexPmidLookup:
    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        raise RuntimeError("openalex unavailable")


class TimeoutOpenAlexPmidLookup:
    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        raise httpx.TimeoutException("openalex timed out")


@pytest.mark.asyncio
async def test_resolver_batches_caches_positive_and_negative_results() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    first = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)
    second = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)

    assert first.resolved == {"10.1000/a": "100"}
    assert first.unresolved == {"10.1000/b"}
    assert second.resolved == {"10.1000/a": "100"}
    assert second.cached_count == 2
    assert discovery.calls == [(["10.1000/a", "10.1000/b"], "doi")]


@pytest.mark.asyncio
async def test_resolver_respects_max_ids_and_reports_skipped() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    result = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=1)

    assert discovery.calls == [(["10.1000/a"], "doi")]
    assert result.skipped_count == 1


@pytest.mark.asyncio
async def test_resolver_falls_back_to_openalex_after_id_converter_no_match() -> None:
    discovery = NoMatchDiscovery()
    openalex = OpenAlexPmidLookup("26802180")
    pubmed = PubMedPmidLookup("999")
    resolver = DoiPmidResolver(
        discovery_service=discovery,
        openalex_service=openalex,
        pubmed_service=pubmed,
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.resolved == {"10.1136/annrheumdis-2015-208690": "26802180"}
    assert result.resolution_sources["10.1136/annrheumdis-2015-208690"] == "openalex"
    assert result.provider_result_counts["openalex"] == 1
    assert result.provider_no_match_counts["ncbi_idconv"] == 1
    assert discovery.calls == [(["10.1136/annrheumdis-2015-208690"], "doi")]
    assert openalex.calls == ["10.1136/annrheumdis-2015-208690"]
    assert pubmed.calls == []


@pytest.mark.asyncio
async def test_resolver_falls_back_to_pubmed_esearch_after_openalex_no_match() -> None:
    discovery = NoMatchDiscovery()
    openalex = OpenAlexPmidLookup(None)
    pubmed = PubMedPmidLookup("26802180")
    resolver = DoiPmidResolver(
        discovery_service=discovery,
        openalex_service=openalex,
        pubmed_service=pubmed,
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.resolved == {"10.1136/annrheumdis-2015-208690": "26802180"}
    assert result.resolution_sources["10.1136/annrheumdis-2015-208690"] == "pubmed_esearch"
    assert result.provider_result_counts["pubmed_esearch"] == 1
    assert result.provider_no_match_counts["ncbi_idconv"] == 1
    assert result.provider_no_match_counts["openalex"] == 1
    assert openalex.calls == ["10.1136/annrheumdis-2015-208690"]
    assert pubmed.calls == ["10.1136/annrheumdis-2015-208690"]


@pytest.mark.asyncio
async def test_resolver_reports_provider_specific_fallback_failures() -> None:
    resolver = DoiPmidResolver(
        discovery_service=NoMatchDiscovery(),
        openalex_service=FailingOpenAlexPmidLookup(),
        pubmed_service=PubMedPmidLookup(None),
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.unresolved == {"10.1136/annrheumdis-2015-208690"}
    assert result.provider_no_match_counts["ncbi_idconv"] == 1
    assert result.provider_failed_counts["openalex"] == 1
    assert result.provider_no_match_counts["pubmed_esearch"] == 1


@pytest.mark.asyncio
async def test_resolver_cached_unresolved_results_keep_provider_status_counts() -> None:
    resolver = DoiPmidResolver(
        discovery_service=NoMatchDiscovery(),
        openalex_service=OpenAlexPmidLookup(None),
        pubmed_service=PubMedPmidLookup(None),
    )

    first = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)
    second = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert first.provider_no_match_counts == {
        "ncbi_idconv": 1,
        "openalex": 1,
        "pubmed_esearch": 1,
    }
    assert second.unresolved == {"10.1136/annrheumdis-2015-208690"}
    assert second.cached_count == 1
    assert second.provider_no_match_counts == first.provider_no_match_counts


@pytest.mark.asyncio
async def test_resolver_counts_httpx_timeout_as_provider_timeout() -> None:
    resolver = DoiPmidResolver(
        discovery_service=NoMatchDiscovery(),
        openalex_service=TimeoutOpenAlexPmidLookup(),
        pubmed_service=PubMedPmidLookup(None),
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.provider_timeout_counts["openalex"] == 1
    assert result.provider_failed_counts.get("openalex", 0) == 0
    assert result.timeout_count == 1
