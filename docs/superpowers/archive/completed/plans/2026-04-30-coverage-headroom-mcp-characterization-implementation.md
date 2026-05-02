# Coverage Headroom And MCP Characterization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the enforced coverage threshold to 80% with focused behavior-preserving tests that also characterize the public MCP facade before a later split.

**Architecture:** Add tests only, except for the final coverage threshold ratchet in `pyproject.toml`. Characterize public MCP metadata through the existing inspection managers, cover server-manager lifecycle branches with test doubles, and extend annotation route tests using existing patch/dependency patterns. Do not refactor runtime code in this plan.

**Tech Stack:** Python 3.11, pytest, FastAPI TestClient, FastMCP, Ruff, mypy, pytest-cov, uv, Make.

---

## File Map

- Modify `tests/unit/mcp/test_mcp_facade.py`: add full public MCP surface characterization tests.
- Create `tests/unit/test_server_manager.py`: add server-manager lifecycle and transport tests.
- Modify `tests/test_routes/test_annotations.py`: add annotation route error/status tests.
- Modify `pyproject.toml`: raise `[tool.coverage.report] fail_under` from `78` to `80` after coverage proves sufficient.
- Verify with `make test-cov` and `make ci-local`.

## Task 1: Characterize The Full MCP Public Surface

**Files:**
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add public surface constants near the top of the file**

Add these constants below `from __future__ import annotations`:

```python
EXPECTED_PUBLIC_TOOL_NAMES = {
    "pubtator.get_server_capabilities",
    "pubtator.search_literature",
    "pubtator.fetch_publication_annotations",
    "pubtator.get_publication_passages",
    "pubtator.estimate_publication_context",
    "pubtator.fetch_pmc_annotations",
    "pubtator.search_biomedical_entities",
    "pubtator.find_entity_relations",
    "pubtator.submit_text_annotation",
    "pubtator.get_text_annotation_results",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context",
    "pubtator.retrieve_review_context_batch",
}

EXPECTED_RESOURCE_URIS = {
    "pubtator://capabilities",
    "pubtator://bioconcepts",
    "pubtator://relation-types",
    "pubtator://formats",
    "pubtator://text-processing",
    "pubtator://compliance/research-use",
}

EXPECTED_PROMPT_NAMES = {
    "search_biomedical_literature",
    "annotate_research_text",
    "review_pubtator_annotations",
    "review_rerag_workflow",
}
```

- [ ] **Step 2: Replace the partial tool-name assertions with a stable set test**

In `test_curated_facade_registers_pubtator_tools`, replace the individual `assert "... in tool_names"` lines with:

```python
    assert tool_names == EXPECTED_PUBLIC_TOOL_NAMES
    assert "pubtator.clear_api_cache" not in tool_names
```

This locks the full current public MCP tool surface and makes future tool additions explicit.

- [ ] **Step 3: Add a full resource and prompt set test**

Append this test near `test_curated_facade_registers_resources_and_prompts`:

```python
def test_curated_facade_public_resources_and_prompts_are_stable() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()

    assert set(mcp._resource_manager._resources) == EXPECTED_RESOURCE_URIS
    assert set(mcp._prompt_manager._prompts) == EXPECTED_PROMPT_NAMES
```

- [ ] **Step 4: Add annotation characterization for write-capable tools**

Append this test after `test_public_hosted_tools_have_expected_annotations`:

```python
def test_write_capable_mcp_tools_have_expected_annotations() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    annotation_submit = tools["pubtator.submit_text_annotation"].annotations
    assert annotation_submit.readOnlyHint is False
    assert annotation_submit.destructiveHint is False
    assert annotation_submit.idempotentHint is False
    assert annotation_submit.openWorldHint is True

    review_index = tools["pubtator.index_review_evidence"].annotations
    assert review_index.readOnlyHint is False
    assert review_index.destructiveHint is False
    assert review_index.idempotentHint is True
    assert review_index.openWorldHint is True
```

- [ ] **Step 5: Add review retrieval schema default characterization**

Append this test after `test_common_mcp_tools_are_flat_and_unversioned`:

```python
def test_review_context_schema_defaults_are_stable() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    single_schema = tools["pubtator.retrieve_review_context"].parameters["properties"]
    assert single_schema["max_passages"]["default"] == 8
    assert single_schema["max_chars"]["default"] == 6000
    assert single_schema["include_diagnostics"]["default"] is False
    assert single_schema["table_mode"]["default"] == "preview"

    batch_schema = tools["pubtator.retrieve_review_context_batch"].parameters["properties"]
    assert batch_schema["response_mode"]["default"] == "compact"
    assert batch_schema["budget_strategy"]["default"] == "query_fair"
    assert batch_schema["include_diagnostics"]["default"] is True
    assert batch_schema["table_mode"]["default"] == "preview"
```

