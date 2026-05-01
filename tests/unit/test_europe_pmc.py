import httpx
import pytest

from pubtator_link.services.europe_pmc import EuropePmcClient


@pytest.mark.asyncio
async def test_europe_pmc_client_returns_open_access_xml() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "PMC123" in str(request.url)
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "pmcid": "PMC123",
                            "isOpenAccess": "Y",
                            "license": "CC BY",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {
                                        "availability": "Open access",
                                        "url": "https://example.org/full.xml",
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EuropePmcClient(http_client=http_client, base_url="https://example.org")
        result = await client.lookup_open_access_record("PMC123")

    assert result.available is True
    assert result.pmcid == "PMC123"
    assert result.license_or_access_hint == "CC BY"


@pytest.mark.asyncio
async def test_europe_pmc_client_reports_not_open_access() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"resultList": {"result": [{"pmcid": "PMC123", "isOpenAccess": "N"}]}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EuropePmcClient(http_client=http_client, base_url="https://example.org")
        result = await client.lookup_open_access_record("PMC123")

    assert result.available is False
    assert result.reason == "license_reuse_unavailable"


@pytest.mark.asyncio
async def test_europe_pmc_client_reports_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"resultList": {"result": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EuropePmcClient(http_client=http_client, base_url="https://example.org")
        result = await client.lookup_open_access_record("PMC123")

    assert result.available is False
    assert result.reason == "not_found"
