from __future__ import annotations

import httpx
import pytest

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.retry import RetryPolicy
from pubtator_link.config import APIConfig, TextProcessingConfig


def _client_with_text_transport(transport: httpx.AsyncBaseTransport) -> PubTator3Client:
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
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(_empty_json))
    client.text_client = httpx.AsyncClient(transport=transport)
    return client


async def _empty_json(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, request=request, json={})


@pytest.mark.asyncio
async def test_submit_text_annotation_reads_json_id_session_id() -> None:
    client = _client_with_text_transport(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={"id": "632A7A61D4B815989FB2"},
            )
        )
    )
    try:
        session_id = await client.submit_text_annotation("MEFV evidence", bioconcept="Gene")
    finally:
        await client.close()

    assert session_id == "632A7A61D4B815989FB2"


@pytest.mark.asyncio
async def test_submit_text_annotation_reads_legacy_content_session_id() -> None:
    client = _client_with_text_transport(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                content=b"632A7A61D4B815989FB2",
                headers={"content-type": "application/octet-stream"},
            )
        )
    )
    try:
        session_id = await client.submit_text_annotation("MEFV evidence", bioconcept="Gene")
    finally:
        await client.close()

    assert session_id == "632A7A61D4B815989FB2"


@pytest.mark.asyncio
async def test_submit_text_annotation_reads_bytes_content_session_id() -> None:
    client = _client_with_text_transport(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                request=request,
                json={"content": "632A7A61D4B815989FB2"},
            )
        )
    )
    try:
        session_id = await client.submit_text_annotation("MEFV evidence", bioconcept="Gene")
    finally:
        await client.close()

    assert session_id == "632A7A61D4B815989FB2"


@pytest.mark.asyncio
async def test_retrieve_text_annotation_retries_transient_upstream_failure(monkeypatch) -> None:
    attempts = 0

    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("pubtator_link.api.retry.random.randint", lambda _start, _end: 0)
    monkeypatch.setattr("pubtator_link.api.retry.asyncio.sleep", no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request, text="try later")
        return httpx.Response(200, request=request, json={"status": "completed"})

    client = _client_with_text_transport(httpx.MockTransport(handler))
    try:
        result = await client.retrieve_text_annotation("632A7A61D4B815989FB2")
    finally:
        await client.close()

    assert result["status"] == "completed"
    assert attempts == RetryPolicy().max_attempts - 1


@pytest.mark.asyncio
async def test_wait_for_text_annotation_respects_timeout_during_retries(monkeypatch) -> None:
    async def no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("pubtator_link.api.retry.asyncio.sleep", no_sleep)

    client = _client_with_text_transport(
        httpx.MockTransport(
            lambda request: httpx.Response(
                503,
                request=request,
                text="try later",
                headers={"retry-after": "5"},
            )
        )
    )
    try:
        result = await client.retrieve_text_annotation_until_ready(
            "632A7A61D4B815989FB2", timeout_ms=1000
        )
    finally:
        await client.close()

    assert result == {
        "status": "upstream_unavailable",
        "retryable": True,
        "message": "PubTator text annotation upstream is unavailable.",
    }
