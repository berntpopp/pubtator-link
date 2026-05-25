from __future__ import annotations

from collections.abc import Sequence

import httpx
import pytest

from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdKind,
    CitationLookupRecord,
    MeshDescriptor,
    RelatedArticleMode,
    RelatedArticleRecord,
)
from pubtator_link.models.publication_metadata import (
    PublicationAuthor,
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient
from tests.fixtures.literature_graph import NCBI_ELINK_NEIGHBOR_SCORE


def assert_no_prepare_mode(payload: object) -> None:
    assert "prepare_mode" not in str(payload)


class MockTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, request=request)


class SequentialMockTransport:
    def __init__(self, payloads: Sequence[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = self.payloads[len(self.requests) - 1]
        return httpx.Response(200, json=payload, request=request)


class SequentialStatusTransport:
    def __init__(self, responses: Sequence[tuple[int, dict[str, object]]]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, payload = self.responses[len(self.requests) - 1]
        return httpx.Response(status_code, json=payload, request=request)


class FakeDiscoveryClient:
    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        return [
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
            ),
            ArticleIdConversionRecord(
                input_id="bad",
                input_kind="auto",
                status="unresolved",
                reason="not_found",
            ),
        ]

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return None

    async def find_pmid_by_title(self, title: str) -> str | None:
        return None

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        return [
            MeshDescriptor(
                ui="D010505",
                name="Familial Mediterranean Fever",
                search_terms=["familial mediterranean fever"],
            )
        ]

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        return [
            CitationLookupRecord(citation="citation 1", status="matched", pmid="123"),
            CitationLookupRecord(citation="citation 2", status="matched", pmid="123"),
            CitationLookupRecord(citation="missing", status="not_found", reason="not_found"),
        ]

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        return [
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="789", relation=mode),
        ]


@pytest.mark.asyncio
async def test_convert_article_ids_adds_candidates_and_next_commands() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.convert_article_ids(["PMC123", "bad"])

    assert response.candidate_pmids == ["123"]
    assert response.unresolved == ["bad"]
    assert response.meta.next_commands[0]["tool"] == "pubtator_stage_research_session"
    assert response.meta.next_commands[0]["arguments"] == {"pmids": ["123"]}
    assert response.meta.next_commands[1] == {
        "tool": "pubtator_index_review_evidence",
        "arguments": {"pmids": ["123"]},
    }
    assert_no_prepare_mode(response.meta.next_commands)


@pytest.mark.asyncio
async def test_lookup_citation_extracts_nbk_and_adds_recovery_hint() -> None:
    class Client(FakeDiscoveryClient):
        async def lookup_citations(self, citations):
            assert citations == ["GeneReviews NBK1139 familial Mediterranean fever"]
            return [
                CitationLookupRecord(
                    citation=citations[0],
                    status="not_found",
                    reason="not_found",
                )
            ]

        async def convert_article_ids(self, ids, source):
            assert ids == ["NBK1139"]
            return [
                ArticleIdConversionRecord(
                    input_id="NBK1139",
                    input_kind="auto",
                    status="unresolved",
                    reason="not_found",
                )
            ]

    service = DiscoveryService(Client())

    response = await service.lookup_citation(["https://www.ncbi.nlm.nih.gov/books/NBK1139/"])

    assert response.records[0].reason in {"nbk_not_mapped", "not_found"}
    assert response.meta.next_commands
    assert "NBK1139" in str(response.meta.next_commands)


@pytest.mark.asyncio
async def test_lookup_citation_falls_back_to_title_search_for_prose_reference() -> None:
    class Client(FakeDiscoveryClient):
        def __init__(self) -> None:
            self.title_queries: list[str] = []

        async def lookup_citations(self, citations):
            return [
                CitationLookupRecord(
                    citation=citations[0],
                    status="not_found",
                    reason="not_found",
                )
            ]

        async def find_pmid_by_title(self, title: str) -> str | None:
            self.title_queries.append(title)
            return "42135612"

    client = Client()
    service = DiscoveryService(client)

    response = await service.lookup_citation(
        [
            (
                "Ozen S. MEFV variants of uncertain significance in children. "
                "Rheumatology. 2026;65:100-110."
            )
        ]
    )

    assert response.records[0].status == "matched"
    assert response.records[0].pmid == "42135612"
    assert response.records[0].title == "MEFV variants of uncertain significance in children"
    assert client.title_queries == ["MEFV variants of uncertain significance in children"]


@pytest.mark.asyncio
async def test_lookup_citation_enriches_matched_metadata_fields() -> None:
    class Client(FakeDiscoveryClient):
        async def lookup_citations(self, citations):
            return [CitationLookupRecord(citation=citations[0], status="matched", pmid="26802180")]

    class Metadata:
        async def get_metadata(self, request):
            assert request.pmids == ["26802180"]
            assert request.include_mesh is False
            assert request.include_publication_types is False
            assert request.include_citations == "none"
            assert request.include_coverage is False
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="26802180",
                        title="EULAR recommendations for the management of FMF",
                        journal="Annals of the Rheumatic Diseases",
                        pub_year=2016,
                        authors=[
                            PublicationAuthor(last_name="Ozen", initials="S"),
                            PublicationAuthor(last_name="Demirkaya", initials="E"),
                        ],
                    )
                ],
                failed_pmids={},
                _meta={"next_commands": []},
            )

    service = DiscoveryService(Client(), metadata_service=Metadata())

    response = await service.lookup_citation(["Ozen S. EULAR recommendations. Ann Rheum Dis."])

    assert response.candidate_pmids == ["26802180"]
    assert response.records[0].title == "EULAR recommendations for the management of FMF"
    assert response.records[0].journal == "Annals of the Rheumatic Diseases"
    assert response.records[0].year == 2016
    assert response.records[0].authors == ["Ozen S", "Demirkaya E"]


