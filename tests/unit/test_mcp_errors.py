import ast
import json
import logging
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from pubtator_link.mcp.errors import (
    McpErrorContext,
    error_code_for_exception,
    mcp_tool_error,
    sanitize_error_message,
)
from pubtator_link.services.errors import (
    ReviewIndexUnavailableError,
    ReviewSchemaStaleError,
    UpstreamUnavailableError,
    ValidationFailureError,
)


def test_sanitize_error_message_removes_database_details() -> None:
    message = 'column "updated_at" of relation "reviews" does not exist'

    assert sanitize_error_message(message) == "Review database schema is not current."


def test_mcp_tool_error_serializes_recovery_envelope() -> None:
    error = mcp_tool_error(
        RuntimeError('column "updated_at" of relation "reviews" does not exist'),
        McpErrorContext(
            tool_name="pubtator.index_review_evidence",
            pmids=["39540697"],
        ),
    )

    assert isinstance(error, ToolError)
    payload = json.loads(str(error))
    assert payload["error_code"] == "review_schema_not_current"
    assert payload["fallback_tool"] == "pubtator.get_publication_passages"
    assert payload["fallback_args"]["pmids"] == ["39540697"]
    assert "updated_at" not in payload["message"]


def test_error_code_for_typed_review_errors() -> None:
    assert error_code_for_exception(ReviewSchemaStaleError("schema stale")) == (
        "review_schema_not_current"
    )
    assert error_code_for_exception(ReviewIndexUnavailableError("db unavailable")) == (
        "review_index_unavailable"
    )
    assert error_code_for_exception(UpstreamUnavailableError("timeout")) == ("upstream_unavailable")
    assert error_code_for_exception(ValidationFailureError("bad input")) == ("validation_failed")


def test_error_code_legacy_schema_text_fallback_still_works() -> None:
    assert error_code_for_exception(RuntimeError("column updated_at missing from reviews")) == (
        "review_schema_not_current"
    )


def test_mcp_tool_error_includes_bounded_diagnostics_snapshot() -> None:
    error = mcp_tool_error(
        RuntimeError("relation review_passages is unavailable"),
        McpErrorContext(
            tool_name="pubtator.index_review_evidence",
            pmids=["35042149", "39540697"],
            diagnostics_snapshot={
                "database": {
                    "status": "ready",
                    "schema_current": True,
                    "missing_tables": [],
                    "missing_columns": [],
                },
                "review_index": {
                    "review_id": "fmf-vus",
                    "known_sources": 2,
                    "prepared_sources": 0,
                    "failed_sources": 2,
                },
                "recovery_hint": "Continue with abstract_only fallback.",
            },
            degraded_mode="index_unavailable",
            fallback_preview={
                "tool": "pubtator.get_publication_passages",
                "mode": "compact_passages",
                "source_count": 2,
                "degraded_mode": "abstract_only",
                "coverage_by_pmid": {"35042149": "abstract_only"},
            },
        ),
    )

    payload = json.loads(str(error))

    assert payload["degraded_mode"] == "index_unavailable"
    assert payload["diagnostics_snapshot"]["database"]["schema_current"] is True
    assert payload["fallback_preview"]["source_count"] == 2
    assert len(json.dumps(payload["diagnostics_snapshot"])) < 2048


def test_public_mcp_tools_use_centralized_error_wrapper() -> None:
    tool_files = [
        Path("pubtator_link/mcp/metadata.py"),
        *sorted(Path("pubtator_link/mcp/tools").glob("*.py")),
    ]
    missing: list[str] = []

    for path in tool_files:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            if not _is_mcp_tool(node):
                continue
            if not any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "run_mcp_tool"
                for call in ast.walk(node)
            ):
                missing.append(f"{path}:{node.name}")

    assert missing == []


def test_recent_mcp_errors_are_bounded_and_clearable() -> None:
    from pubtator_link.mcp.errors import (
        RECENT_MCP_ERROR_LIMIT,
        clear_recent_mcp_errors,
        get_recent_mcp_errors,
        record_mcp_error,
    )

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator.index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
        raw_message="relation review_sources does not exist",
    )

    errors = get_recent_mcp_errors()

    assert errors[-1]["tool_name"] == "pubtator.index_review_evidence"
    assert errors[-1]["error_code"] == "review_index_unavailable"
    assert "relation review_sources does not exist" in errors[-1]["raw_message"]

    for index in range(RECENT_MCP_ERROR_LIMIT + 5):
        record_mcp_error(
            tool_name=f"pubtator.test_tool_{index}",
            error_code="internal_error",
            message="The tool could not complete the requested operation.",
        )

    errors = get_recent_mcp_errors(limit=RECENT_MCP_ERROR_LIMIT + 10)

    assert len(errors) == RECENT_MCP_ERROR_LIMIT
    assert errors[0]["tool_name"] == "pubtator.test_tool_5"
    assert errors[-1]["tool_name"] == "pubtator.test_tool_54"

    clear_recent_mcp_errors()

    assert get_recent_mcp_errors() == []


