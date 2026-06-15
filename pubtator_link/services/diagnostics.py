from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.mcp.errors import get_recent_mcp_errors
from pubtator_link.models.responses import DiagnosticsResponse


class DiagnosticsService:
    """Report subsystem status and recovery commands for LLM consumers."""

    def __init__(
        self,
        *,
        inspect_schema: Callable[[], Awaitable[ReviewSchemaDiagnostics]],
        review_queue_available: Callable[[], bool],
        europe_pmc_enabled: Callable[[], bool],
        pubtator_api_status: Callable[[], dict[str, Any] | Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        self._inspect_schema = inspect_schema
        self._review_queue_available = review_queue_available
        self._europe_pmc_enabled = europe_pmc_enabled
        self._pubtator_api_status = pubtator_api_status

    async def get_diagnostics(self) -> DiagnosticsResponse:
        recovery: list[str] = []
        schema = await self._inspect_schema()
        pubtator_api = await self._probe_pubtator_api()
        recent_errors = get_recent_mcp_errors()
        database: dict[str, Any] = {
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

        subsystems: dict[str, dict[str, Any]] = {
            "database": database,
            "review_queue": {"available": self._review_queue_available()},
            "pubtator_api": pubtator_api,
            "europe_pmc": {"enabled": self._europe_pmc_enabled()},
            "recent_mcp_errors": {"count": len(recent_errors), "latest": recent_errors},
        }
        review_error_prefixes = (
            "index_review",
            "stage_research_session",
            "get_review_context",
            "export_review_audit_bundle",
        )
        recent_review_errors = [
            error
            for error in recent_errors
            if str(error.get("tool_name", "")).startswith(review_error_prefixes)
        ]
        for error in recent_review_errors:
            tool_name = error["tool_name"]
            reason = error.get("message", "see logs for details")
            recovery.append(f"Recent MCP tool failure in {tool_name}: {reason}")
        if not database["connected"]:
            status = "not_ready"
        elif not database["schema_current"] or recent_review_errors:
            status = "degraded"
        else:
            status = "ready"

        minimum_workflow: dict[str, Any] = {
            "grounded_review": [
                "search_literature",
                "preflight_review_sources",
                "index_review_evidence",
                "inspect_review_index",
                "get_review_context_batch",
            ],
            "one_call": "ground_question",
            "workflow_resource": "pubtator://workflow-help",
        }

        return DiagnosticsResponse(
            success=True,
            status=status,
            subsystems=subsystems,
            recovery=recovery,
            minimum_workflow=minimum_workflow,
        )

    async def _probe_pubtator_api(self) -> dict[str, Any]:
        if self._pubtator_api_status is None:
            return {"status": "unknown", "probe": "not_configured"}
        try:
            status = self._pubtator_api_status()
            if inspect.isawaitable(status):
                status = await status
            if not isinstance(status, dict):
                raise TypeError("pubtator api status probe must return a dict")
            if not isinstance(status.get("status"), str):
                raise TypeError("pubtator api status probe must include a status string")
            return status
        except Exception as exc:
            return {"status": "unavailable", "probe": "search", "error": type(exc).__name__}
