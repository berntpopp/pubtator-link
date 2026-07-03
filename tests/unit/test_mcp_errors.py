import ast
import json
import logging
from pathlib import Path

import pytest

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.mcp.errors import (
    McpErrorContext,
    error_code_for_exception,
    mcp_tool_error,
    run_mcp_tool,
    sanitize_error_message,
)
from pubtator_link.mcp.validation_errors import extract_validation_details
from pubtator_link.services.errors import (
    ReviewIndexUnavailableError,
    ReviewSchemaStaleError,
    UpstreamUnavailableError,
    ValidationFailureError,
)


def test_sanitize_error_message_removes_database_details() -> None:
    message = 'column "updated_at" of relation "reviews" does not exist'

    assert sanitize_error_message(message) == "Review database schema is not current."


def test_extract_validation_details_finds_direct_and_anyof_enum_values() -> None:
    details = extract_validation_details(
        {
            "type": "object",
            "properties": {
                "response_mode": {"enum": ["compact", "standard", "full"]},
                "concept": {
                    "anyOf": [
                        {"enum": ["Gene", "Disease"]},
                        {"type": "null"},
                    ]
                },
                "query": {"type": "string"},
            },
        }
    )

    assert details["valid_params"] == ["concept", "query", "response_mode"]
    assert details["valid_values_for"] == {
        "concept": ["Gene", "Disease"],
        "response_mode": ["compact", "standard", "full"],
    }


def test_mcp_tool_error_serializes_recovery_envelope() -> None:
    payload = mcp_tool_error(
        RuntimeError('column "updated_at" of relation "reviews" does not exist'),
        McpErrorContext(
            tool_name="index_review_evidence",
            pmids=["39540697"],
        ),
    )

    assert payload["error_code"] == "review_schema_not_current"
    assert payload["fallback_tool"] == "get_publication_passages"
    assert payload["fallback_args"]["pmids"] == ["39540697"]
    assert "updated_at" not in payload["message"]


def test_preflight_review_sources_error_points_to_publication_passages() -> None:
    payload = mcp_tool_error(
        RuntimeError("temporary preflight failure"),
        McpErrorContext(
            tool_name="preflight_review_sources",
            pmids=["10490564", "10927144"],
        ),
    )

    assert payload["error_code"] == "internal_error"
    assert payload["fallback_tool"] == "get_publication_passages"
    assert payload["fallback_args"] == {
        "pmids": ["10490564", "10927144"],
        "mode": "full_abstract",
    }
    assert payload["recovery_action"] == (
        "Call get_publication_passages with the same PMIDs. "
        "Use mode='full_abstract' for article-local answering; run diagnostics only if "
        "passage retrieval also fails."
    )
    assert payload["_meta"]["tool"] == "preflight_review_sources"
    assert payload["_meta"]["next_commands"][0] == {
        "tool": "get_publication_passages",
        "arguments": {
            "pmids": ["10490564", "10927144"],
            "mode": "full_abstract",
        },
    }


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


def test_review_schema_stale_error_preserves_runtime_error_compatibility() -> None:
    assert isinstance(ReviewSchemaStaleError("schema stale"), RuntimeError)


def test_mcp_tool_error_sanitizes_typed_review_schema_message() -> None:
    payload = mcp_tool_error(
        ReviewSchemaStaleError("Review database schema is not current: review_sources"),
        McpErrorContext(tool_name="index_review_evidence"),
    )

    assert payload["error_code"] == "review_schema_not_current"
    assert payload["message"] == "Review database schema is not current."


def test_mcp_tool_error_sanitizes_typed_upstream_message() -> None:
    payload = mcp_tool_error(
        UpstreamUnavailableError("service unavailable"),
        McpErrorContext(tool_name="search_literature"),
    )

    assert payload["error_code"] == "upstream_unavailable"
    assert payload["message"] == "The upstream service is temporarily unavailable."


def test_pubtator_api_database_maintenance_is_upstream_unavailable() -> None:
    payload = mcp_tool_error(
        PubTatorAPIError(
            'HTTP 400: {"detail":"We are currently updating the Database. Please try again later"}',
            status_code=400,
        ),
        McpErrorContext(tool_name="search_literature"),
    )

    assert payload["error_code"] == "upstream_unavailable"
    assert payload["message"] == "The upstream service is temporarily unavailable."
    assert "review schema" not in payload["recovery_action"].lower()


