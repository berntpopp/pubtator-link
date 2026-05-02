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
    )

    response = await service.get_diagnostics()

    assert response.success is True
    assert response.status == "degraded"
    assert response.subsystems["database"]["schema_current"] is False
    assert "make db-migrate" in response.recovery[0]
