import pytest

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.services.diagnostics import DiagnosticsService


@pytest.mark.asyncio
async def test_diagnostics_reports_stale_schema_with_recovery() -> None:
    async def inspect_schema() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(
            connected=True,
            current=False,
            applied_versions=["0001_review_schema_base"],
            missing_tables=[],
            missing_columns=["reviews.updated_at"],
        )

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: False,
        pubtator_api_status=lambda: {"status": "ready"},
    )

    response = await service.get_diagnostics()

    assert response.success is True
    assert response.status == "degraded"
    assert response.subsystems["database"]["schema_current"] is False
    assert response.subsystems["pubtator_api"]["status"] == "ready"
    assert "make db-migrate" in response.recovery[0]


@pytest.mark.asyncio
async def test_diagnostics_reports_recent_review_database_tool_error() -> None:
    from pubtator_link.mcp.errors import clear_recent_mcp_errors, record_mcp_error

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator_index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
    )

    async def inspect_schema() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(
            connected=True,
            current=True,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
        )

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: False,
        pubtator_api_status=lambda: {"status": "ready"},
    )

    response = await service.get_diagnostics()

    assert response.status == "degraded"
    assert response.subsystems["recent_mcp_errors"]["count"] == 1
    assert (
        response.subsystems["recent_mcp_errors"]["latest"][0]["error_code"]
        == "review_index_unavailable"
    )
    assert any("pubtator_index_review_evidence" in item for item in response.recovery)


@pytest.mark.asyncio
async def test_diagnostics_reports_pubtator_api_probe_status() -> None:
    async def inspect_schema() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(
            connected=True,
            current=True,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
        )

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: True,
        pubtator_api_status=lambda: {"status": "ready", "probe": "search"},
    )

    response = await service.get_diagnostics()

    assert response.subsystems["pubtator_api"] == {"status": "ready", "probe": "search"}
