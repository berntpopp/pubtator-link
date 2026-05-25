"""Hostname allowlist enforcement in SafeUrlFetcher (audit 1.3)."""

from __future__ import annotations

import dataclasses
import socket

import pytest

from pubtator_link.config import ReviewReragConfig, ServerSettings
from pubtator_link.services.url_safety import (
    SafeUrlFetcher,
    UrlSafetyError,
    enforce_host_allowlist,
)


def _config_with_allowlist(*allowed: str) -> ReviewReragConfig:
    """Build a fully-valid ReviewReragConfig with the given allowlist."""
    base = ReviewReragConfig.from_settings(ServerSettings())
    return dataclasses.replace(
        base,
        curated_url_host_allowlist=tuple(allowed),
        allow_http_urls=False,
    )


@pytest.mark.parametrize(
    "hostname",
    [
        "evil.example.com",
        "ncbi.nlm.nih.gov.evil.com",
        "127.0.0.1",
    ],
)
def test_enforce_host_allowlist_rejects_unlisted(hostname: str) -> None:
    with pytest.raises(UrlSafetyError) as info:
        enforce_host_allowlist(("ncbi.nlm.nih.gov",), hostname)
    assert "not in allowlist" in str(info.value).lower()


@pytest.mark.parametrize(
    "hostname",
    [
        "ncbi.nlm.nih.gov",
        "www.ncbi.nlm.nih.gov",
        "pubmed.ncbi.nlm.nih.gov",
        "NCBI.NLM.NIH.GOV",
    ],
)
def test_enforce_host_allowlist_accepts_exact_and_subdomains(hostname: str) -> None:
    enforce_host_allowlist(("ncbi.nlm.nih.gov",), hostname)


def test_enforce_host_allowlist_empty_rejects_everything() -> None:
    with pytest.raises(UrlSafetyError):
        enforce_host_allowlist((), "ncbi.nlm.nih.gov")


def test_validate_url_rejects_disallowed_host_before_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowlist must run before DNS - verified by getaddrinfo call counter."""
    call_log: list[str] = []

    def _track(*args, **kwargs):
        call_log.append(args[0] if args else "")
        raise AssertionError("DNS must not be consulted for a rejected host")

    monkeypatch.setattr(socket, "getaddrinfo", _track)
    fetcher = SafeUrlFetcher(_config_with_allowlist("ncbi.nlm.nih.gov"))
    with pytest.raises(UrlSafetyError) as info:
        fetcher._validate_url("https://evil.example.com/x")
    assert "not in allowlist" in str(info.value).lower()
    assert call_log == [], f"DNS was consulted before allowlist: {call_log}"
