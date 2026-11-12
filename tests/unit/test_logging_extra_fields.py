"""Stdlib ``extra=`` fields must reach the rendered log line (#248)."""

import json
import logging

import structlog

from pubtator_link.logging_config import stdlib_formatter


def test_stdlib_extra_fields_are_rendered_into_json() -> None:
    formatter = stdlib_formatter(structlog.processors.JSONRenderer())
    record = logging.getLogger("pubtator_link.mcp.errors").makeRecord(
        "pubtator_link.mcp.errors",
        logging.WARNING,
        __file__,
        1,
        "mcp_tool_failed",
        None,
        None,
        extra={"tool_name": "get_publication_passages", "error_code": "internal"},
    )

    line = json.loads(formatter.format(record))

    assert line["event"] == "mcp_tool_failed"
    assert line["tool_name"] == "get_publication_passages"
    assert line["error_code"] == "internal"
    assert line["level"] == "warning"
    assert line["service"] == "pubtator-link"
