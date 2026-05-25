"""Bound checks for every literature-provider httpx.AsyncClient (audit 1.4)."""

from __future__ import annotations

import httpx
import pytest

from pubtator_link.services.literature_providers import (
    CrossrefClient,
    EuropePmcLiteratureClient,
    OpenAlexClient,
    UnpaywallClient,
)


def _assert_bounded(client: httpx.AsyncClient) -> None:
    """Assert explicit hosted-safe bounds instead of httpx library defaults."""
    assert client.timeout.connect is not None
    assert client.timeout.connect <= 10.0
    assert client.timeout.read is not None
    assert client.timeout.read <= 60.0
    # httpx exposes no public limits view, so this test pins the private
    # pool attributes that would otherwise silently inherit library defaults.
    pool = client._transport._pool
    assert pool._max_connections <= 50
    assert pool._max_keepalive_connections <= 10
    assert client.headers["user-agent"].startswith("PubTator-Link/")


@pytest.mark.parametrize(
    "factory",
    [
        lambda: CrossrefClient(mailto="ops@example.com"),
        lambda: EuropePmcLiteratureClient(),
        lambda: OpenAlexClient(mailto="ops@example.com"),
        lambda: UnpaywallClient(email="ops@example.com"),
    ],
)
def test_default_client_has_finite_timeout(factory) -> None:
    instance = factory()
    _assert_bounded(instance._client)


def test_upstream_http_helper_returns_bounded_client_with_limits() -> None:
    """The shared helper itself must always produce a Limits-bound client."""
    from pubtator_link.services.upstream_http import (
        DEFAULT_LIMITS,
        default_async_client,
    )

    assert DEFAULT_LIMITS.max_connections is not None
    assert DEFAULT_LIMITS.max_connections <= 50
    client = default_async_client()
    assert client.timeout.connect is not None