- [ ] **Step 6: Run the MCP facade tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit MCP characterization tests**

Run:

```bash
git add tests/unit/mcp/test_mcp_facade.py
git commit -m "test: characterize mcp public surface"
```

## Task 2: Add Server Manager Lifecycle And Transport Tests

**Files:**
- Create: `tests/unit/test_server_manager.py`

- [ ] **Step 1: Create server manager test module with imports and doubles**

Create `tests/unit/test_server_manager.py`:

```python
"""Tests for unified server manager lifecycle and transport behavior."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from pubtator_link.api.routes import dependencies
from pubtator_link.api.routes.dependencies import AppResources
from pubtator_link.server_manager import UnifiedServerManager


class LoggerDouble:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    def info(self, message: str, **kwargs: Any) -> None:
        self.messages.append((message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self.messages.append((message, kwargs))


class ClientDouble:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class McpHttpAppDouble:
    def __init__(self) -> None:
        self.lifespan = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        return None


class McpDouble:
    def __init__(self) -> None:
        self.http_app_calls: list[dict[str, Any]] = []
        self.run_async_calls: list[dict[str, Any]] = []

    def http_app(self, **kwargs: Any) -> McpHttpAppDouble:
        self.http_app_calls.append(kwargs)
        return McpHttpAppDouble()

    async def run_async(self, **kwargs: Any) -> None:
        self.run_async_calls.append(kwargs)
```

- [ ] **Step 2: Add test for `create_app(include_mcp=True)`**

Append:

```python
def test_create_app_with_mcp_mounts_http_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    mcp = McpDouble()
    monkeypatch.setattr("pubtator_link.server_manager.create_pubtator_mcp", lambda: mcp)

    manager = UnifiedServerManager(logger=LoggerDouble())
    app = manager.create_app(include_mcp=True)

    assert isinstance(app, FastAPI)
    assert manager.app is app
    assert manager.mcp is mcp
    assert mcp.http_app_calls == [
        {
            "path": "/mcp",
            "json_response": True,
            "stateless_http": True,
        }
    ]
    assert any(route.path == "" for route in app.routes)
```

- [ ] **Step 3: Add test that shutdown only requests server exit**

Append:

```python
@pytest.mark.asyncio
async def test_shutdown_requests_server_exit_without_closing_resources() -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    client = ClientDouble()
    manager.resources = AppResources(
        logger=manager.logger,
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
    )
    manager.server = SimpleNamespace(should_exit=False)

    await manager.shutdown()

    assert manager.server.should_exit is True
    assert manager.resources is not None
    assert client.closed is False
```

- [ ] **Step 4: Add test for stdio resource context binding**

Append:

```python
@pytest.mark.asyncio
async def test_start_stdio_server_binds_lifespan_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = UnifiedServerManager(logger=LoggerDouble())
    client = ClientDouble()
    resources = AppResources(
        logger=manager.logger,
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
    )
    observed_resources: list[AppResources | None] = []

    async def create_resources(logger: Any) -> AppResources:
        return resources

    async def close_resources(app_resources: AppResources) -> None:
        await app_resources.api_client.close()

    class StdioMcpDouble:
        async def run_async(self, **kwargs: Any) -> None:
            observed_resources.append(dependencies.current_app_resources())
            assert kwargs == {"transport": "stdio"}

    async def create_mcp_server(app: FastAPI) -> StdioMcpDouble:
        assert isinstance(app, FastAPI)
        return StdioMcpDouble()

    monkeypatch.setattr(
        "pubtator_link.server_manager.create_app_resources",
        create_resources,
    )
    monkeypatch.setattr(
        "pubtator_link.server_manager.close_app_resources",
        close_resources,
    )
    monkeypatch.setattr(manager, "create_mcp_server", create_mcp_server)

    await manager.start_stdio_server()

    assert observed_resources == [resources]
    assert dependencies.current_app_resources() is None
    assert client.closed is True
    assert manager.resources is None
```

- [ ] **Step 5: Run the server manager tests and verify they pass**

Run:

