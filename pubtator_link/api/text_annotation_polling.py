from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

TRANSIENT_TEXT_ANNOTATION_STATUS_CODES = {408, 429, 500, 502, 503, 504}
PENDING_TEXT_ANNOTATION_STATUSES = {"submitted", "processing", "pending", "queued"}
# retrieve.cgi documents 404 "The Result is not ready"; it answered 400 for a pending session
# (and for an unknown one: the two cannot be told apart) on 2026-11-26.
NOT_READY_TEXT_ANNOTATION_STATUS_CODES = {400, 404}


def parse_pubtator_text_result(content: str) -> dict[str, Any]:
    """A finished job in PubTator format: `id|t|text`, then tab rows id, start, end, text, type, id."""
    original_text = ""
    annotations: list[dict[str, Any]] = []
    for line in content.splitlines():
        if "|t|" in line:
            original_text = line.split("|t|", 1)[1]
        cols = line.split("\t")
        if len(cols) >= 5 and cols[1].isdigit() and cols[2].isdigit():
            annotations.append(
                {
                    "start": int(cols[1]),
                    "end": int(cols[2]),
                    "text": cols[3],
                    "entity_type": cols[4],
                    "entity_id": cols[5] if len(cols) > 5 else "",
                }
            )
    bioconcept = ",".join(sorted({str(a["entity_type"]) for a in annotations}))
    return {
        "status": "completed",
        "original_text": original_text,
        "bioconcept": bioconcept,
        "annotations": annotations,
    }


async def retrieve_text_annotation_result(
    request: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """One retrieve.cgi call as `{status, ...}`: not-ready is `processing`, text is parsed."""
    try:
        response = await request()
    except Exception as exc:
        if getattr(exc, "status_code", None) in NOT_READY_TEXT_ANNOTATION_STATUS_CODES:
            return {"status": "processing"}
        raise
    content = response.get("content")
    return parse_pubtator_text_result(content) if isinstance(content, str) else response


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
