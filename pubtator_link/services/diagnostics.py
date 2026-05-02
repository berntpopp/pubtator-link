from __future__ import annotations

from collections.abc import Awaitable, Callable

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.models.responses import DiagnosticsResponse


class DiagnosticsService:
    """Report subsystem status and recovery commands for LLM consumers."""

    def __init__(
        self,
        *,
        inspect_schema: Callable[[], Awaitable[ReviewSchemaDiagnostics]],
        review_queue_available: Callable[[], bool],
        europe_pmc_enabled: Callable[[], bool],
    ) -> None:
        self._inspect_schema = inspect_schema
        self._review_queue_available = review_queue_available
        self._europe_pmc_enabled = europe_pmc_enabled

    async def get_diagnostics(self) -> DiagnosticsResponse:
        recovery: list[str] = []
        schema = await self._inspect_schema()
        database = {
            "connected": schema.connected,
            "schema_current": schema.current,
            "applied_versions": schema.applied_versions,
            "missing_tables": schema.missing_tables,
            "missing_columns": schema.missing_columns,
            "error": schema.error,
        }
        if schema.connected and not schema.current:
            recovery.append(
                "Run make db-migrate with PUBTATOR_LINK_DATABASE_URL set, then restart or retry."
            )
        if not schema.connected:
            recovery.append("Configure PUBTATOR_LINK_DATABASE_URL or check database connectivity.")

        subsystems = {
            "database": database,
            "review_queue": {"available": self._review_queue_available()},
            "pubtator_api": {"status": "unknown"},
            "europe_pmc": {"enabled": self._europe_pmc_enabled()},
        }
        if not database["connected"]:
            status = "not_ready"
        elif not database["schema_current"]:
            status = "degraded"
        else:
            status = "ready"

        return DiagnosticsResponse(
            success=True,
            status=status,
            subsystems=subsystems,
            recovery=recovery,
        )
