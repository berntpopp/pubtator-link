"""NCBI API key + shared E-utilities token bucket (#275)."""

from __future__ import annotations

import io
import logging

import httpx
import pytest
import structlog
from pydantic import SecretStr

from pubtator_link.config import settings
from pubtator_link.logging_config import stdlib_formatter
from pubtator_link.services import ncbi_eutils_rate
from pubtator_link.services.publication_metadata import NcbiPublicationMetadataClient

KEY = "abc123secretkey0000000000000000000"


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUNICORN_WORKERS", "1")


def test_bucket_is_3_per_second_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", None)
    limiter = ncbi_eutils_rate.eutils_rate_limiter()
    assert limiter.rate == 3.0
    assert limiter.burst == 1.0
    assert ncbi_eutils_rate.eutils_rate_limiter() is limiter  # one process-wide bucket
    assert ncbi_eutils_rate.ncbi_api_key_params() == {}


def test_bucket_is_10_per_second_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    assert ncbi_eutils_rate.eutils_rate_limiter().rate == 10.0


def test_bucket_splits_the_per_ip_rate_across_gunicorn_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GUNICORN_WORKERS", "4")
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    assert ncbi_eutils_rate.eutils_rate_limiter().rate == 2.5


async def test_bucket_spaces_requests_at_the_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", None)
    monkeypatch.setattr(ncbi_eutils_rate, "_limiter", None)
    waits = [await ncbi_eutils_rate.eutils_rate_limiter().acquire() for _ in range(3)]
    assert waits[0] == 0.0
    assert all(wait == pytest.approx(1 / 3, abs=0.05) for wait in waits[1:])


async def test_key_is_sent_as_param_but_never_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"result": {"uids": []}})

    stream = io.StringIO()
    log_handler = logging.StreamHandler(stream)
    log_handler.setFormatter(stdlib_formatter(structlog.processors.JSONRenderer()))
    httpx_logger = logging.getLogger("httpx")
    httpx_logger.addHandler(log_handler)
    monkeypatch.setattr(httpx_logger, "level", logging.INFO)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await NcbiPublicationMetadataClient(http_client=http).fetch_esummary(["1"])
    finally:
        httpx_logger.removeHandler(log_handler)

    assert seen[0].params["api_key"] == KEY
    logged = stream.getvalue()
    assert "HTTP Request" in logged  # httpx did log the URL...
    assert KEY not in logged  # ...with the key scrubbed
    assert "[REDACTED]" in logged