def test_pubtator_api_transport_failure_is_upstream_unavailable() -> None:
    payload = mcp_tool_error(
        PubTatorAPIError(
            "Request failed: Server disconnected without sending a response.",
            retry_metadata={"terminal_reason": "request_error", "attempt_count": 3},
        ),
        McpErrorContext(tool_name="search_literature"),
    )

    assert payload["error_code"] == "upstream_unavailable"
    assert payload["message"] == "The upstream service is temporarily unavailable."
    assert payload["retryable"] is True


def test_generic_internal_error_does_not_claim_schema_is_stale() -> None:
    payload = mcp_tool_error(
        RuntimeError("unexpected adapter failure"),
        McpErrorContext(tool_name="pubtator_unknown_tool"),
    )

    assert payload["error_code"] == "internal_error"
    assert "review schema" not in payload["recovery_action"].lower()
    assert "recent_mcp_errors" in payload["recovery_action"]


def test_schema_stale_recovery_is_reserved_for_schema_errors() -> None:
    payload = mcp_tool_error(
        ReviewSchemaStaleError("schema stale"),
        McpErrorContext(tool_name="index_review_evidence"),
    )

    assert payload["error_code"] == "review_schema_not_current"
    assert "review schema is stale" in payload["recovery_action"].lower()


def test_tool_specific_recovery_text_for_discovery_text_and_audit_errors() -> None:
    cases = {
        "convert_article_ids": "Retry with one identifier at a time",
        "submit_text_annotation": "Retry with a shorter text",
        "export_review_audit_bundle": "Use fallback_inline=True",
    }

    for tool_name, expected in cases.items():
        payload = mcp_tool_error(RuntimeError("boom"), McpErrorContext(tool_name=tool_name))

        assert expected in payload["recovery_action"]
        assert "review schema" not in payload["recovery_action"].lower()


def test_ground_question_error_uses_selected_pmids_for_fallback() -> None:
    error_source = RuntimeError("review database unavailable")
    error_source.pmids = ["11111111", "22222222"]  # type: ignore[attr-defined]

    payload = mcp_tool_error(
        error_source,
        McpErrorContext(tool_name="ground_question"),
    )

    assert payload["fallback_tool"] == "get_publication_passages"
    assert payload["fallback_args"] == {
        "pmids": ["11111111", "22222222"],
        "mode": "compact_passages",
    }


@pytest.mark.asyncio
async def test_ground_question_wrapper_uses_selected_pmids_for_fallback() -> None:
    async def failing() -> dict[str, object]:
        error = RuntimeError("review database unavailable")
        error.pmids = ["11111111", "22222222"]  # type: ignore[attr-defined]
        raise error

    payload = await run_mcp_tool("ground_question", failing)

    assert payload["success"] is False
    assert payload["fallback_tool"] == "get_publication_passages"
    assert payload["fallback_args"] == {
        "pmids": ["11111111", "22222222"],
        "mode": "compact_passages",
    }


def test_mcp_tool_error_includes_bounded_diagnostics_snapshot() -> None:
    payload = mcp_tool_error(
        RuntimeError("relation review_passages is unavailable"),
        McpErrorContext(
            tool_name="index_review_evidence",
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
                "tool": "get_publication_passages",
                "mode": "compact_passages",
                "source_count": 2,
                "degraded_mode": "abstract_only",
                "coverage_by_pmid": {"35042149": "abstract_only"},
            },
        ),
    )

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
        tool_name="index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
        raw_message="relation review_sources does not exist",
    )

    errors = get_recent_mcp_errors()

    assert errors[-1]["tool_name"] == "index_review_evidence"
    assert errors[-1]["error_code"] == "review_index_unavailable"
    assert "raw_message" not in errors[-1]

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
        tool_name="index_review_evidence",
        error_code="review_index_unavailable",
        message='relation "review_sources" does not exist',
        raw_message='relation "review_sources" does not exist at host db.internal',
    )

    errors = get_recent_mcp_errors()

    assert errors[-1]["message"] == "Review database operation failed."
    assert "raw_message" not in errors[-1]
    assert "db.internal" not in json.dumps(errors)


