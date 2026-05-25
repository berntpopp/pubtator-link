"""Body-cap guard for PubTator3Client._make_request (audit 1.6)."""

from __future__ import annotations

import dataclasses
import gzip

import httpx
import pytest

from pubtator_link.api.client import PubTator3Client, PubTatorAPIError
from pubtator_link.config import api_config


def _client_with_transport(transport: httpx.MockTransport, *, cap: int) -> PubTator3Client:
    """Wire a PubTator3Client with a MockTransport and a tight body cap."""
    bounded = dataclasses.replace(api_config, text_max_bytes=cap, pdf_max_bytes=cap)
    client = PubTator3Client(config=bounded)
    client.client = httpx.AsyncClient(transport=transport)
    client.text_client = httpx.AsyncClient(transport=transport)
    return client


@pytest.mark.asyncio
async def test_oversized_content_length_raises_payload_too_large() -> None:
    oversized = 60 * 1024 * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-length": str(oversized),
            },
            content=b'{"ok": true}',
        )

    transport = httpx.MockTransport(handler)
    client = _client_with_transport(transport, cap=5 * 1024 * 1024)
    try:
        with pytest.raises(PubTatorAPIError) as info:
            await client._make_request("GET", "https://example.org/big")
        assert info.value.terminal_reason == "payload_too_large"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_compressed_response_is_not_decoded_twice_after_body_cap() -> None:
    """httpx decodes stream bytes, so rebuilt capped responses must not keep Content-Encoding."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
            content=gzip.compress(b'{"ok": true}'),
        )

    transport = httpx.MockTransport(handler)
    client = _client_with_transport(transport, cap=1024)
    try:
        assert await client._make_request("GET", "https://example.org/compressed") == {"ok": True}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unknown_length_body_exceeding_cap_raises_payload_too_large() -> None:
    """Bodies without Content-Length must also be capped while streamed."""
    cap = 1024

    def handler(request: httpx.Request) -> httpx.Response:
        body = b"x" * (cap * 4)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            stream=httpx.ByteStream(body),
        )

    transport = httpx.MockTransport(handler)
    client = _client_with_transport(transport, cap=cap)
    try:
        with pytest.raises(PubTatorAPIError) as info:
            await client._make_request("GET", "https://example.org/stream")
        assert info.value.terminal_reason == "payload_too_large"
    finally:
        await client.close()
