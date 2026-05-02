import ast
import json
import logging
from pathlib import Path

import pytest
from fastmcp.exceptions import ToolError

from pubtator_link.mcp.errors import (
    McpErrorContext,
    mcp_tool_error,
    sanitize_error_message,
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
