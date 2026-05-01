# CLI Smoke Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fast CLI smoke tests that cover parser and dispatch behavior without network calls.

**Architecture:** Test `pubtator_link.cli.main()` directly by patching `sys.argv`, command functions, and `asyncio.run`. Avoid asserting Rich output and avoid live PubTator clients.

**Tech Stack:** Python 3.11, argparse, pytest, pytest monkeypatch, Make.

---

## File Structure

- Create `tests/unit/test_cli.py`: parser, dispatch, and exit-code smoke tests.
- Modify `pubtator_link/cli.py` only if tests expose an existing bug.

## Task 1: Add Help Path Tests

**Files:**
- Create: `tests/unit/test_cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Write tests for no-command and serve-no-mode paths**

Create `tests/unit/test_cli.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link import cli


def test_cli_without_command_prints_help_and_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["pubtator-link"])

    cli.main()


def test_cli_serve_without_mode_prints_help_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve"])

    cli.main()
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/unit/test_cli.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add cli help smoke tests"
```

## Task 2: Add Server Dispatch Tests

**Files:**
- Modify: `tests/unit/test_cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Add dispatch helpers and tests**

Append to `tests/unit/test_cli.py`:

```python
def test_cli_dispatches_http_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_serve_http(host: str, port: int, reload: bool) -> object:
        calls.append((host, port, reload))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve", "http", "--host", "0.0.0.0", "--port", "9000", "--reload"])
    monkeypatch.setattr(cli, "serve_http", fake_serve_http)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("0.0.0.0", 9000, True), sentinel]


def test_cli_dispatches_unified_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_serve_unified(host: str, port: int, reload: bool) -> object:
        calls.append((host, port, reload))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve", "unified", "--port", "9100"])
    monkeypatch.setattr(cli, "serve_unified", fake_serve_unified)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("127.0.0.1", 9100, False), sentinel]


def test_cli_dispatches_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve", "mcp"])
    monkeypatch.setattr(cli, "serve_mcp_only", lambda: calls.append("mcp"))

    cli.main()

    assert calls == ["mcp"]
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_cli.py -q
```

Expected: pass without coroutine warnings.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add cli server dispatch smoke tests"
```

## Task 3: Add Data Command Dispatch Tests

**Files:**
- Modify: `tests/unit/test_cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Add tests for entities, search, and export dispatch**

Append:

```python
def test_cli_dispatches_entities_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_search_entities(query: str, concept: str | None, limit: int) -> object:
        calls.append((query, concept, limit))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "entities", "MEFV", "--concept", "Gene", "--limit", "3"])
    monkeypatch.setattr(cli, "search_entities", fake_search_entities)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("MEFV", "Gene", 3), sentinel]


def test_cli_dispatches_search_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_search_publications(query: str, page: int) -> object:
        calls.append((query, page))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "search", "colchicine", "--page", "2"])
    monkeypatch.setattr(cli, "search_publications", fake_search_publications)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("colchicine", 2), sentinel]


def test_cli_dispatches_export_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_export_publications(pmids: str, format: str, full: bool) -> object:
        calls.append((pmids, format, full))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "export", "1,2", "--format", "pubtator", "--full"])
    monkeypatch.setattr(cli, "export_publications", fake_export_publications)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("1,2", "pubtator", True), sentinel]
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/unit/test_cli.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add cli data command dispatch smoke tests"
```

## Task 4: Add Test Command Exit-Code Coverage

**Files:**
- Modify: `tests/unit/test_cli.py`
- Test: `tests/unit/test_cli.py`

- [ ] **Step 1: Add exit-code tests**

Append:

```python
@pytest.mark.parametrize(("success", "expected_code"), [(True, 0), (False, 1)])
def test_cli_test_command_maps_connection_result_to_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    success: bool,
    expected_code: int,
) -> None:
    sentinel = object()

    def fake_test_connection() -> object:
        return sentinel

    def fake_asyncio_run(coro: object) -> bool:
        assert coro is sentinel
        return success

    monkeypatch.setattr("sys.argv", ["pubtator-link", "test"])
    monkeypatch.setattr(cli, "test_connection", fake_test_connection)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == expected_code
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_cli.py -q
```

Expected: pass.

- [ ] **Step 3: Run coverage gate**

```bash
make test-cov
```

Expected: exits 0 and coverage remains at or above 80%.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add cli test command exit coverage"
```

## Task 5: Final Verification

**Files:**
- Check: `tests/unit/test_cli.py`
- Check: `pubtator_link/cli.py`

- [ ] **Step 1: Run focused tests**

```bash
uv run pytest tests/unit/test_cli.py -q
```

Expected: pass.

- [ ] **Step 2: Run full gate**

```bash
make ci-local
make test-cov
```

Expected: both exit 0.

- [ ] **Step 3: Check for final cleanup changes**

```bash
git add tests/unit/test_cli.py pubtator_link/cli.py
git commit -m "test: finalize cli smoke coverage"
```

Run:

```bash
git status --short
```

If `tests/unit/test_cli.py` or `pubtator_link/cli.py` changed during final verification, commit them. If `git status --short` is empty, do not create an empty commit for this task.

## Plan Self-Review Checklist

- Spec coverage: help paths, dispatch paths, exit-code mapping, no network calls, and coverage gate are covered.
- Placeholder scan: no placeholders.
- Type consistency: tests use pytest `MonkeyPatch` and existing `cli.main()`.
