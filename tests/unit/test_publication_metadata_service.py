from typing import Literal

import httpx
import pytest

from pubtator_link.models.publication_metadata import (
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)
from pubtator_link.models.review_rerag import CoverageReason, CoverageTier
from pubtator_link.services.publication_metadata import (
    NcbiPublicationMetadataClient,
    PublicationMetadataService,
)

PMID = "33454820"
TITLE = "Adherence to best practice consensus guidelines for familial Mediterranean fever"
JOURNAL = "Rheumatology International"
DOI = "10.1007/s00296-020-04776-1"
PMCID = "PMC7811395"


def _esummary_json() -> dict[str, object]:
    return {
        "result": {
            "uids": [PMID],
            PMID: {
                "uid": PMID,
                "title": TITLE,
                "fulljournalname": JOURNAL,
                "pubdate": "2022 Jan",
                "epubdate": "",
                "sortpubdate": "2022/01/01 00:00",
                "volume": "42",
                "issue": "1",
                "pages": "87-94",
                "articleids": [
                    {"idtype": "doi", "value": DOI},
                    {"idtype": "pmc", "value": PMCID},
                ],
                "authors": [
                    {
                        "name": "Kavrul Kayaalp G",
                        "authtype": "Author",
                        "clusterid": "",
                    }
                ],
                "pubtype": ["Journal Article"],
            },
        }
    }


def _mesh_xml() -> str:
    return (
        "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
        f"<PMID>{PMID}</PMID>"
        "<MeshHeadingList><MeshHeading><DescriptorName>"
        "Familial Mediterranean Fever"
        "</DescriptorName></MeshHeading></MeshHeadingList>"
        "</MedlineCitation></PubmedArticle></PubmedArticleSet>"
    )


def _successful_handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "esummary.fcgi" in url:
        return httpx.Response(200, json=_esummary_json())
    if "efetch.fcgi" in url:
        return httpx.Response(200, text=_mesh_xml())
    return httpx.Response(404)


async def _fetch_metadata(
    *,
    include_mesh: bool = False,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both",
) -> PublicationMetadataResponse:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_successful_handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)
        return await service.get_metadata(
            PublicationMetadataRequest(
                pmids=[PMID],
                include_mesh=include_mesh,
                include_citations=include_citations,
            )
        )


@pytest.mark.asyncio
async def test_publication_metadata_service_parses_esummary_and_mesh() -> None:
    response = await _fetch_metadata(include_mesh=True, include_citations="both")
    metadata = response.metadata[0]

    assert response.success is True
    assert response.failed_pmids == {}
    assert response.meta["next_commands"] == [
        "Use pubtator.get_publication_passages for citable passage text.",
        "Use pubtator.index_review_evidence after selecting the final PMID corpus.",
    ]
    assert metadata.authors[0].display_name == "Kavrul Kayaalp G"
    assert metadata.journal == JOURNAL
    assert metadata.volume == "42"
    assert metadata.issue == "1"
    assert metadata.pages == "87-94"
    assert metadata.doi == DOI
    assert metadata.pmcid == PMCID
    assert metadata.mesh_headings == ["Familial Mediterranean Fever"]
    assert metadata.nlm_citation is not None
    assert "Kavrul Kayaalp G." in metadata.nlm_citation
    assert "Rheumatology International. 2022;42(1):87-94." in metadata.nlm_citation
    assert f"doi: {DOI}." in metadata.nlm_citation
    assert f"PMID: {PMID}." in metadata.nlm_citation
    assert f"PMCID: {PMCID}." in metadata.nlm_citation
    assert metadata.bibtex is not None
    assert f"title = {{{TITLE}}}" in metadata.bibtex
    assert f"journal = {{{JOURNAL}}}" in metadata.bibtex
    assert "year = {2022}" in metadata.bibtex
    assert f"doi = {{{DOI}}}" in metadata.bibtex
    assert f"pmid = {{{PMID}}}" in metadata.bibtex


