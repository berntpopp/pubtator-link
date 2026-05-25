import socket
from types import TracebackType
from typing import Any

import httpx
import pytest
import respx

from pubtator_link.config import ReviewReragConfig
from pubtator_link.services.url_safety import SafeUrlFetcher, UrlSafetyError

UNSPECIFIED_IPV4 = ".".join(["0", "0", "0", "0"])


def _config(*, allow_http_urls: bool = False, pdf_max_bytes: int = 32) -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=60,
        source_timeout_seconds=5,
        pdf_max_bytes=pdf_max_bytes,
        text_max_bytes=32,
        allow_http_urls=allow_http_urls,
        enable_docling=False,
        curated_url_host_allowlist=("example.test",),
    )


def _public_dns(monkeypatch: pytest.MonkeyPatch, ip_address: str = "93.184.216.34") -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip_address, 443))
        ],
    )


@pytest.mark.asyncio
async def test_rejects_unsupported_scheme() -> None:
    fetcher = SafeUrlFetcher(_config())

    with pytest.raises(UrlSafetyError, match="Unsupported URL scheme"):
        await fetcher.fetch("ftp://example.test/source.pdf")


@pytest.mark.asyncio
async def test_rejects_http_url_unless_config_allows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _public_dns(monkeypatch)

    with pytest.raises(UrlSafetyError, match="HTTP URLs are disabled"):
        await SafeUrlFetcher(_config()).fetch("http://example.test/source.pdf")

    with respx.mock:
        respx.get("http://example.test/source.pdf").mock(
            return_value=httpx.Response(
                200,
                headers={"content-type": "application/pdf"},
                content=b"%PDF-1.7\nok",
            )
        )

        body, content_type = await SafeUrlFetcher(_config(allow_http_urls=True)).fetch(
            "http://example.test/source.pdf"
        )

    assert body == b"%PDF-1.7\nok"
    assert content_type == "application/pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ip_address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",
        UNSPECIFIED_IPV4,
        "224.0.0.1",
        "240.0.0.1",
    ],
)
async def test_rejects_unsafe_resolved_ip_addresses(
    monkeypatch: pytest.MonkeyPatch, ip_address: str
) -> None:
    _public_dns(monkeypatch, ip_address)

    with pytest.raises(UrlSafetyError, match="unsafe IP address"):
        await SafeUrlFetcher(_config()).fetch("https://example.test/source.pdf")


@pytest.mark.asyncio
async def test_rejects_content_length_over_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)

    with respx.mock:
        respx.get("https://example.test/large.pdf").mock(
            return_value=httpx.Response(
                200,
                headers={"content-length": "33", "content-type": "application/pdf"},
                content=b"",
            )
        )

        with pytest.raises(UrlSafetyError, match="Content-Length exceeds"):
            await SafeUrlFetcher(_config(pdf_max_bytes=32)).fetch("https://example.test/large.pdf")


@pytest.mark.asyncio
async def test_accepts_small_pdf_body(monkeypatch: pytest.MonkeyPatch) -> None:
    _public_dns(monkeypatch)
    pdf_body = b"%PDF-1.7\nsmall\n%%EOF"

    with respx.mock:
        respx.get("https://example.test/small.pdf").mock(
            return_value=httpx.Response(
                200,
                headers={
                    "content-length": str(len(pdf_body)),
                    "content-type": "application/pdf; charset=binary",
                },
                content=pdf_body,
            )
        )

        body, content_type = await SafeUrlFetcher(_config()).fetch("https://example.test/small.pdf")

    assert body == pdf_body
    assert content_type == "application/pdf; charset=binary"


@pytest.mark.asyncio
async def test_fetch_disables_httpx_environment_proxy_trust(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _public_dns(monkeypatch)
    captured_kwargs: dict[str, Any] = {}

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            captured_kwargs.update(kwargs)

        async def __aenter__(self) -> "RecordingClient":
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

        def stream(self, _method: str, _url: str) -> Any:
            class StreamContext:
                async def __aenter__(self) -> httpx.Response:
                    return httpx.Response(
                        200,
                        headers={"content-type": "application/pdf"},
                        content=b"%PDF-1.7\nok",
                    )

                async def __aexit__(
                    self,
                    exc_type: type[BaseException] | None,
                    exc: BaseException | None,
                    traceback: TracebackType | None,
                ) -> None:
                    return None

            return StreamContext()

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)

    body, _content_type = await SafeUrlFetcher(_config()).fetch("https://example.test/paper.pdf")

    assert body == b"%PDF-1.7\nok"
    assert captured_kwargs["trust_env"] is False