def test_record_mcp_error_sanitizes_stored_message() -> None:
    from pubtator_link.mcp.errors import (
        clear_recent_mcp_errors,
        get_recent_mcp_errors,
        record_mcp_error,
    )

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator.index_review_evidence",
        error_code="review_index_unavailable",
        message='relation "review_sources" does not exist',
        raw_message='relation "review_sources" does not exist at host db.internal',
    )

    errors = get_recent_mcp_errors()

    assert errors[-1]["message"] == "Review database operation failed."
    assert "db.internal" in errors[-1]["raw_message"]


@pytest.mark.asyncio
async def test_mcp_error_wrapper_raises_tool_error() -> None:
    from pubtator_link.mcp.errors import run_mcp_tool

    async def failing() -> dict[str, object]:
        raise RuntimeError('column "updated_at" of relation "reviews" does not exist')

    with pytest.raises(ToolError) as exc_info:
        await run_mcp_tool(
            "pubtator.index_review_evidence",
            failing,
            pmids=["39540697"],
        )

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "review_schema_not_current"


@pytest.mark.asyncio
async def test_mcp_error_wrapper_preserves_input_normalization_details() -> None:
    from pubtator_link.mcp.errors import run_mcp_tool
    from pubtator_link.mcp.input_normalization import InputNormalizationError

    field_errors = [
        {
            "field": "max_total_passages",
            "message": "Ambiguous arguments: provide only one of max_total_passages, limit.",
        }
    ]
    recovery_hint = "Use either max_total_passages or limit, not both."

    async def failing() -> dict[str, object]:
        raise InputNormalizationError(field_errors=field_errors, recovery_hint=recovery_hint)

    with pytest.raises(ToolError) as exc_info:
        await run_mcp_tool("pubtator.retrieve_review_context_batch", failing)

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "validation_failed"
    assert payload["field_errors"] == field_errors
    assert payload["recovery_hint"] == recovery_hint
    assert payload["message"] == "Invalid MCP arguments."


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_preserves_json_tool_error_code_in_recent_errors_and_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pubtator_link.mcp.errors import (
        clear_recent_mcp_errors,
        get_recent_mcp_errors,
        run_mcp_tool,
    )
    from pubtator_link.observability.metrics import metrics_payload

    async def failing() -> dict[str, object]:
        raise mcp_tool_error(
            RuntimeError('column "updated_at" of relation "reviews" does not exist'),
            McpErrorContext(tool_name="pubtator.index_review_evidence"),
        )

    clear_recent_mcp_errors()
    caplog.set_level(logging.WARNING, logger="pubtator_link.mcp.errors")

    with pytest.raises(ToolError):
        await run_mcp_tool("pubtator.index_review_evidence", failing)

    errors = get_recent_mcp_errors()
    failed_records = [record for record in caplog.records if record.message == "mcp_tool_failed"]
    metrics = metrics_payload().decode()

    assert errors[-1]["error_code"] == "review_schema_not_current"
    assert errors[-1]["message"] == "Review database schema is not current."
    assert failed_records[-1].error_code == "review_schema_not_current"
    assert (
        'mcp_tool_calls_total{error_code="review_schema_not_current",'
        'outcome="failure",tool_name="pubtator.index_review_evidence"}'
    ) in metrics


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_emits_lifecycle_logs_and_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pubtator_link.mcp.errors import run_mcp_tool
    from pubtator_link.observability.metrics import metrics_payload

    async def successful() -> dict[str, object]:
        return {"ok": True}

    caplog.set_level(logging.INFO, logger="pubtator_link.mcp.errors")

    result = await run_mcp_tool("pubtator.test_tool", successful, pmids=["1", "2"])

    assert result == {"ok": True}
    messages = [record.message for record in caplog.records]
    assert "mcp_tool_started" in messages
    assert "mcp_tool_completed" in messages
    metrics = metrics_payload().decode()
    assert (
        'mcp_tool_calls_total{error_code="",outcome="success",tool_name="pubtator.test_tool"}'
        in metrics
    )


def _is_mcp_tool(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    for decorator in node.decorator_list:
        if (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "tool"
        ):
            return True
    return False
