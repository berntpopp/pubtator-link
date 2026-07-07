"""Regression guards: REST/service log sites MUST NOT leak free-text or raw exceptions.

The free-text search query (GDPR Art. 9 — it can carry variant coordinates,
phenotype text, or patient identifiers) and raw exception strings (which can
carry a DSN, credentials, host/IP, or the query echoed back by an upstream
error) must never reach emitted log values, even though the sanitized envelope
returned to the caller is clean.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from fastapi import HTTPException

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.api.routes.dependencies.validation import handle_api_errors
from pubtator_link.services.publication_service import PublicationService


class _CapturingLogger:
    """Duck-typed structlog logger that records every event + bound key/value.

    The captured ``(event, kwargs)`` pairs are exactly what structlog renders
    into log output, so asserting the sentinel is absent from every captured
    value is equivalent to asserting it never reaches the log stream.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def _record(self, level: str, event: str, **kwargs: Any) -> None:
        self.entries.append({"level": level, "event": event, **kwargs})

    def debug(self, event: str, **kwargs: Any) -> None:
        self._record("debug", event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._record("info", event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._record("warning", event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._record("error", event, **kwargs)


class _RaisingClient:
    """PubTator3 client stub whose search fails, echoing the query in the error."""

    async def search_publications(self, text: str, page: int = 1) -> dict[str, Any]:
        raise PubTatorAPIError(f"upstream 500 while searching for {text}", status_code=500)


SENTINEL = "BRCA1-p.Arg1699Gln-phenotype-freetext-SENTINEL"


async def test_search_publications_failure_does_not_leak_query_to_logs() -> None:
    """A failing search must not emit the free-text query or the raw exception."""
    logger = _CapturingLogger()
    service = PublicationService(client=_RaisingClient(), logger=logger)  # type: ignore[arg-type]

    with pytest.raises(PubTatorAPIError):
        await service.search_publications(SENTINEL, page=1)

    # Something was logged (cache miss + error) so the guard is meaningful.
    assert logger.entries
    for entry in logger.entries:
        for value in entry.values():
            assert SENTINEL not in str(value), f"query leaked into log entry: {entry}"

    # The sanitized error log still exists and carries only non-identifying fields.
    error_entries = [e for e in logger.entries if e["event"] == "Publication search failed"]
    assert error_entries
    assert "query" not in error_entries[-1]
    assert error_entries[-1].get("error_type") == "PubTatorAPIError"


async def test_handle_api_errors_does_not_leak_exception_string_to_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The generic REST error handler must not render the raw exception message.

    Focused guard for the ``str(e)``/``{e}`` route sites: the exception message
    (which can carry a DSN, host/IP, or free-text) must be absent from logs;
    only the sanitized ``error_type`` may be attached.
    """

    @handle_api_errors
    async def boom() -> None:
        raise RuntimeError(f"connection to secret host contained {SENTINEL}")

    caplog.set_level(logging.ERROR, logger="pubtator_link.api.routes.dependencies")
    with pytest.raises(HTTPException) as excinfo:  # sanitized detail, status 500
        await boom()
    assert excinfo.value.status_code == 500

    formatter = logging.Formatter("%(name)s %(levelname)s %(message)s")
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert SENTINEL not in rendered

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records
    assert getattr(error_records[-1], "error_type", None) == "RuntimeError"
