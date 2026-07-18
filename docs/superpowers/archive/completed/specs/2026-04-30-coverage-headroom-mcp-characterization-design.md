# Coverage Headroom And MCP Characterization Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-04-30

## Goal

Raise PubTator-Link's enforced coverage threshold from 78% to 80% by adding
focused, behavior-preserving tests that also make a later MCP facade split safer.

## Problem

The foundation quality gate now enforces coverage at 78%, and the current
verified coverage is 78.64%. That margin is too narrow. Small useful changes can
break CI even when they are well-tested locally.

At the same time, `pubtator_link/mcp/facade.py` remains a high-change file. It
registers public MCP tools, resources, prompts, annotations, and compatibility
inspection helpers in one place. Before splitting it by domain, the repository
needs stronger characterization tests around the public MCP surface.

## Non-Goals

- Do not refactor `pubtator_link/mcp/facade.py` in this slice.
- Do not change public REST API behavior.
- Do not change public MCP tool names, resource URIs, prompt names, schemas, or
  annotations.
- Do not add broad presentation-heavy CLI tests unless focused tests fail to
  reach the coverage target.
- Do not require PostgreSQL integration tests in CI.

## Proposed Approach

Add tests in three focused areas:

1. MCP facade characterization tests.
2. Server manager lifecycle and transport tests.
3. Annotation route error/status tests.

After the tests push total coverage safely above 80%, update
`[tool.coverage.report] fail_under` in `pyproject.toml` from `78` to `80`.

This keeps the slice behavior-preserving while creating useful safety rails for
future refactors.

## Test Targets

### MCP Facade Characterization

Extend `tests/unit/mcp/test_mcp_facade.py`.

Required coverage:

- Public tool names are locked as a stable set.
- Public resource URIs are locked as a stable set.
- Public prompt names are locked as a stable set.
- Research-use text remains present in public tool descriptions where expected.
- Key tool annotations remain stable:
  - Search/fetch/retrieve tools are read-only and non-destructive.
  - `pubtator.index_review_evidence` remains non-destructive but write-capable.
  - Remote text annotation submission remains non-idempotent.
- Key review-context schema defaults remain stable:
  - `response_mode = "compact"`.
  - `budget_strategy = "query_fair"`.
  - `include_diagnostics = True` for batch retrieval.
  - `table_mode = "preview"`.

These tests should not call external APIs. They should instantiate
`create_pubtator_mcp()` and inspect registered FastMCP metadata through the
existing inspection managers.

### Server Manager Tests

Extend `tests/unit/test_server_manager.py` if it exists. If it does not exist,
create it.

Required coverage:

- `create_app(include_mcp=True)` creates and stores an MCP facade and mounts the
  MCP HTTP app without invoking network I/O.
- `shutdown()` sets `server.should_exit = True` without closing active
  app-owned resources.
- `start_stdio_server()` binds app resources around `mcp.run_async()` when
  lifespan resources exist.

Use lightweight test doubles and monkeypatching. Do not start Uvicorn, bind
ports, or run a real MCP stdio loop.

### Annotation Route Tests

Extend `tests/test_routes/test_annotations.py`.

Required coverage:

- Submit endpoint rejects invalid bioconcepts with 400.
- Submit endpoint rejects blank text with 422.
- Submit endpoint rejects text over 10,000 characters with 413.
- Results endpoint returns 202 detail for `submitted` and `processing`.
- Results endpoint returns 500 for `failed`.
- Results endpoint returns 404 for `expired`.
- Results endpoint returns 500 for unknown statuses.

Use FastAPI dependency overrides or existing route test fixtures. Do not call the
real PubTator API.

## Coverage Threshold Ratchet

Update `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
```

Only commit this threshold increase if `make test-cov` passes with total
coverage at or above 80%.

If coverage is below 80 after the focused tests, keep `fail_under = 78`, document
the measured coverage in the implementation notes, and do not broaden the scope
without review.

## Verification

Required verification commands:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/test_server_manager.py tests/test_routes/test_annotations.py -q
make test-cov
make ci-local
```

Expected results:

- Focused tests pass.
- `make test-cov` exits 0 with total coverage at or above 80%.
- `make ci-local` exits 0.
- No PostgreSQL integration test is required unless
  `PUBTATOR_LINK_TEST_DATABASE_URL` is set.

## Risks And Mitigations

Risk: Tests become brittle by asserting too much private FastMCP structure.

Mitigation: Assert public MCP names, schemas, annotations, resources, and prompts
through the already-installed inspection managers. Avoid testing unrelated
FastMCP internals.

Risk: Coverage target encourages low-value tests.

Mitigation: Keep tests behavior-focused. Prioritize public surface stability and
error/status handling over implementation trivia.

Risk: Annotation route tests reveal existing response-shape behavior that is
awkward, especially 202 responses raised via `HTTPException`.

Mitigation: Characterize current behavior in this slice. Do not redesign response
shape unless a separate spec approves it.

## Success Criteria

- `fail_under` is raised to 80.
- `make test-cov` passes at or above 80% total coverage.
- `make ci-local` passes.
- Public REST and MCP behavior is unchanged.
- The new MCP tests can serve as a safety net for the later MCP facade split.