```bash
uv run pytest tests/unit/test_server_manager.py -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Run lint check for the new test file**

Run:

```bash
uv run ruff check tests/unit/test_server_manager.py
```

Expected:

```text
All checks passed!
```

- [ ] **Step 7: Commit server manager tests**

Run:

```bash
git add tests/unit/test_server_manager.py
git commit -m "test: cover server manager lifecycle branches"
```

## Task 3: Add Annotation Route Error And Status Tests

**Files:**
- Modify: `tests/test_routes/test_annotations.py`

- [ ] **Step 1: Add submit validation tests**

Inside `class TestAnnotationRoutes`, add these tests after `test_submit_text_annotation_invalid_bioconcept`:

```python
    def test_submit_text_annotation_rejects_blank_text(self, test_client):
        """Test text annotation rejects empty text."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "   ", "bioconcepts": "Gene"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == "Text is required and cannot be empty"

    def test_submit_text_annotation_rejects_text_over_limit(self, test_client):
        """Test text annotation rejects text over the public limit."""
        response = test_client.post(
            "/api/annotations/submit",
            params={"text": "x" * 10001, "bioconcepts": "Gene"},
        )

        assert response.status_code == 413
        assert "10,000 characters" in response.json()["detail"]
```

- [ ] **Step 2: Add helper for mocked annotation-result statuses**

Inside `class TestAnnotationRoutes`, add this static helper before result-status tests:

```python
    @staticmethod
    def _annotation_result(status: str) -> dict[str, object]:
        result: dict[str, object] = {
            "status": status,
            "original_text": "BRCA1 mutations increase breast cancer risk",
            "bioconcept": "Gene",
        }
        if status == "failed":
            result["error"] = "upstream processing failed"
        return result
```

- [ ] **Step 3: Add 202 status tests for submitted and processing**

Add:

```python
    @pytest.mark.parametrize("status", ["submitted", "processing"])
    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_in_progress_status(
        self,
        mock_get_results,
        test_client,
        status,
    ):
        """Test in-progress annotation statuses return 202 details."""
        mock_get_results.return_value = self._annotation_result(status)

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 202
        detail = response.json()["detail"]
        assert detail["success"] is True
        assert detail["status"] == status
        assert detail["message"] == "Processing in progress. Please try again in a few moments."
```

- [ ] **Step 4: Add failed, expired, and unknown status tests**

Add:

```python
    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_failed_status(self, mock_get_results, test_client):
        """Test failed annotation status returns an explicit server error."""
        mock_get_results.return_value = self._annotation_result("failed")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 500
        assert "upstream processing failed" in response.json()["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_expired_status(self, mock_get_results, test_client):
        """Test expired annotation status returns not found."""
        mock_get_results.return_value = self._annotation_result("expired")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 404
        assert "has expired" in response.json()["detail"]

    @patch.object(PubTator3Client, "retrieve_text_annotation")
    def test_get_annotation_results_reports_unknown_status(self, mock_get_results, test_client):
        """Test unknown annotation status returns an explicit server error."""
        mock_get_results.return_value = self._annotation_result("queued_elsewhere")

        response = test_client.get("/api/annotations/results/0DA64A2FE4D635D5820C")

        assert response.status_code == 500
        assert "Unknown processing status: queued_elsewhere" in response.json()["detail"]
```

- [ ] **Step 5: Run annotation route tests**

Run:

```bash
uv run pytest tests/test_routes/test_annotations.py -q
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit annotation route tests**

Run:

```bash
git add tests/test_routes/test_annotations.py
git commit -m "test: cover annotation route status branches"
```

## Task 4: Raise Coverage Threshold To 80

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Run coverage before editing the threshold**

Run:

```bash
make test-cov
```

Expected:

```text
passed
TOTAL
```

Confirm total coverage is at least 80.00%. If it is below 80.00%, stop and report the measured coverage before changing `pyproject.toml`.

- [ ] **Step 2: Raise coverage threshold**

In `pyproject.toml`, change:

```toml
fail_under = 78
```

to:

```toml
fail_under = 80
```

- [ ] **Step 3: Run coverage with the raised threshold**

Run:

```bash
make test-cov
```

Expected:

```text
Required test coverage of 80.0% reached.
```

The command must exit 0.

- [ ] **Step 4: Commit coverage ratchet**

Run:

```bash
git add pyproject.toml
git commit -m "test: raise coverage threshold to 80"
```

## Task 5: Full Verification

**Files:**
- Verify all changed files from Tasks 1-4.

- [ ] **Step 1: Run local CI**

Run:

```bash
make ci-local
```

Expected:

```text
Success: no issues found
passed
```

The command must exit 0.

- [ ] **Step 2: Run coverage gate**

Run:

```bash
make test-cov
```

Expected:

```text
Required test coverage of 80.0% reached.
```

The command must exit 0 and total coverage must be at least 80%.

- [ ] **Step 3: Inspect final branch state**

Run:

```bash
git status --short
git log --oneline -6
```

Expected:

- Working tree is clean.
- Recent commits correspond to the MCP characterization tests, server manager tests, annotation route tests, and coverage threshold ratchet.

## Self-Review Checklist For Implementers

Before final handoff, verify:

- MCP public tool names, resources, prompts, annotations, and schema defaults are characterized.
- Server manager tests do not start real network listeners or real MCP stdio loops.
- Annotation route tests do not call the real PubTator API.
- `fail_under` is exactly `80`.
- `make ci-local` passes.
- `make test-cov` passes at or above 80%.
- Public REST and MCP behavior remains unchanged.
