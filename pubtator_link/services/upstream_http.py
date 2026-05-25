"""Shared defaults for outbound httpx.AsyncClient instances.

Centralizes the timeout and connection-pool bounds used by literature
provider clients (1.4) and the PubTator client streaming guard (1.6).
"""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
DEFAULT_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


def default_async_client(
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    limits: httpx.Limits | None = None,
) -> httpx.AsyncClient:
    """Return an httpx.AsyncClient with bounded timeout + connection pool."""
    return httpx.AsyncClient(
        timeout=timeout or DEFAULT_TIMEOUT,
        limits=limits or DEFAULT_LIMITS,
        headers=headers,
    )
