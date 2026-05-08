from __future__ import annotations

import httpx
import pytest

from pubtator_link.api.retry import RetryPolicy
from pubtator_link.models.literature_graph import LiteratureAvailability, ProviderWarning
from pubtator_link.services.literature_providers import (
    PROVIDER_DISABLED,
    CrossrefClient,
    EuropePmcLiteratureClient,
    OpenAlexClient,
    UnpaywallClient,
)
from tests.fixtures.literature_graph import (
    CROSSREF_WORK_ARD_2025,
    EUROPE_PMC_CITATIONS_40562663,
    OPENALEX_WORK,
    UNPAYWALL_WORK,
)


class MockTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, request=request)


class StatusTransport:
    def __init__(self, status_code: int, payload: dict[str, object] | None = None) -> None:
        self.status_code = status_code
        self.payload = payload or {}
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status_code, json=self.payload, request=request)


class SequentialStatusTransport:
    def __init__(self, responses: list[tuple[int, dict[str, object]]]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status_code, payload = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
        return httpx.Response(status_code, json=payload, request=request)


class SequentialTransport:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = payloads
        self.requests: list[httpx.Request] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        payload = self.payloads[len(self.requests) - 1]
        return httpx.Response(200, json=payload, request=request)


@pytest.mark.asyncio
async def test_crossref_client_get_work_and_reference_mapping() -> None:
    transport = MockTransport(CROSSREF_WORK_ARD_2025)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = CrossrefClient(http_client=http_client, mailto="curator@example.org")

    work = await client.get_work("10.1016/j.ard.2025.05.020")
    references = client.references_from_work(work)

    assert transport.requests[0].url.raw_path.startswith(b"/works/10.1016%2Fj.ard.2025.05.020")
    assert transport.requests[0].url.params["mailto"] == "curator@example.org"
    assert references[0].doi == "10.1000/primary-study"
    assert references[0].title == "Primary trial of colchicine"
    assert references[0].journal == "Example Journal"
    assert references[0].year == 2021
    assert references[1].title == "Unresolved guideline reference"
    assert references[1].journal == "Guideline Journal"
    assert references[1].status == "unresolved_reference"
    await client.close()


@pytest.mark.asyncio
async def test_europe_pmc_literature_client_get_citations_maps_availability() -> None:
    transport = MockTransport(EUROPE_PMC_CITATIONS_40562663)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = EuropePmcLiteratureClient(http_client=http_client)

    citations = await client.get_citations("40562663", limit=1)

    assert transport.requests[0].url.params["pageSize"] == "1"
    assert citations[0].pmid == "40600001"
    assert citations[0].doi == "10.1000/citing-study"
    assert citations[0].availability.is_open_access is True
    assert citations[0].availability.has_pmc_full_text is True
    assert citations[0].availability.has_pdf is True
    await client.close()


@pytest.mark.asyncio
async def test_europe_pmc_literature_client_get_citations_maps_citation_list_payload() -> None:
    transport = MockTransport(
        {
            "citationList": {
                "citation": [
                    {
                        "id": "41910911",
                        "source": "MED",
                        "title": "Growth differentiation factor-15 as a potential biomarker.",
                        "journalAbbreviation": "Clin Rheumatol",
                        "pubYear": 2026,
                    }
                ]
            }
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = EuropePmcLiteratureClient(http_client=http_client)

    citations = await client.get_citations("28386255", limit=5)

    assert citations[0].pmid == "41910911"
    assert citations[0].journal == "Clin Rheumatol"
    assert citations[0].year == 2026
    await client.close()


@pytest.mark.asyncio
async def test_europe_pmc_literature_client_retries_transient_status() -> None:
    transport = SequentialStatusTransport(
        [
            (503, {"error": "temporarily unavailable"}),
            (200, EUROPE_PMC_CITATIONS_40562663),
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = EuropePmcLiteratureClient(
        http_client=http_client,
        retry_policy=RetryPolicy(max_attempts=2, base_delay_ms=0, max_delay_ms=0),
    )

    citations = await client.get_citations("40562663", limit=1)

    assert len(transport.requests) == 2
    assert citations[0].pmid == "40600001"
    await client.close()


@pytest.mark.asyncio
async def test_provider_parsing_ignores_empty_identifier_strings() -> None:
    transport = MockTransport(
        {
            "resultList": {
                "result": [
                    {
                        "id": "40600001",
                        "pmid": " ",
                        "doi": "",
                        "title": "Metadata without identifiers",
                    }
                ]
            }
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = EuropePmcLiteratureClient(http_client=http_client)

    citations = await client.get_citations("40562663", limit=25)

    assert citations[0].pmid is None
    assert citations[0].doi is None
    await client.close()


@pytest.mark.asyncio
async def test_openalex_client_get_work_by_doi_maps_metadata_and_availability() -> None:
    transport = MockTransport(OPENALEX_WORK)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = OpenAlexClient(http_client=http_client, mailto="curator@example.org")

    paper = await client.get_work_by_doi("10.1000/primary-study")

    assert transport.requests[0].url.params["mailto"] == "curator@example.org"
    assert paper.pmid == "39596913"
    assert paper.openalex_id == "https://openalex.org/W123"
    assert paper.authors[0].name == "Ada Example"
    assert paper.authors[0].affiliations == ["Example University"]
    assert paper.availability.is_open_access is True
    assert paper.availability.oa_status == "green"
    await client.close()


@pytest.mark.asyncio
async def test_openalex_client_get_cited_by_falls_back_to_cites_filter() -> None:
    transport = SequentialTransport(
        [
            {
                "id": "https://openalex.org/W2599457451",
                "doi": "https://doi.org/10.3389/fimmu.2017.00253",
                "title": "Familial Mediterranean Fever",
                "publication_year": 2017,
                "cited_by_count": 193,
            },
            {
                "meta": {"count": 193},
                "results": [
                    {
                        "id": "https://openalex.org/W1685331907",
                        "ids": {
                            "pmid": "https://pubmed.ncbi.nlm.nih.gov/31180581",
                            "doi": "https://doi.org/10.1002/jca.21705",
                        },
                        "doi": "https://doi.org/10.1002/jca.21705",
                        "title": "Guidelines on therapeutic apheresis",
                        "publication_year": 2019,
                    }
                ],
            },
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = OpenAlexClient(http_client=http_client, mailto="curator@example.org")

    papers = await client.get_cited_by("10.3389/fimmu.2017.00253", limit=5)

    assert transport.requests[1].url.path == "/works"
    assert transport.requests[1].url.params["filter"] == "cites:W2599457451"
    assert transport.requests[1].url.params["per-page"] == "5"
    assert transport.requests[1].url.params["mailto"] == "curator@example.org"
    assert papers[0].pmid == "31180581"
    assert papers[0].doi == "10.1002/jca.21705"
    await client.close()


@pytest.mark.asyncio
async def test_openalex_client_retries_transient_work_lookup_status() -> None:
    transport = SequentialStatusTransport(
        [
            (502, {"error": "bad gateway"}),
            (200, OPENALEX_WORK),
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = OpenAlexClient(
        http_client=http_client,
        mailto="curator@example.org",
        retry_policy=RetryPolicy(max_attempts=2, base_delay_ms=0, max_delay_ms=0),
    )

    paper = await client.get_work_by_doi("10.1000/primary-study")

    assert len(transport.requests) == 2
    assert paper.pmid == "39596913"
    await client.close()


@pytest.mark.asyncio
async def test_unpaywall_client_without_email_returns_provider_disabled_warning() -> None:
    client = UnpaywallClient(email=None)

    warning = await client.get_availability("10.1000/primary-study")

    assert isinstance(warning, ProviderWarning)
    assert warning.status == PROVIDER_DISABLED
    await client.close()


@pytest.mark.asyncio
async def test_unpaywall_client_with_payload_returns_availability() -> None:
    transport = MockTransport(UNPAYWALL_WORK)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = UnpaywallClient(http_client=http_client, email="curator@example.org")

    availability = await client.get_availability("10.1000/primary-study")

    assert isinstance(availability, LiteratureAvailability)
    assert availability.is_open_access is True
    assert availability.oa_status == "green"
    assert availability.full_text_url == "https://example.org/fulltext"
    assert availability.license_or_access_hint == "cc-by"
    await client.close()


@pytest.mark.asyncio
async def test_unpaywall_client_404_returns_no_match_warning() -> None:
    transport = StatusTransport(404)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = UnpaywallClient(http_client=http_client, email="curator@example.org")

    result = await client.get_availability("10.1002/missing")

    assert isinstance(result, ProviderWarning)
    assert result.status == "provider_no_match"
    assert result.retryable is False
    await client.close()


@pytest.mark.asyncio
async def test_unpaywall_client_retries_transient_status_before_availability() -> None:
    transport = SequentialStatusTransport(
        [
            (504, {"error": "timeout"}),
            (200, UNPAYWALL_WORK),
        ]
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = UnpaywallClient(
        http_client=http_client,
        email="curator@example.org",
        retry_policy=RetryPolicy(max_attempts=2, base_delay_ms=0, max_delay_ms=0),
    )

    availability = await client.get_availability("10.1000/primary-study")

    assert len(transport.requests) == 2
    assert isinstance(availability, LiteratureAvailability)
    assert availability.is_open_access is True
    await client.close()
