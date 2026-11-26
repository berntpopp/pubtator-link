"""NCBI API key + shared E-utilities token bucket (#275)."""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest
import structlog
from pydantic import SecretStr

from pubtator_link.config import settings
from pubtator_link.logging_config import stdlib_formatter
from pubtator_link.services import ncbi_eutils_rate
from pubtator_link.services.ncbi_discovery import NcbiDiscoveryClient
from pubtator_link.services.publication_metadata import NcbiPublicationMetadataClient

KEY = "abc123secretkey0000000000000000000"


@pytest.fixture(autouse=True)
def _private_rate_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep this file's timing assertions away from other xdist workers' requests.
    monkeypatch.setattr(ncbi_eutils_rate, "RATE_FILE", tmp_path / "ncbi.rate")
    monkeypatch.setattr(ncbi_eutils_rate, "_limiter", None)


def test_bucket_is_3_per_second_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", None)
    limiter = ncbi_eutils_rate.eutils_rate_limiter()
    assert limiter.rate == 3.0
    assert ncbi_eutils_rate.eutils_rate_limiter() is limiter  # one process-wide bucket
    assert ncbi_eutils_rate.ncbi_api_key_params() == {}


def test_bucket_is_10_per_second_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    assert ncbi_eutils_rate.eutils_rate_limiter().rate == 10.0


async def test_bucket_spaces_requests_at_the_configured_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", None)
    waits = [await ncbi_eutils_rate.eutils_rate_limiter().acquire() for _ in range(3)]
    assert waits[0] == 0.0
    assert all(wait == pytest.approx(1 / 3, abs=0.05) for wait in waits[1:])


async def test_key_is_sent_as_param_but_never_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"result": {"uids": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await NcbiPublicationMetadataClient(http_client=http).fetch_esummary(["1"])
    assert seen[0].params["api_key"] == KEY

    # The exact line httpx emits at INFO for every request, rendered by our formatter.
    record = logging.getLogger("httpx").makeRecord(
        "httpx", logging.INFO, __file__, 1, "HTTP Request: %s %s", ("GET", seen[0]), None
    )
    logged = stdlib_formatter(structlog.processors.JSONRenderer()).format(record)
    assert "esummary.fcgi" in logged
    assert KEY not in logged
    assert "[REDACTED]" in logged


async def test_key_is_absent_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", None)
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"result": {"uids": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await NcbiPublicationMetadataClient(http_client=http).fetch_esummary(["1"])
    assert "api_key" not in seen[0].params


async def test_id_converter_requests_carry_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"records": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await NcbiDiscoveryClient(http_client=http).map_article_ids(["PMC1"], source="auto")
    assert seen[0].host == "pmc.ncbi.nlm.nih.gov"
    assert seen[0].params["api_key"] == KEY


@pytest.mark.parametrize("key", [None, SecretStr(KEY)])
def test_health_reports_has_api_key_never_the_value(
    monkeypatch: pytest.MonkeyPatch, key: SecretStr | None
) -> None:
    from fastapi.testclient import TestClient

    from pubtator_link.server_manager import UnifiedServerManager

    monkeypatch.setattr(settings, "ncbi_api_key", key)
    response = TestClient(UnifiedServerManager().create_app(include_mcp=False)).get("/health")
    assert response.json()["has_api_key"] is (key is not None)
    assert KEY not in response.text


_WORKER = textwrap.dedent(
    """
    import asyncio, sys, time
    from pathlib import Path
    from pubtator_link.services.ncbi_eutils_rate import SharedRateLimiter

    async def main():
        limiter = SharedRateLimiter(rate=10.0, path=Path(sys.argv[1]))
        print("ready", flush=True)
        sys.stdin.readline()
        for _ in range(10):
            await limiter.acquire()
            print(time.time(), flush=True)

    asyncio.run(main())
    """
)


def test_two_processes_share_one_bucket(tmp_path: Path) -> None:
    """Two worker processes together stay at 10 req/s (unshared they would do 20)."""
    procs = [
        subprocess.Popen(  # noqa: S603 - fixed argv, our own interpreter
            [sys.executable, "-c", _WORKER, str(tmp_path / "shared.rate")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    for proc in procs:  # both imported and waiting, so their acquires overlap
        assert proc.stdout is not None and proc.stdout.readline().strip() == "ready"
    for proc in procs:
        assert proc.stdin is not None
        proc.stdin.write("go\n")
        proc.stdin.flush()
    stamps: list[float] = []
    for proc in procs:
        stamps += map(float, proc.communicate(timeout=30)[0].split())
    stamps.sort()
    assert len(stamps) == 20
    # Never more than 10 grants in any 1 s window across both processes.
    assert min(b - a for a, b in zip(stamps, stamps[10:], strict=False)) >= 0.95
    assert stamps[-1] - stamps[0] >= 1.85


async def test_unusable_rate_file_falls_back_to_process_bucket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "ncbi_api_key", SecretStr(KEY))
    monkeypatch.setattr(ncbi_eutils_rate, "RATE_FILE", tmp_path / "missing-dir" / "x.rate")
    limiter = ncbi_eutils_rate.eutils_rate_limiter()
    with caplog.at_level(logging.WARNING):
        waits = [await limiter.acquire() for _ in range(2)]
    assert waits[0] == 0.0
    assert waits[1] == pytest.approx(1 / 10, abs=0.05)  # still throttled
    assert "falling back to a per-process bucket" in caplog.text
    assert KEY not in caplog.text
