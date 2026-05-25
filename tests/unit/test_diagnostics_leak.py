"""Public pubtator_diagnostics must never leak raw upstream/DB exception text."""

from __future__ import annotations

import json

import pytest

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.mcp.errors import clear_recent_mcp_errors, record_mcp_error
from pubtator_link.services.diagnostics import DiagnosticsService

SENSITIVE_FRAGMENTS = (
    "asyncpg",
    "postgres://",
    "UniqueViolationError",
    "user:password",
    "192.168.",
    "duplicate key",
)


@pytest.mark.asyncio
async def test_get_diagnostics_does_not_leak_raw_exception_text() -> None:
    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator_index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
        raw_message=(
            "asyncpg.exceptions.UniqueViolationError: "
            "duplicate key value violates unique constraint at "
            "postgres://user:password@192.168.1.10:5432/pubtator"
        ),
    )

    async def _inspect() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(
            connected=True,
            current=True,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
        )

    service = DiagnosticsService(
        inspect_schema=_inspect,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: True,
    )
    response = await service.get_diagnostics()
    payload = json.dumps(response.model_dump(), default=str)
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in payload, f"public diagnostics leaked {fragment!r}: {payload!r}"


def test_get_recent_mcp_errors_does_not_expose_raw_message() -> None:
    """The public read API for recent errors must not include raw_message."""
    from pubtator_link.mcp.errors import get_recent_mcp_errors

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator_search_literature",
        error_code="upstream_unavailable",
        message="The upstream service timed out.",
        raw_message="ConnectError: [Errno 111] Connection refused to 10.0.0.5:5432",
    )
    entries = get_recent_mcp_errors()
    assert entries, "expected one recorded entry"
    assert "raw_message" not in entries[0], "raw_message must not be exposed via the public reader"
    assert "10.0.0.5" not in json.dumps(entries)
