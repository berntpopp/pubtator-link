from __future__ import annotations

import httpx
import pytest

from pubtator_link.api.client import PubTator3Client, PubTatorAPIError
from pubtator_link.config import APIConfig, TextProcessingConfig


def _client_with_transports(
    transport: httpx.AsyncBaseTransport,
    text_transport: httpx.AsyncBaseTransport | None = None,
) -> PubTator3Client:
    client = PubTator3Client(
        config=APIConfig(
            base_url="https://pubtator.example.test",
            timeout=5,
            rate_limit_per_second=1000,
        ),
        text_config=TextProcessingConfig(
            base_url="https://text.example.test",
            timeout=5,
        ),
    )
    client.client = httpx.AsyncClient(
        transport=transport,
        base_url="https://pubtator.example.test",
        headers={"Accept": "application/json"},
    )
    client.text_client = httpx.AsyncClient(
        transport=text_transport or transport,
        base_url="https://text.example.test",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    return client


@pytest.mark.asyncio
async def test_get_export_retries_503_then_succeeds() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request, text="busy")
        return httpx.Response(200, request=request, json={"documents": []})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        result = await client.export_publications(["40234174"], format="biocjson")
    finally:
        await client.close()

    assert result == {"documents": []}
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_get_export_respects_retry_after_header() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503,
                request=request,
                headers={"Retry-After": "0"},
                text="busy",
            )
        return httpx.Response(200, request=request, json={"documents": []})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        result = await client.export_publications(["40234174"], format="biocjson")
    finally:
        await client.close()

    assert result == {"documents": []}
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_get_export_does_not_retry_404() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, request=request, text="missing")

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications(["40234174"], format="biocjson")
    finally:
        await client.close()

    assert exc_info.value.status_code == 404
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_text_processing_post_does_not_retry_by_default() -> None:
    text_requests: list[httpx.Request] = []

    async def text_handler(request: httpx.Request) -> httpx.Response:
        text_requests.append(request)
        return httpx.Response(503, request=request, text="busy")

    client = _client_with_transports(
        httpx.MockTransport(lambda request: httpx.Response(200, request=request, json={})),
        text_transport=httpx.MockTransport(text_handler),
    )
    try:
        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.submit_text_annotation("MEFV evidence", bioconcept="Gene")
    finally:
        await client.close()

    assert exc_info.value.status_code == 503
    assert len(text_requests) == 1


@pytest.mark.asyncio
async def test_export_publications_with_metadata_reports_retry_attempts() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                503,
                request=request,
                headers={"Retry-After": "0"},
                text="busy",
            )
        return httpx.Response(200, request=request, json={"documents": []})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        payload, metadata = await client.export_publications_with_metadata(
            ["40234174"],
            format="biocjson",
            full=False,
        )
    finally:
        await client.close()

    assert payload == {"documents": []}
    assert len(requests) == 2
    assert metadata.attempt_count == 2
    assert metadata.last_status_code == 200
    assert metadata.terminal_reason is None


@pytest.mark.asyncio
async def test_export_publications_with_metadata_attaches_retry_exhausted_to_error() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request, json={"error": "busy"})

    client = _client_with_transports(httpx.MockTransport(handler))
    try:
        with pytest.raises(PubTatorAPIError) as exc_info:
            await client.export_publications_with_metadata(["40234174"], format="biocjson")
    finally:
        await client.close()

    assert len(requests) == 3
    metadata = exc_info.value.response_data["retry_metadata"]
    assert metadata["attempt_count"] == 3
    assert metadata["last_status_code"] == 503
    assert metadata["terminal_reason"] == "retry_exhausted"


@pytest.mark.asyncio
async def test_sidecar_request_metadata_records_single_post_attempt() -> None:
    async def text_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            text="SESSION-1",
            headers={"content-type": "text/plain"},
        )

    client = _client_with_transports(
        httpx.MockTransport(lambda request: httpx.Response(200, request=request, json={})),
        text_transport=httpx.MockTransport(text_handler),
    )
    try:
        payload, metadata = await client._make_request_with_metadata(
            "POST",
            "https://text.example.test/request.cgi",
            data={"text": "MEFV evidence", "bioconcept": "Gene"},
            use_text_client=True,
            retry=False,
        )
    finally:
        await client.close()

    assert payload == {"content": "SESSION-1", "content_type": "text/plain"}
    assert metadata.attempt_count == 1
    assert metadata.last_status_code == 200
    assert metadata.terminal_reason is None