@pytest.mark.asyncio
async def test_publication_metadata_service_skips_citations_when_requested() -> None:
    response = await _fetch_metadata(include_citations="none")

    assert response.metadata[0].nlm_citation is None
    assert response.metadata[0].bibtex is None


@pytest.mark.asyncio
async def test_publication_metadata_service_can_return_only_nlm_citation() -> None:
    response = await _fetch_metadata(include_citations="nlm")

    assert response.metadata[0].nlm_citation is not None
    assert response.metadata[0].bibtex is None


@pytest.mark.asyncio
async def test_publication_metadata_service_can_return_only_bibtex_citation() -> None:
    response = await _fetch_metadata(include_citations="bibtex")

    assert response.metadata[0].nlm_citation is None
    assert response.metadata[0].bibtex is not None


@pytest.mark.asyncio
async def test_publication_metadata_service_continues_when_mesh_lookup_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "esummary.fcgi" in url:
            return httpx.Response(200, json=_esummary_json())
        if "efetch.fcgi" in url:
            return httpx.Response(500)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=[PMID], include_mesh=True)
        )

    assert response.success is True
    assert response.failed_pmids == {}
    assert response.metadata[0].pmid == PMID
    assert response.metadata[0].mesh_headings == []
    assert response.meta["warnings"] == ["mesh_lookup_failed"]


@pytest.mark.asyncio
async def test_publication_metadata_service_warns_when_mesh_xml_is_malformed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "esummary.fcgi" in url:
            return httpx.Response(200, json=_esummary_json())
        if "efetch.fcgi" in url:
            return httpx.Response(200, text="<PubmedArticleSet>")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=[PMID], include_mesh=True)
        )

    assert response.success is True
    assert response.failed_pmids == {}
    assert response.metadata[0].pmid == PMID
    assert response.metadata[0].mesh_headings == []
    assert "mesh_lookup_failed" in response.meta["warnings"]


@pytest.mark.asyncio
async def test_publication_metadata_service_does_not_warn_when_mesh_xml_has_no_headings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "esummary.fcgi" in url:
            return httpx.Response(200, json=_esummary_json())
        if "efetch.fcgi" in url:
            return httpx.Response(
                200,
                text=(
                    "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
                    f"<PMID>{PMID}</PMID>"
                    "</MedlineCitation></PubmedArticle></PubmedArticleSet>"
                ),
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=[PMID], include_mesh=True)
        )

    assert response.success is True
    assert response.metadata[0].mesh_headings == []
    assert "warnings" not in response.meta


@pytest.mark.asyncio
async def test_publication_metadata_service_continues_when_coverage_lookup_fails() -> None:
    async def failing_coverage_provider(
        pmids: list[str],
    ) -> dict[str, tuple[CoverageTier, CoverageReason]]:
        raise RuntimeError("coverage service unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_successful_handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(
            client=client,
            coverage_provider=failing_coverage_provider,
        )

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=[PMID], include_mesh=False, include_coverage=True)
        )

    assert response.success is True
    assert response.failed_pmids == {}
    assert response.metadata[0].pmid == PMID
    assert response.metadata[0].coverage == "unknown"
    assert response.metadata[0].coverage_reason is None
    assert response.meta["warnings"] == ["coverage_lookup_failed"]


@pytest.mark.asyncio
async def test_publication_metadata_service_reports_missing_pmids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"uids": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=["999999999"], include_mesh=False)
        )

    assert response.success is True
    assert response.metadata == []
    assert response.failed_pmids == {"999999999": "metadata_not_found"}


@pytest.mark.asyncio
async def test_publication_metadata_service_treats_esummary_error_records_as_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "uids": ["999999999"],
                    "999999999": {
                        "uid": "999999999",
                        "error": "cannot get document summary",
                    },
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NcbiPublicationMetadataClient(http_client=http_client)
        service = PublicationMetadataService(client=client)

        response = await service.get_metadata(
            PublicationMetadataRequest(pmids=["999999999"], include_mesh=False)
        )

    assert response.success is True
    assert response.metadata == []
    assert response.failed_pmids == {"999999999": "metadata_not_found"}
