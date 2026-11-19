"""Process-wide NCBI E-utilities rate limit and optional API key (#275).

NCBI allows 3 requests/s per IP without an API key and 10/s with one
(https://www.ncbi.nlm.nih.gov/books/NBK25497/). Every E-utilities caller in
this process shares ONE token bucket so concurrent tools cannot jointly exceed it.
Gunicorn forks GUNICORN_WORKERS processes behind one egress IP, so each worker's
bucket gets an equal share of NCBI's per-IP rate.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from pubtator_link.api.client import RateLimiter
from pubtator_link.config import settings

KEYLESS_RATE_PER_SECOND = 3.0
KEYED_RATE_PER_SECOND = 10.0

_limiter: RateLimiter | None = None


def ncbi_api_key_params() -> dict[str, str]:
    """``{"api_key": ...}`` when ``PUBTATOR_LINK_NCBI_API_KEY`` is set, else ``{}``."""
    key = settings.ncbi_api_key
    return {"api_key": key.get_secret_value()} if key else {}


def eutils_rate_limiter() -> RateLimiter:
    global _limiter
    rate = KEYED_RATE_PER_SECOND if settings.ncbi_api_key else KEYLESS_RATE_PER_SECOND
    # Same default as docker/gunicorn_conf.py; a single-process dev run is merely slower.
    rate /= max(1, int(os.environ.get("GUNICORN_WORKERS", "2")))
    if _limiter is None or _limiter.rate != rate:
        _limiter = RateLimiter(rate=rate)
    return _limiter


async def eutils_get(client: Any, url: str, *, params: Any, **kwargs: Any) -> Any:
    """``client.get`` throttled by the shared bucket, with the API key added when set."""
    await eutils_rate_limiter().acquire()
    query = httpx.QueryParams(params).merge(ncbi_api_key_params())
    return await client.get(url, params=query, **kwargs)
