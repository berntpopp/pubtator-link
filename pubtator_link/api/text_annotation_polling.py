from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from typing import Any

TRANSIENT_TEXT_ANNOTATION_STATUS_CODES = {408, 429, 500, 502, 503, 504}
PENDING_TEXT_ANNOTATION_STATUSES = {"submitted", "processing", "pending", "queued"}


async def poll_text_annotation_until_ready(
    retrieve: Callable[[str], Any],
    *,
    session_id: str,
    timeout_ms: int,
    is_transient_error: Callable[[Exception], bool],
) -> dict[str, Any] | None:
    deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)
    delay = 0.25
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return None
        try:
            async with asyncio.timeout(remaining):
                result: dict[str, Any] = await retrieve(session_id)
        except TimeoutError:
            return _upstream_unavailable_result()
        except Exception as exc:
            if is_transient_error(exc):
                return _upstream_unavailable_result()
            raise
        if str(result.get("status", "")).lower() not in PENDING_TEXT_ANNOTATION_STATUSES:
            return result
        if asyncio.get_running_loop().time() + delay > deadline:
            return None
        with suppress(TimeoutError):
            async with asyncio.timeout(deadline - asyncio.get_running_loop().time()):
                await asyncio.sleep(delay)
        delay = min(delay * 2, 2.0)


def _upstream_unavailable_result() -> dict[str, Any]:
    return {
        "status": "upstream_unavailable",
        "retryable": True,
        "message": "PubTator text annotation upstream is unavailable.",
    }