@pytest.mark.asyncio
async def test_lookup_citation_preserves_match_when_metadata_enrichment_fails() -> None:
    class Client(FakeDiscoveryClient):
        async def lookup_citations(self, citations):
            return [CitationLookupRecord(citation=citations[0], status="matched", pmid="26802180")]

    class Metadata:
        async def get_metadata(self, request):
            raise RuntimeError("metadata upstream unavailable")

    service = DiscoveryService(Client(), metadata_service=Metadata())

    response = await service.lookup_citation(["Ozen S. EULAR recommendations. Ann Rheum Dis."])

    assert response.candidate_pmids == ["26802180"]
    assert response.records[0].status == "matched"
    assert response.records[0].pmid == "26802180"
    assert response.records[0].title is None
    assert response.metadata_status == "unavailable"
    assert response.meta.next_commands[0]["arguments"] == {"pmids": ["26802180"]}
    assert any(
        command["tool"] == "pubtator_get_publication_metadata"
        and command["arguments"] == {"pmids": ["26802180"]}
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_ncbi_client_parses_id_conversion_json() -> None:
    transport = MockTransport(
        {
            "records": [
                {
                    "requested-id": "10.1000/example",
                    "pmid": "456",
                    "pmcid": "PMC456",
                    "doi": "10.1000/example",
                },
                {"pmid": "123", "pmcid": "PMC123", "doi": "10.1000/example"},
                {"requested-id": "bad", "status": "error"},
            ]
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(["10.1000/example", "PMC123", "bad"], "auto")

    assert [record.input_id for record in records] == ["10.1000/example", "PMC123", "bad"]
    assert records[0].status == "resolved"
    assert records[0].pmid == "456"
    assert records[0].pmcid == "PMC456"
    assert records[0].doi == "10.1000/example"
    assert records[1].status == "resolved"
    assert records[1].pmid == "123"
    assert records[1].pmcid == "PMC123"
    assert records[2].status == "unresolved"
    assert records[2].reason == "not_found"
    assert (
        str(transport.requests[0].url.copy_with(query=None))
        == "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
    )
    assert transport.requests[0].url.params["ids"] == "10.1000/example,PMC123,bad"
    assert transport.requests[0].url.params["format"] == "json"
    assert transport.requests[0].url.params["tool"] == "pubtator-link"
    assert "idtype" not in transport.requests[0].url.params
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_retries_mixed_id_conversion_per_identifier_after_batch_400() -> None:
    transport = SequentialStatusTransport(
        [
            (400, {"status": "error"}),
            (200, {"records": [{"requested-id": "24166952", "pmid": "24166952"}]}),
            (200, {"records": [{"requested-id": "PMC12758588", "pmid": "41480953"}]}),
            (400, {"status": "error"}),
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(
        ["24166952", "PMC12758588", "10.1038/s41431-022-01127-3"],
        "auto",
    )

    assert [record.input_id for record in records] == [
        "24166952",
        "PMC12758588",
        "10.1038/s41431-022-01127-3",
    ]
    assert records[0].status == "resolved"
    assert records[0].pmid == "24166952"
    assert records[1].status == "resolved"
    assert records[1].pmid == "41480953"
    assert records[2].status == "failed"
    assert records[2].reason == "upstream_rejected_identifier"
    assert [request.url.params["ids"] for request in transport.requests] == [
        "24166952,PMC12758588,10.1038/s41431-022-01127-3",
        "24166952",
        "PMC12758588",
        "10.1038/s41431-022-01127-3",
    ]
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_sends_idtype_for_explicit_source() -> None:
    transport = MockTransport(
        {"records": [{"requested-id": "PMC123", "pmid": "123", "pmcid": "PMC123"}]}
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(["PMC123"], "pmcid")

    assert records[0].status == "resolved"
    assert transport.requests[0].url.params["ids"] == "PMC123"
    assert transport.requests[0].url.params["idtype"] == "pmcid"
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_finds_pmid_by_doi_with_article_identifier_search() -> None:
    transport = MockTransport({"esearchresult": {"idlist": ["26802180"]}})
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    pmid = await client.find_pmid_by_doi("10.1136/annrheumdis-2015-208690")

    assert pmid == "26802180"
    assert transport.requests[0].url.path.endswith("/esearch.fcgi")
    assert transport.requests[0].url.params["db"] == "pubmed"
    assert transport.requests[0].url.params["term"] == "10.1136/annrheumdis-2015-208690[AID]"
    assert transport.requests[0].url.params["retmode"] == "json"
    assert transport.requests[0].url.params["retmax"] == "1"
    assert transport.requests[0].url.params["tool"] == "pubtator-link"
    await client.close()


@pytest.mark.asyncio
async def test_lookup_mesh_returns_search_next_command() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.lookup_mesh("familial mediterranean fever")

    assert response.descriptors[0].ui == "D010505"
    assert response.meta.next_commands[0]["tool"] == "pubtator_search_literature"


@pytest.mark.asyncio
async def test_ncbi_client_parses_ecitmatch_lines() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        text = "Ann Rheum Dis|2024|83|1|Author|known-key|39596913\nUnknown||||||NOT_FOUND\n"
        return httpx.Response(200, text=text, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.lookup_citations(["known", "unknown"])

    assert records[0].status == "matched"
    assert records[0].pmid == "39596913"
    assert records[0].pmid != "known-key"
    assert records[1].status == "not_found"
    assert requests[0].url.path.endswith("/ecitmatch.cgi")
    assert requests[0].url.params["db"] == "pubmed"
    assert requests[0].url.params["retmode"] == "text"
    assert requests[0].url.params["tool"] == "pubtator-link"
    assert requests[0].url.params["bdata"] == "known\runknown"
    await client.close()


@pytest.mark.asyncio
async def test_lookup_citation_normalizes_prose_references_for_ecitmatch() -> None:
    class Client(FakeDiscoveryClient):
        requested_citations: Sequence[str] = ()

        async def lookup_citations(self, citations):
            self.requested_citations = citations
            return [
                CitationLookupRecord(
                    citation=citations[0],
                    status="matched",
                    pmid="32404922",
                ),
                CitationLookupRecord(
                    citation=citations[1],
                    status="matched",
                    pmid="37310422",
                ),
            ]

    client = Client()
    service = DiscoveryService(client)

    response = await service.lookup_citation(
        [
            "Deignan JL, Astbury C, Cutting GR, et al. CFTR variant testing: "
            "a technical standard of the American College of Medical Genetics "
            "and Genomics (ACMG). Genet Med. 2020;22(8):1288-1295.",
            "Deignan JL, Gregg AR, Grody WW, et al. Updated recommendations "
            "for CFTR carrier screening: A position statement of the American "
            "College of Medical Genetics and Genomics (ACMG). Genet Med. "
            "2023;25(8):100867.",
        ]
    )

    assert client.requested_citations == [
        "Genet Med|2020|22|1288|Deignan|0|",
        "Genet Med|2023|25|100867|Deignan|1|",
    ]
    assert response.candidate_pmids == ["32404922", "37310422"]


@pytest.mark.asyncio
async def test_lookup_citation_resolves_doi_only_inputs() -> None:
    class Client(FakeDiscoveryClient):
        async def lookup_citations(self, citations):
            return [
                CitationLookupRecord(
                    citation=citation,
                    status="not_found",
                    reason="not_found",
                )
                for citation in citations
            ]

        async def find_pmid_by_doi(self, doi: str) -> str | None:
            return {
                "10.1038/s41436-020-0822-5": "32404922",
                "10.1016/j.gim.2023.100867": "37310422",
            }.get(doi)

    service = DiscoveryService(Client())

    response = await service.lookup_citation(
        ["10.1038/s41436-020-0822-5", "10.1016/j.gim.2023.100867"]
    )

    assert [record.status for record in response.records] == ["matched", "matched"]
    assert [record.pmid for record in response.records] == ["32404922", "37310422"]
    assert [record.doi for record in response.records] == [
        "10.1038/s41436-020-0822-5",
        "10.1016/j.gim.2023.100867",
    ]
    assert response.candidate_pmids == ["32404922", "37310422"]


@pytest.mark.asyncio
async def test_ncbi_client_keeps_ecitmatch_blank_lines_aligned() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        text = (
            "Ann Rheum Dis|2024|83|1|Author|known-key|39596913\n"
            "\n"
            "Lancet|2023|401|1|Author|third-key|31234567\n"
        )
        return httpx.Response(200, text=text, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.lookup_citations(["known", "blank", "third"])

    assert records[0].status == "matched"
    assert records[0].pmid == "39596913"
    assert records[1].status == "not_found"
    assert records[1].pmid is None
    assert records[2].status == "matched"
    assert records[2].pmid == "31234567"
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_parses_mesh_lookup_json() -> None:
    transport = MockTransport(
        {
            "esearchresult": {"idlist": ["68050505"]},
            "result": {
                "68050505": {
                    "uid": "68050505",
                    "ds_meshterms": ["Familial Mediterranean Fever"],
                    "ds_scopenote": "An autoinflammatory disease.",
                    "ds_idxlinks": ["FMF"],
                    "ds_meshui": "D005505",
                    "ds_tree": ["C16.320.565"],
                }
            },
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    descriptors = await client.lookup_mesh("FMF", limit=5, exact=False)

    assert len(descriptors) == 1
    assert descriptors[0].ui == "D005505"
    assert descriptors[0].name == "Familial Mediterranean Fever"
    assert descriptors[0].scope_note == "An autoinflammatory disease."
    assert descriptors[0].entry_terms == []
    assert descriptors[0].tree_numbers == ["C16.320.565"]
    assert descriptors[0].search_terms == ["Familial Mediterranean Fever[MeSH Terms]"]
    assert transport.requests[0].url.path.endswith("/esearch.fcgi")
    assert transport.requests[0].url.params["db"] == "mesh"
    assert transport.requests[0].url.params["term"] == "FMF"
    assert transport.requests[0].url.params["retmode"] == "json"
    assert transport.requests[0].url.params["retmax"] == "5"
    assert transport.requests[0].url.params["tool"] == "pubtator-link"
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_parses_mesh_lookup_esummary_json() -> None:
    transport = SequentialMockTransport(
        [
            {"esearchresult": {"idlist": ["68050505"]}},
            {
                "result": {
                    "68050505": {
                        "uid": "68050505",
                        "ds_meshterms": [
                            "Familial Mediterranean Fever",
                            "FMF",
                            "Periodic Disease",
                        ],
                        "ds_scopenote": "An autoinflammatory disease.",
                        "ds_idxlinks": [{"treenum": "C16.320.565"}],
                        "ds_meshui": "D005505",
                    }
                }
            },
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    descriptors = await client.lookup_mesh("FMF", limit=5, exact=False)

    assert len(transport.requests) == 2
    assert transport.requests[0].url.path.endswith("/esearch.fcgi")
    assert transport.requests[1].url.path.endswith("/esummary.fcgi")
    assert transport.requests[1].url.params["id"] == "68050505"
    assert len(descriptors) == 1
    assert descriptors[0].ui == "D005505"
    assert descriptors[0].name == "Familial Mediterranean Fever"
    assert descriptors[0].scope_note == "An autoinflammatory disease."
    assert descriptors[0].entry_terms == ["FMF", "Periodic Disease"]
    assert descriptors[0].tree_numbers == ["C16.320.565"]
    assert descriptors[0].search_terms == ["Familial Mediterranean Fever[MeSH Terms]"]
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_lookup_mesh_exact_mode_uses_mesh_terms_query() -> None:
    transport = MockTransport({"esearchresult": {"idlist": []}})
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    descriptors = await client.lookup_mesh("FMF", limit=5, exact=True)

    assert descriptors == []
    assert transport.requests[0].url.params["term"] == '"FMF"[MeSH Terms]'
    await client.close()


@pytest.mark.asyncio
async def test_lookup_citation_deduplicates_candidate_pmids() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.lookup_citation(["citation 1", "citation 2", "missing"])

    assert response.candidate_pmids == ["123"]
    assert response.meta.next_commands[0]["arguments"] == {"pmids": ["123"]}
    assert response.meta.next_commands[1]["arguments"] == {
        "pmids": ["123"],
    }
    assert_no_prepare_mode(response.meta.next_commands)


@pytest.mark.asyncio
async def test_find_related_articles_deduplicates_candidates() -> None:
    service = DiscoveryService(FakeDiscoveryClient())

    response = await service.find_related_articles(["123", "999"])

    assert response.candidate_pmids == ["456", "789"]
    assert response.meta.next_commands[0]["arguments"] == {"pmids": ["456", "789"]}
    assert response.meta.next_commands[1]["arguments"] == {
        "pmids": ["456", "789"],
    }
    assert_no_prepare_mode(response.meta.next_commands)
    assert response.unresolved == ["999"]
    assert response.metadata_status == "unavailable"
    assert any(
        command["tool"] == "pubtator_get_publication_metadata"
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_find_related_articles_enriches_metadata_fields() -> None:
    class Client(FakeDiscoveryClient):
        async def find_related_articles(self, pmids, mode, limit):
            return [RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode)]

    class Metadata:
        async def get_metadata(self, request):
            assert request.pmids == ["456"]
            assert request.include_mesh is False
            assert request.include_publication_types is False
            assert request.include_citations == "none"
            assert request.include_coverage is False
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="456",
                        title="Related FMF cohort",
                        journal="Rheumatology",
                        pub_year=2024,
                    )
                ],
                failed_pmids={},
                _meta={"next_commands": []},
            )

    service = DiscoveryService(Client(), metadata_service=Metadata())

    response = await service.find_related_articles(["123"])

    assert response.related_articles[0].title == "Related FMF cohort"
    assert response.related_articles[0].journal == "Rheumatology"
    assert response.related_articles[0].year == 2024
    assert response.metadata_status == "success"
    assert response.meta.next_commands[0]["arguments"] == {"pmids": ["456"]}


@pytest.mark.asyncio
async def test_find_related_articles_reports_partial_metadata_enrichment() -> None:
    class Client(FakeDiscoveryClient):
        async def find_related_articles(self, pmids, mode, limit):
            return [
                RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
                RelatedArticleRecord(source_pmid="123", pmid="789", relation=mode),
            ]

    class Metadata:
        async def get_metadata(self, request):
            return PublicationMetadataResponse(
                metadata=[
                    PublicationMetadata(
                        pmid="456",
                        title="Related FMF cohort",
                        journal="Rheumatology",
                        pub_year=2024,
                    )
                ],
                failed_pmids={"789": "metadata_not_found"},
                _meta={"next_commands": []},
            )

    service = DiscoveryService(Client(), metadata_service=Metadata())

    response = await service.find_related_articles(["123"])

    assert response.metadata_status == "partial"
    assert response.related_articles[0].title == "Related FMF cohort"
    assert response.related_articles[1].title is None
    assert any(
        command["tool"] == "pubtator_get_publication_metadata"
        and command["arguments"] == {"pmids": ["456", "789"]}
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_find_related_articles_reports_unavailable_when_metadata_enrichment_fails() -> None:
    class Client(FakeDiscoveryClient):
        async def find_related_articles(self, pmids, mode, limit):
            return [RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode)]

    class Metadata:
        async def get_metadata(self, request):
            raise RuntimeError("metadata upstream unavailable")

    service = DiscoveryService(Client(), metadata_service=Metadata())

    response = await service.find_related_articles(["123"])

    assert response.candidate_pmids == ["456"]
    assert response.metadata_status == "unavailable"
    assert response.related_articles[0] == RelatedArticleRecord(
        source_pmid="123",
        pmid="456",
        relation="similar",
    )
    assert any(
        command["tool"] == "pubtator_get_publication_metadata"
        and command["arguments"] == {"pmids": ["456"]}
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_ncbi_client_parses_related_article_links() -> None:
    payload = {
        "linksets": [
            {
                "ids": ["123"],
                "linksetdbs": [{"linkname": "pubmed_pubmed", "links": ["456", "789"]}],
            }
        ]
    }
    transport = MockTransport(payload)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_articles(["123"], "similar", 10)

    assert [record.pmid for record in records] == ["456", "789"]
    assert all(record.source_pmid == "123" for record in records)
    assert transport.requests[0].url.path.endswith("/elink.fcgi")
    assert transport.requests[0].url.params["dbfrom"] == "pubmed"
    assert transport.requests[0].url.params["db"] == "pubmed"
    assert transport.requests[0].url.params["id"] == "123"
    assert transport.requests[0].url.params["linkname"] == "pubmed_pubmed"
    assert transport.requests[0].url.params["retmode"] == "json"
    assert transport.requests[0].url.params["tool"] == "pubtator-link"
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_parses_elink_neighbor_scores() -> None:
    transport = MockTransport(NCBI_ELINK_NEIGHBOR_SCORE)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_article_scores(["40562663"], limit=10)

    assert [(record.source_pmid, record.pmid, record.neighbor_score) for record in records] == [
        ("40562663", "39596913", 1220),
        ("40562663", "40600001", 900),
    ]
    assert transport.requests[0].url.path.endswith("/elink.fcgi")
    assert transport.requests[0].url.params["cmd"] == "neighbor_score"
    await client.close()


@pytest.mark.asyncio
async def test_ncbi_client_preserves_related_article_source_attribution() -> None:
    payload = {
        "linksets": [
            {
                "ids": ["123"],
                "linksetdbs": [{"linkname": "pubmed_pubmed", "links": ["123", "456", "457"]}],
            },
            {
                "ids": ["999"],
                "linksetdbs": [
                    {"linkname": "pubmed_pubmed", "links": ["998"]},
                    {"linkname": "pubmed_pubmed", "links": ["997"]},
                ],
            },
        ]
    }
    transport = MockTransport(payload)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_articles(["123", "999"], "similar", 1)

    assert [(record.source_pmid, record.pmid) for record in records] == [
        ("123", "456"),
        ("999", "998"),
    ]
    assert transport.requests[0].url.params.get_list("id") == ["123", "999"]
    assert transport.requests[0].url.params["linkname"] == "pubmed_pubmed"
    await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "linkname"),
    [
        ("cited_by", "pubmed_pubmed_citedin"),
        ("references", "pubmed_pubmed_refs"),
    ],
)
async def test_ncbi_client_maps_related_article_modes(
    mode: RelatedArticleMode,
    linkname: str,
) -> None:
    transport = MockTransport({"linksets": []})
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_articles(["123"], mode, 10)

    assert records == []
    assert transport.requests[0].url.params["linkname"] == linkname
    await client.close()
