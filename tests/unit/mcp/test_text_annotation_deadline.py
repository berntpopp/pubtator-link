from __future__ import annotations

import asyncio

import pytest

from pubtator_link.mcp.tools.text_annotations import retrieve_annotation_result_with_deadline


@pytest.mark.asyncio
async def test_annotation_result_deadline_bounds_a_slow_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pubtator_link.mcp.tools.text_annotations.ANNOTATION_RESULT_DEADLINE_SECONDS", 0.001
    )

    async def slow_retrieve() -> dict[str, str]:
        await asyncio.sleep(1)
        return {"status": "completed"}

    with pytest.raises(TimeoutError):
        await retrieve_annotation_result_with_deadline(slow_retrieve)