def test_mcp_output_validation_error_is_actionable_and_recorded() -> None:
    from pubtator_link.mcp.errors import clear_recent_mcp_errors, get_recent_mcp_errors
    from pubtator_link.mcp.output_validation import actionable_output_validation_error

    clear_recent_mcp_errors()

    payload = actionable_output_validation_error(
        tool_name="get_review_context_batch",
        arguments={"response_mode": "compact"},
        message="Output validation error: 'explanation' is a required property",
    )

    errors = get_recent_mcp_errors()
    assert payload["success"] is False
    assert payload["error_code"] == "output_validation_failed"
    assert payload["error_field"] == "explanation"
    assert payload["fallback_response_mode"] == "quotes"
    assert payload["suggested_action"].startswith("Retry")
    assert errors[-1]["tool_name"] == "get_review_context_batch"
    assert errors[-1]["error_code"] == "output_validation_failed"
    assert (
        errors[-1]["message"] == "The tool response did not match its declared MCP output schema."
    )


@pytest.mark.asyncio
async def test_installed_mcp_output_validation_handler_replaces_bare_sdk_error() -> None:
    from fastmcp import FastMCP
    from mcp import types

    from pubtator_link.mcp.errors import clear_recent_mcp_errors, get_recent_mcp_errors
    from pubtator_link.mcp.output_validation import install_output_validation_error_handler

    mcp = FastMCP(name="test")

    @mcp.tool(
        name="get_review_context_batch",
        output_schema={
            "type": "object",
            "properties": {"explanation": {"type": "string"}},
            "required": ["explanation"],
        },
    )
    async def broken_tool(response_mode: str = "compact") -> dict[str, object]:
        return {"ok": True}

    install_output_validation_error_handler(mcp)
    clear_recent_mcp_errors()

    handler = mcp._mcp_server.request_handlers[types.CallToolRequest]
    result = await handler(
        types.CallToolRequest(
            params=types.CallToolRequestParams(
                name="get_review_context_batch",
                arguments={"response_mode": "compact"},
            )
        )
    )
    payload = json.loads(result.root.content[0].text)

    assert result.root.isError is True
    assert payload["error_code"] == "output_validation_failed"
    assert payload["error_field"] == "explanation"
    assert payload["fallback_response_mode"] == "quotes"
    assert get_recent_mcp_errors()[-1]["error_code"] == "output_validation_failed"


@pytest.mark.asyncio
async def test_mcp_error_wrapper_returns_flat_envelope_without_raising() -> None:
    from pubtator_link.mcp.errors import run_mcp_tool

    async def failing() -> dict[str, object]:
        raise RuntimeError('column "updated_at" of relation "reviews" does not exist')

    payload = await run_mcp_tool(
        "index_review_evidence",
        failing,
        pmids=["39540697"],
    )

    assert payload["success"] is False
    assert payload["error_code"] == "review_schema_not_current"
    assert payload["_meta"]["tool"] == "index_review_evidence"


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

    payload = await run_mcp_tool("get_review_context_batch", failing)

    assert payload["success"] is False
    assert payload["error_code"] == "validation_failed"
    assert payload["field_errors"] == field_errors
    assert payload["recovery_hint"] == recovery_hint
    assert payload["message"] == "Invalid MCP arguments."


@pytest.mark.asyncio
async def test_mcp_tool_wrapper_preserves_error_code_in_recent_errors_and_metrics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from pubtator_link.mcp.errors import (
        clear_recent_mcp_errors,
        get_recent_mcp_errors,
        run_mcp_tool,
    )
    from pubtator_link.observability.metrics import metrics_payload

    async def failing() -> dict[str, object]:
        raise RuntimeError('column "updated_at" of relation "reviews" does not exist')

    clear_recent_mcp_errors()
    caplog.set_level(logging.WARNING, logger="pubtator_link.mcp.errors")

    payload = await run_mcp_tool("index_review_evidence", failing)

    assert payload["success"] is False
    errors = get_recent_mcp_errors()
    failed_records = [record for record in caplog.records if record.message == "mcp_tool_failed"]
    metrics = metrics_payload().decode()

    assert errors[-1]["error_code"] == "review_schema_not_current"
    assert errors[-1]["message"] == "Review database schema is not current."
    assert failed_records[-1].error_code == "review_schema_not_current"
    assert (
        'mcp_tool_calls_total{error_code="review_schema_not_current",'
        'outcome="failure",tool_name="index_review_evidence"}'
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

    assert result["ok"] is True
    assert result["success"] is True
    assert result["_meta"]["tool"] == "pubtator.test_tool"
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
