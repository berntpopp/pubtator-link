"""Process-wide NCBI E-utilities rate limit and optional API key (#275).

NCBI allows 3 requests/s per IP without an API key and 10/s with one
(https://www.ncbi.nlm.nih.gov/books/NBK25497/). Every E-utilities caller in
this container shares ONE bucket -- an fcntl-locked file on the shared /tmp --
so neither concurrent tools nor Gunicorn workers can jointly exceed it.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from pubtator_link.api.client import RateLimiter
from pubtator_link.config import settings

KEYLESS_RATE_PER_SECOND = 3.0
KEYED_RATE_PER_SECOND = 10.0

RATE_FILE = Path(tempfile.gettempdir()) / "pubtator-link-ncbi-eutils.rate"

logger = logging.getLogger(__name__)


class SharedRateLimiter:
    """Strict 1/rate spacing shared by every process that opens ``path``.

    The file holds the next free slot (epoch seconds). Each acquire claims a slot
    under ``flock`` and sleeps until it; if the file is unusable, the per-process
    bucket is used instead.
    """

    def __init__(self, rate: float, path: Path | None = None) -> None:
        self.rate = rate
        self.path = path or RATE_FILE
        self._fallback = RateLimiter(rate=rate)
        self._warned = False

    def _reserve(self) -> float:
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            now = time.time()
            try:
                stored = float(os.pread(fd, 64, 0) or 0)
            except ValueError:
                stored = 0.0
            # A slot >5 min ahead is a backward clock jump, not a queue (clients time out at 60 s).
            slot = max(now, stored) if stored < now + 300 else now
            os.ftruncate(fd, 0)
            os.pwrite(fd, f"{slot + 1 / self.rate:.6f}".encode(), 0)
            return slot - now
        finally:
            os.close(fd)  # also releases the flock

    async def acquire(self) -> float:
        try:
            wait = await asyncio.to_thread(self._reserve)
        except OSError as exc:
            if not self._warned:
                self._warned = True
                logger.warning(
                    "NCBI rate file %s unusable (%s); falling back to a per-process bucket",
                    self.path,
                    type(exc).__name__,
                )
            return await self._fallback.acquire()
        if wait > 0:
            await asyncio.sleep(wait)
        return wait


_limiter: SharedRateLimiter | None = None


def ncbi_api_key_params() -> dict[str, str]:
    """``{"api_key": ...}`` when ``NCBI_API_KEY`` is set, else ``{}``."""
    key = settings.ncbi_api_key
    return {"api_key": key.get_secret_value()} if key else {}


def eutils_rate_limiter() -> SharedRateLimiter:
    global _limiter
    rate = KEYED_RATE_PER_SECOND if settings.ncbi_api_key else KEYLESS_RATE_PER_SECOND
    # ponytail: shared per host /tmp, i.e. per container; replicas on one egress IP
    # would each get the full rate. Move to Postgres if the service is ever scaled out.
    if _limiter is None or _limiter.rate != rate:
        _limiter = SharedRateLimiter(rate=rate)
    return _limiter


async def eutils_get(client: Any, url: str, *, params: Any, **kwargs: Any) -> Any:
    """``client.get`` throttled by the shared bucket, with the API key added when set."""
    await eutils_rate_limiter().acquire()
    query = httpx.QueryParams(params).merge(ncbi_api_key_params())
    return await client.get(url, params=query, **kwargs)
