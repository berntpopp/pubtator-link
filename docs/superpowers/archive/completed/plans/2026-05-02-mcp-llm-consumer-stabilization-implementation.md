# MCP LLM Consumer Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize PubTator-Link MCP for LLM consumers by repairing review database schema drift, centralizing MCP-standard error handling, reducing noisy search payloads, surfacing coverage before indexing, and documenting deterministic recovery flows.

**Architecture:** Add a first-party idempotent PostgreSQL migration runner and schema diagnostics layer, then use it from startup, Makefile, Docker, `/ready`, and `pubtator.diagnostics`. Centralize MCP tool-execution error mapping through FastMCP `ToolError` with masked server errors, while preserving typed structured success outputs. Extend existing search, entity, passage, and review retrieval models instead of renaming tools.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, asyncpg/PostgreSQL, httpx, Ruff, mypy, pytest, pytest-asyncio, Makefile, Docker Compose, uv.

---

## Context

Read first:

- `AGENTS.md`
- `docs/superpowers/specs/2026-05-02-mcp-llm-consumer-stabilization-design.md`
- `docs/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md` if present; do not edit it unless explicitly requested.

Current live failure to preserve in tests:

- Existing Docker PostgreSQL volume can have `reviews(review_id, created_at)` but no `updated_at`.
- `index_review_evidence` currently fails against that stale schema.
- Replaying `pubtator_link/db/review_schema.sql` is insufficient because `CREATE TABLE IF NOT EXISTS reviews (...)` does not add missing columns.

Use TDD for every behavior change. Commit after each completed task.

## File Structure

Create:

- `pubtator_link/db/__init__.py` - package marker and migration exports.
- `pubtator_link/db/migrations/__init__.py` - migration package marker.
- `pubtator_link/db/migrations/0001_review_schema_base.sql` - base schema for new DBs.
- `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql` - additive repair for old DBs.
- `pubtator_link/db/migrate.py` - asyncpg migration runner, schema diagnostics, and CLI.
- `pubtator_link/mcp/errors.py` - centralized MCP error envelope and `ToolError` mapping.
- `pubtator_link/mcp/tools/diagnostics.py` - `pubtator.diagnostics` MCP tool.
- `pubtator_link/services/diagnostics.py` - subsystem diagnostics service shared by REST and MCP.
- `tests/unit/test_db_migrations.py`
- `tests/unit/test_mcp_errors.py`
- `tests/unit/test_diagnostics_service.py`

Modify:

- `pubtator_link/config.py` - migration settings.
- `pubtator_link/api/routes/dependencies.py` - run migrations, expose diagnostics service, route search preflight provider.
- `pubtator_link/server_manager.py` - richer `/ready`.
- `pubtator_link/db/review_schema.sql` - keep bootstrap schema aligned with migrations.
- `Makefile` - add `db-migrate` and use it in Docker/local docs.
- `docker/docker-compose.yml` - enable auto migration for local stack if needed.
- `pubtator_link/models/responses.py` - search response shaping, coverage/reproducibility metadata, matched terms.
- `pubtator_link/models/publication_passages.py` - coverage, failed PMIDs, warnings, reproducibility metadata.
- `pubtator_link/models/review_rerag.py` - diagnostics metadata, zero-result reasons, dry run flag.
- `pubtator_link/api/client.py` - optional search page size only if upstream supports it safely; otherwise leave untouched and locally trim results.
- `pubtator_link/api/routes/search.py` - REST search options.
- `pubtator_link/api/routes/publications.py` - passage response model fields through existing service.
- `pubtator_link/mcp/facade.py` - `mask_error_details=True`, register diagnostics, updated instructions.
- `pubtator_link/mcp/tools/literature.py` - compact search args, guideline wrapper, centralized error wrapper.
- `pubtator_link/mcp/tools/publications.py` - centralized error wrapper and response schema.
- `pubtator_link/mcp/tools/review.py` - centralized error wrapper and output schemas where missing.
- `pubtator_link/mcp/tools/discovery.py` - centralized error wrapper.
- `pubtator_link/mcp/tools/text_annotations.py` - centralized error wrapper.
- `pubtator_link/mcp/service_adapters.py` - search shaping, guideline rerank, error helper use where adapter-level fallback args are easiest.
- `pubtator_link/mcp/resources.py` - capabilities/core workflow/recovery docs.
- `pubtator_link/services/publication_passage_service.py` - coverage and degradation warnings.
- `pubtator_link/services/research_session.py` - more deterministic queue failure recovery.
- `pubtator_link/services/review_context/diagnostics.py` - expanded zero-result reasons.
- `pubtator_link/services/review_context_service.py` - dry run and reproducibility metadata.
- `README.md`
- `docs/MCP_CONNECTION_GUIDE.md`
- `docs/development/operations-runbook.md`
- `docker/README.md`

Existing tests to update:

- `tests/unit/test_route_dependencies.py`
- `tests/test_routes/test_search.py`
- `tests/test_routes/test_publications.py`
- `tests/test_routes/test_reviews.py`
- `tests/unit/test_publication_passage_service.py`
- `tests/unit/test_review_context_service.py`
- `tests/unit/mcp/test_mcp_facade.py`
- `tests/unit/mcp/test_mcp_service_adapters.py`
- `tests/unit/mcp/test_review_rerag_mcp.py`
- `tests/unit/test_review_schema_sql.py`
- `tests/integration/test_review_schema_postgres.py`

---

### Task 1: Add Idempotent Review Database Migrations

**Files:**
- Create: `pubtator_link/db/__init__.py`
- Create: `pubtator_link/db/migrations/__init__.py`
- Create: `pubtator_link/db/migrations/0001_review_schema_base.sql`
- Create: `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql`
- Create: `pubtator_link/db/migrate.py`
- Modify: `pubtator_link/db/review_schema.sql`
- Modify: `Makefile`
- Test: `tests/unit/test_db_migrations.py`
- Test: `tests/unit/test_review_schema_sql.py`

- [ ] **Step 1: Write failing migration ordering and SQL tests**

Create `tests/unit/test_db_migrations.py`:

```python
from pathlib import Path

from pubtator_link.db.migrate import (
    MIGRATIONS_PACKAGE,
    required_review_schema_items,
    schema_repair_statements,
)


def test_migration_files_are_ordered_and_include_repair_migration() -> None:
    migration_dir = Path("pubtator_link/db/migrations")
    names = sorted(path.name for path in migration_dir.glob("*.sql"))

    assert names == [
        "0001_review_schema_base.sql",
        "0002_review_schema_drift_repair.sql",
    ]
    assert MIGRATIONS_PACKAGE == "pubtator_link.db.migrations"


def test_repair_migration_adds_reviews_updated_at_without_dropping_data() -> None:
    sql = Path("pubtator_link/db/migrations/0002_review_schema_drift_repair.sql").read_text()

    assert "alter table reviews add column if not exists updated_at" in sql.lower()
    assert "update reviews set updated_at = coalesce(updated_at, created_at, now())" in sql.lower()
    assert "create index if not exists reviews_updated_at_idx" in sql.lower()
    assert "drop table" not in sql.lower()
    assert "truncate" not in sql.lower()


def test_required_schema_items_include_review_tables_and_columns() -> None:
    required = required_review_schema_items()

    assert ("reviews", "updated_at") in required.columns
    assert ("full_text_retrieval_attempts", "coverage_reason") in required.columns
    assert "review_research_sessions" in required.tables
    assert "review_research_session_candidates" in required.tables
    assert "review_evidence_certainty" in required.tables


def test_schema_repair_statements_are_non_destructive() -> None:
    statements = schema_repair_statements()
    joined = "\n".join(statements).lower()

    assert "drop table" not in joined
    assert "drop column" not in joined
    assert "truncate" not in joined
    assert any("alter table reviews add column if not exists updated_at" in item.lower() for item in statements)
```

Extend `tests/unit/test_review_schema_sql.py`:

```python
def test_bootstrap_schema_matches_first_migration_core_tables() -> None:
    base = Path("pubtator_link/db/migrations/0001_review_schema_base.sql").read_text()

    for fragment in (
        "create table if not exists reviews",
        "updated_at timestamptz not null default now()",
        "create table if not exists review_research_sessions",
        "create table if not exists review_evidence_certainty",
    ):
        assert fragment in base
        assert fragment in SCHEMA
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_db_migrations.py tests/unit/test_review_schema_sql.py -q
```

Expected: fail because migration files and `pubtator_link.db.migrate` do not exist.

- [ ] **Step 3: Add migration files**

Create `pubtator_link/db/__init__.py`:

```python
"""Database migration helpers for PubTator-Link."""
```

Create `pubtator_link/db/migrations/__init__.py`:

```python
"""SQL migrations for PubTator-Link review storage."""
```

Create `pubtator_link/db/migrations/0001_review_schema_base.sql` by copying the complete current contents of `pubtator_link/db/review_schema.sql`.

Create `pubtator_link/db/migrations/0002_review_schema_drift_repair.sql`:

```sql
alter table reviews add column if not exists updated_at timestamptz;

update reviews
set updated_at = coalesce(updated_at, created_at, now())
where updated_at is null;

alter table reviews alter column updated_at set default now();
alter table reviews alter column updated_at set not null;

create index if not exists reviews_updated_at_idx
    on reviews(updated_at);

alter table full_text_retrieval_attempts
    add column if not exists coverage_reason text not null default 'unknown',
    add column if not exists attempt_count integer not null default 1,
    add column if not exists last_status_code integer,
    add column if not exists retry_after_ms integer,
    add column if not exists backoff_ms integer,
    add column if not exists terminal_reason text,
    add column if not exists pmcid text,
    add column if not exists doi text,
    add column if not exists license_or_access_hint text,
    add column if not exists pmc_fallback_available boolean not null default false;

create index if not exists review_attempts_audit_idx
    on full_text_retrieval_attempts(review_id, source_id, source_kind, created_at);

create table if not exists review_audit_events (
    review_id text not null references reviews(review_id),
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists review_audit_events_review_id_idx
    on review_audit_events(review_id, created_at);

create table if not exists review_research_sessions (
    session_id text not null,
    review_id text not null references reviews(review_id),
    query text,
    status text not null default 'active',
    request jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id)
);

create index if not exists review_research_sessions_review_id_idx
    on review_research_sessions(review_id, updated_at);

create table if not exists review_research_session_candidates (
    review_id text not null,
    session_id text not null,
    pmid text not null,
    rank integer,
    title text,
    status text not null,
    decision_reason text not null,
    coverage_hint jsonb,
    source_id text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id, pmid),
    unique(review_id, session_id, pmid),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id)
);

create index if not exists review_research_session_candidates_session_idx
    on review_research_session_candidates(review_id, session_id, rank, pmid);

create unique index if not exists review_research_session_candidates_unique_pmid_idx
    on review_research_session_candidates(review_id, session_id, pmid);

create table if not exists review_evidence_certainty (
    certainty_id uuid primary key,
    review_id text not null references reviews(review_id),
    outcome text not null,
    question text,
    study_design text,
    risk_of_bias_notes text,
    inconsistency_notes text,
    indirectness_notes text,
    imprecision_notes text,
    publication_bias_notes text,
    overall_certainty text not null,
    certainty_rationale text,
    passage_ids text[] not null default '{}',
    unresolved_passage_ids text[] not null default '{}',
    created_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists review_evidence_certainty_review_id_idx
    on review_evidence_certainty(review_id, updated_at);
```

- [ ] **Step 4: Add migration runner**

Create `pubtator_link/db/migrate.py`:

```python
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from importlib import resources
from typing import Any

import asyncpg

from pubtator_link.config import review_rerag_config

MIGRATIONS_PACKAGE = "pubtator_link.db.migrations"


@dataclass(frozen=True)
class RequiredSchemaItems:
    tables: frozenset[str]
    columns: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ReviewSchemaDiagnostics:
    connected: bool
    current: bool
    applied_versions: list[str]
    missing_tables: list[str]
    missing_columns: list[str]
    error: str | None = None


def required_review_schema_items() -> RequiredSchemaItems:
    return RequiredSchemaItems(
        tables=frozenset(
            {
                "reviews",
                "review_preparation_jobs",
                "full_text_retrieval_attempts",
                "review_passages",
                "review_audit_events",
                "review_research_sessions",
                "review_research_session_candidates",
                "review_evidence_certainty",
            }
        ),
        columns=frozenset(
            {
                ("reviews", "updated_at"),
                ("full_text_retrieval_attempts", "coverage_reason"),
                ("full_text_retrieval_attempts", "attempt_count"),
                ("full_text_retrieval_attempts", "last_status_code"),
                ("full_text_retrieval_attempts", "retry_after_ms"),
                ("full_text_retrieval_attempts", "backoff_ms"),
                ("full_text_retrieval_attempts", "terminal_reason"),
                ("full_text_retrieval_attempts", "pmcid"),
                ("full_text_retrieval_attempts", "doi"),
                ("full_text_retrieval_attempts", "license_or_access_hint"),
                ("full_text_retrieval_attempts", "pmc_fallback_available"),
            }
        ),
    )


def migration_files() -> list[tuple[str, str]]:
    package = resources.files(MIGRATIONS_PACKAGE)
    files = sorted(path for path in package.iterdir() if path.name.endswith(".sql"))
    return [(path.name.removesuffix(".sql"), path.read_text()) for path in files]


def schema_repair_statements() -> list[str]:
    migration = resources.files(MIGRATIONS_PACKAGE).joinpath(
        "0002_review_schema_drift_repair.sql"
    )
    return [
        statement.strip()
        for statement in migration.read_text().split(";")
        if statement.strip()
    ]


async def apply_migrations(database_url: str | None = None) -> list[str]:
    dsn = database_url or review_rerag_config.database_url
    if dsn is None:
        return []

    connection = await asyncpg.connect(dsn)
    try:
        await connection.execute(
            """
            create table if not exists schema_migrations (
                version text primary key,
                applied_at timestamptz not null default now()
            )
            """
        )
        applied_rows = await connection.fetch("select version from schema_migrations")
        applied = {row["version"] for row in applied_rows}
        newly_applied: list[str] = []
        for version, sql in migration_files():
            if version in applied:
                continue
            async with connection.transaction():
                await connection.execute(sql)
                await connection.execute(
                    "insert into schema_migrations(version) values($1)",
                    version,
                )
            newly_applied.append(version)
        return newly_applied
    finally:
        await connection.close()


async def inspect_review_schema(database_url: str | None = None) -> ReviewSchemaDiagnostics:
    dsn = database_url or review_rerag_config.database_url
    if dsn is None:
        return ReviewSchemaDiagnostics(
            connected=False,
            current=False,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
            error="database_not_configured",
        )

    try:
        connection = await asyncpg.connect(dsn)
    except Exception as exc:
        return ReviewSchemaDiagnostics(
            connected=False,
            current=False,
            applied_versions=[],
            missing_tables=[],
            missing_columns=[],
            error=type(exc).__name__,
        )

    try:
        required = required_review_schema_items()
        table_rows = await connection.fetch(
            """
            select tablename
            from pg_tables
            where schemaname = 'public'
            """
        )
        tables = {row["tablename"] for row in table_rows}
        column_rows = await connection.fetch(
            """
            select table_name, column_name
            from information_schema.columns
            where table_schema = 'public'
            """
        )
        columns = {(row["table_name"], row["column_name"]) for row in column_rows}
        migration_rows = await connection.fetch(
            """
            select version
            from schema_migrations
            order by version
            """
        ) if "schema_migrations" in tables else []
        missing_tables = sorted(required.tables - tables)
        missing_columns = [
            f"{table}.{column}"
            for table, column in sorted(required.columns - columns)
        ]
        return ReviewSchemaDiagnostics(
            connected=True,
            current=not missing_tables and not missing_columns,
            applied_versions=[row["version"] for row in migration_rows],
            missing_tables=missing_tables,
            missing_columns=missing_columns,
        )
    finally:
        await connection.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply PubTator-Link database migrations.")
    parser.add_argument("--check", action="store_true", help="Check schema without applying.")
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    if args.check:
        diagnostics = await inspect_review_schema()
        print(diagnostics)
        return 0 if diagnostics.current else 1
    applied = await apply_migrations()
    print("Applied migrations:", ", ".join(applied) if applied else "none")
    diagnostics = await inspect_review_schema()
    if not diagnostics.current:
        print(diagnostics)
        return 1
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Add Makefile target**

Modify `Makefile`:

```make
db-migrate: ## Apply idempotent review re-RAG PostgreSQL migrations
	test -n "$$PUBTATOR_LINK_DATABASE_URL"
	uv run python -m pubtator_link.db.migrate
```

Keep `db-init` for compatibility but change its description to "Apply bootstrap schema to empty databases".

- [ ] **Step 6: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_db_migrations.py tests/unit/test_review_schema_sql.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/db Makefile tests/unit/test_db_migrations.py tests/unit/test_review_schema_sql.py
git commit -m "feat: add review database migrations"
```

---

### Task 2: Wire Migrations Into Startup, Readiness, And Docker

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/server_manager.py`
- Modify: `docker/docker-compose.yml`
- Test: `tests/unit/test_route_dependencies.py`
- Test: `tests/test_routes/test_root_health.py` if present, otherwise `tests/test_routes/test_server.py`

- [ ] **Step 1: Write failing config and startup tests**

Add to `tests/unit/test_route_dependencies.py`:

```python
import pytest

from pubtator_link.api.routes import dependencies


@pytest.mark.asyncio
async def test_create_app_resources_runs_migrations_before_review_services(monkeypatch):
    calls: list[str] = []

    async def apply_migrations(database_url=None):
        calls.append("migrate")
        return ["0002_review_schema_drift_repair"]

    class FakePool:
        async def close(self):
            calls.append("close_pool")

    async def create_pool(**kwargs):
        calls.append("pool")
        return FakePool()

    monkeypatch.setattr(dependencies, "apply_migrations", apply_migrations)
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://test",
            prep_concurrency=2,
            auto_migrate=True,
            require_schema_current=False,
        ),
    )
    monkeypatch.setattr(dependencies, "_build_full_text_preparation", lambda **kwargs: object())

    resources = await dependencies.create_app_resources(logger=object())

    assert calls[:2] == ["migrate", "pool"]
    assert resources.review_pool is not None
```

Add a readiness route test in the existing route test file that already creates `app`:

```python
def test_ready_reports_schema_not_current(test_client, monkeypatch):
    from pubtator_link.server_manager import app

    app.state.pubtator_schema_diagnostics = {
        "connected": True,
        "current": False,
        "missing_tables": [],
        "missing_columns": ["reviews.updated_at"],
        "applied_versions": ["0001_review_schema_base"],
    }

    response = test_client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["database"]["schema_current"] is False
    assert "reviews.updated_at" in body["dependencies"]["database"]["missing_columns"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_route_dependencies.py tests/test_routes -q
```

Expected: fail because migration settings and readiness schema diagnostics do not exist.

- [ ] **Step 3: Add config fields**

Modify `ServerSettings` in `pubtator_link/config.py`:

```python
auto_migrate: bool = Field(
    default=True,
    description="Run additive review database migrations on startup when database_url is configured",
)
require_schema_current: bool = Field(
    default=True,
    description="Require current review database schema before enabling review services",
)
```

Modify `ReviewReragConfig`:

```python
auto_migrate: bool = True
require_schema_current: bool = True
```

Modify `ReviewReragConfig.from_settings`:

```python
auto_migrate=server_settings.auto_migrate,
require_schema_current=server_settings.require_schema_current,
```

- [ ] **Step 4: Run migrations before pool creation**

In `pubtator_link/api/routes/dependencies.py`, import:

```python
from pubtator_link.db.migrate import apply_migrations, inspect_review_schema
```

Inside `create_app_resources`, before `asyncpg.create_pool`:

```python
schema_diagnostics: dict[str, Any] | None = None
if review_rerag_config.database_url is not None:
    if review_rerag_config.auto_migrate:
        await apply_migrations(review_rerag_config.database_url)
    diagnostics = await inspect_review_schema(review_rerag_config.database_url)
    schema_diagnostics = diagnostics.__dict__
    if review_rerag_config.require_schema_current and not diagnostics.current:
        raise RuntimeError("Review database schema is not current")
```

Add `schema_diagnostics: dict[str, Any] | None = None` to `AppResources` and pass it into `AppResources`.

- [ ] **Step 5: Enrich `/ready`**

Modify `/ready` in `pubtator_link/server_manager.py` so database dependency includes:

```python
"schema_current": schema_current,
"missing_tables": missing_tables,
"missing_columns": missing_columns,
"applied_versions": applied_versions,
"recovery": "Run make db-migrate with PUBTATOR_LINK_DATABASE_URL set." if not schema_current else None,
```

If `resources` is unavailable but `request.app.state.pubtator_schema_diagnostics` exists, use that dict.

- [ ] **Step 6: Update Docker env**

In `docker/docker-compose.yml`, add:

```yaml
      PUBTATOR_LINK_AUTO_MIGRATE: "true"
      PUBTATOR_LINK_REQUIRE_SCHEMA_CURRENT: "true"
```

- [ ] **Step 7: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_route_dependencies.py tests/test_routes -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/config.py pubtator_link/api/routes/dependencies.py pubtator_link/server_manager.py docker/docker-compose.yml tests/unit/test_route_dependencies.py tests/test_routes
git commit -m "feat: run review migrations on startup"
```

---

### Task 3: Centralize MCP-Standard Error Handling

**Files:**
- Create: `pubtator_link/mcp/errors.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/tools/*.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing tests for sanitized ToolError mapping**

Create `tests/unit/test_mcp_errors.py`:

```python
import json

import asyncpg
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


@pytest.mark.asyncio
async def test_mcp_error_wrapper_raises_tool_error() -> None:
    from pubtator_link.mcp.errors import run_mcp_tool

    async def failing():
        raise RuntimeError('column "updated_at" of relation "reviews" does not exist')

    with pytest.raises(ToolError) as exc_info:
        await run_mcp_tool(
            "pubtator.index_review_evidence",
            failing,
            pmids=["39540697"],
        )

    payload = json.loads(str(exc_info.value))
    assert payload["error_code"] == "review_schema_not_current"
```

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_mcp_masks_unhandled_error_details() -> None:
    mcp = create_pubtator_mcp()

    assert getattr(mcp, "settings").mask_error_details is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: fail because `pubtator_link.mcp.errors` does not exist and MCP is not configured with `mask_error_details=True`.

- [ ] **Step 3: Implement MCP error module**

Create `pubtator_link/mcp/errors.py`:

```python
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import asyncpg
import httpx
from fastmcp.exceptions import ToolError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpErrorContext:
    tool_name: str
    pmids: list[str] | None = None
    fallback_tool: str | None = None
    fallback_args: dict[str, Any] | None = None


def sanitize_error_message(message: str) -> str:
    lowered = message.lower()
    if "updated_at" in lowered and "reviews" in lowered:
        return "Review database schema is not current."
    if "database" in lowered or "postgres" in lowered or "asyncpg" in lowered:
        return "Review database operation failed."
    if "timeout" in lowered:
        return "The upstream service timed out."
    return "The tool could not complete the requested operation."


def error_code_for_exception(exc: Exception) -> str:
    message = str(exc).lower()
    if "updated_at" in message and "reviews" in message:
        return "review_schema_not_current"
    if isinstance(exc, asyncpg.PostgresError):
        return "review_index_unavailable"
    if isinstance(exc, httpx.TimeoutException) or isinstance(exc, TimeoutError):
        return "upstream_unavailable"
    if isinstance(exc, ValueError):
        return "validation_failed"
    return "internal_error"


def _fallback_for_context(context: McpErrorContext) -> tuple[str | None, dict[str, Any] | None]:
    if context.fallback_tool is not None:
        return context.fallback_tool, context.fallback_args or {}
    if context.tool_name in {
        "pubtator.index_review_evidence",
        "pubtator.stage_research_session",
    } and context.pmids:
        return (
            "pubtator.get_publication_passages",
            {"pmids": context.pmids, "mode": "compact_passages"},
        )
    return None, None


def mcp_tool_error(exc: Exception, context: McpErrorContext) -> ToolError:
    logger.exception("MCP tool execution failed", extra={"tool_name": context.tool_name})
    fallback_tool, fallback_args = _fallback_for_context(context)
    next_commands: list[dict[str, Any]] = []
    if fallback_tool and fallback_args is not None:
        next_commands.append({"tool": fallback_tool, "arguments": fallback_args})
    next_commands.append({"tool": "pubtator.diagnostics", "arguments": {}})
    payload = {
        "error_code": error_code_for_exception(exc),
        "message": sanitize_error_message(str(exc)),
        "retryable": False,
        "fallback_tool": fallback_tool,
        "fallback_args": fallback_args,
        "recovery": "Run database migrations if diagnostics reports stale schema, then retry the tool.",
        "_meta": {
            "next_commands": next_commands,
            "unsafe_for_clinical_use": True,
        },
    }
    return ToolError(json.dumps(payload, separators=(",", ":"), sort_keys=True))


async def run_mcp_tool(
    tool_name: str,
    func: Callable[[], Awaitable[dict[str, Any]]],
    *,
    pmids: list[str] | None = None,
    fallback_tool: str | None = None,
    fallback_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        return await func()
    except ToolError:
        raise
    except Exception as exc:
        raise mcp_tool_error(
            exc,
            McpErrorContext(
                tool_name=tool_name,
                pmids=pmids,
                fallback_tool=fallback_tool,
                fallback_args=fallback_args,
            ),
        ) from exc
```

- [ ] **Step 4: Configure FastMCP masking**

Modify `pubtator_link/mcp/facade.py`:

```python
mcp = FastMCP(
    name="pubtator-link",
    mask_error_details=True,
    instructions=(...),
)
```

- [ ] **Step 5: Wrap MCP tools**

For each MCP tool function, replace direct adapter return with `run_mcp_tool`.

Example for `pubtator.index_review_evidence`:

```python
from pubtator_link.mcp.errors import run_mcp_tool

return await run_mcp_tool(
    "pubtator.index_review_evidence",
    lambda: index_review_evidence_impl(
        queue=queue,
        review_id=review_id,
        pmids=pmids,
        curated_urls=curated_urls,
        prepare_mode=prepare_mode,
    ),
    pmids=pmids or [],
)
```

Example for read-only search:

```python
return await run_mcp_tool(
    "pubtator.search_literature",
    lambda: search_literature_impl(...),
)
```

- [ ] **Step 6: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/mcp tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: centralize MCP error handling"
```

---

### Task 4: Add Diagnostics Service, REST Readiness Details, And MCP Tool

**Files:**
- Create: `pubtator_link/services/diagnostics.py`
- Create: `pubtator_link/mcp/tools/diagnostics.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/models/responses.py`
- Test: `tests/unit/test_diagnostics_service.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing diagnostics tests**

Create `tests/unit/test_diagnostics_service.py`:

```python
import pytest

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.services.diagnostics import DiagnosticsService


@pytest.mark.asyncio
async def test_diagnostics_reports_stale_schema_with_recovery() -> None:
    async def inspect_schema():
        return ReviewSchemaDiagnostics(
            connected=True,
            current=False,
            applied_versions=["0001_review_schema_base"],
            missing_tables=[],
            missing_columns=["reviews.updated_at"],
        )

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: False,
    )

    response = await service.get_diagnostics()

    assert response.success is True
    assert response.status == "degraded"
    assert response.subsystems["database"]["schema_current"] is False
    assert "make db-migrate" in response.recovery[0]
```

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_diagnostics_tool_is_registered() -> None:
    mcp = create_pubtator_mcp()

    assert "pubtator.diagnostics" in mcp._tool_manager._tools
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_diagnostics_service.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: fail because diagnostics service/tool do not exist.

- [ ] **Step 3: Add response model**

In `pubtator_link/models/responses.py`:

```python
class DiagnosticsResponse(BaseResponse):
    status: str = Field(..., description="ready, degraded, or not_ready")
    subsystems: dict[str, dict[str, Any]] = Field(default_factory=dict)
    recovery: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement diagnostics service**

Create `pubtator_link/services/diagnostics.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from pubtator_link.db.migrate import ReviewSchemaDiagnostics
from pubtator_link.models.responses import DiagnosticsResponse


class DiagnosticsService:
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
```

- [ ] **Step 5: Add dependency and MCP tool**

In `dependencies.py`, add a diagnostics dependency that uses `inspect_review_schema`.

Create `pubtator_link/mcp/tools/diagnostics.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.api.routes.dependencies import get_diagnostics_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.models.responses import DiagnosticsResponse


def register_diagnostics_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.diagnostics",
        title="PubTator-Link Diagnostics",
        output_schema=DiagnosticsResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def diagnostics() -> dict[str, Any]:
        """Use this to check PubTator-Link subsystem status and recovery commands. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_diagnostics_service()
        return await run_mcp_tool(
            "pubtator.diagnostics",
            lambda: _diagnostics_impl(service),
        )


async def _diagnostics_impl(service: Any) -> dict[str, Any]:
    return (await service.get_diagnostics()).model_dump()
```

Register it in `pubtator_link/mcp/facade.py` before review tools.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_diagnostics_service.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/services/diagnostics.py pubtator_link/mcp/tools/diagnostics.py pubtator_link/mcp/facade.py pubtator_link/api/routes/dependencies.py pubtator_link/models/responses.py tests/unit/test_diagnostics_service.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: expose MCP diagnostics"
```

---

### Task 5: Compact Search Payloads, Plain Highlights, Entity IDs, And Guideline Boost

**Files:**
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/api/routes/search.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_search.py`

- [ ] **Step 1: Write failing search adapter tests**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_search_literature_compact_omits_bibtex_and_plainifies_text_hl() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {
                        "pmid": "1",
                        "title": "FMF guideline",
                        "journal": "Ann Rheum Dis",
                        "date": "2025-01-01T00:00:00Z",
                        "text_hl": "@GENE_MEFV @@@MEFV@@@ in @DISEASE_FMF @@@FMF@@@",
                        "citations": {"NLM": "NLM citation", "BibTeX": "@article{x}"},
                    }
                ],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        include_citations="nlm",
        text_hl_format="plain",
        limit=5,
    )

    first = result["results"][0]
    assert first["text_hl"] == "MEFV in FMF"
    assert first["citations"] == {"NLM": "NLM citation"}
    assert "BibTeX" not in first["citations"]


@pytest.mark.asyncio
async def test_search_literature_combines_entity_ids_with_text() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    captured = {}

    class FakeClient:
        async def search_publications(self, **kwargs):
            captured.update(kwargs)
            return {"results": [], "count": 0, "total_pages": 0, "page_size": 10}

    await search_literature_impl(
        client=FakeClient(),
        text="colchicine",
        entity_ids=["@GENE_MEFV", "@DISEASE_FMF"],
    )

    assert captured["text"] == "(colchicine) AND @GENE_MEFV AND @DISEASE_FMF"


@pytest.mark.asyncio
async def test_search_literature_guideline_boost_reranks_page() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [
                    {"pmid": "1", "title": "Narrative review", "score": 10.0},
                    {
                        "pmid": "2",
                        "title": "EULAR recommendations for FMF",
                        "score": 5.0,
                        "publication_types": ["Practice Guideline"],
                    },
                ],
                "count": 2,
                "total_pages": 1,
                "page_size": 10,
            }

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        guideline_boost=True,
        response_mode="full",
    )

    assert [item["pmid"] for item in result["results"]] == ["2", "1"]
    assert result["results"][0]["rank_features"]["guideline_boost"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: fail because new search args are unsupported.

- [ ] **Step 3: Extend models**

In `SearchResult`, add:

```python
coverage_hint: dict[str, Any] | None = None
rank_features: dict[str, Any] | None = None
matched_terms: list[str] = Field(default_factory=list)
```

In `SearchResponse`, add:

```python
cache_key: str | None = None
corpus_snapshot_date: str | None = None
source_versions: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Implement search shaping helpers**

In `service_adapters.py`, add:

```python
import hashlib
import re
from datetime import UTC, date

SearchResponseMode = Literal["compact", "standard", "full"]
IncludeCitations = Literal["none", "nlm", "bibtex", "both"]
TextHighlightFormat = Literal["none", "plain", "annotated"]


def _plain_text_hl(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"@\w+(?::[\w.-]+)?", "", value)
    text = re.sub(r"@@@([^@]+)@@@", r"\1", text)
    text = re.sub(r"</?m>", "", text)
    return " ".join(text.split())


def _shape_citations(citations: dict[str, str] | None, mode: IncludeCitations) -> dict[str, str] | None:
    if not citations or mode == "none":
        return None
    shaped: dict[str, str] = {}
    if mode in {"nlm", "both"} and "NLM" in citations:
        shaped["NLM"] = citations["NLM"]
    if mode in {"bibtex", "both"} and "BibTeX" in citations:
        shaped["BibTeX"] = citations["BibTeX"]
    return shaped or None


def _combined_search_text(text: str, entity_ids: list[str] | None) -> str:
    ids = [item.strip() for item in entity_ids or [] if item.strip()]
    if not ids:
        return text.strip()
    entity_query = " AND ".join(ids)
    stripped = text.strip()
    return f"({stripped}) AND {entity_query}" if stripped else entity_query
```

Add guideline scoring:

```python
GUIDELINE_TERMS = ("recommendation", "guideline", "consensus", "eular", "pres", "share")
GUIDELINE_TYPES = (
    "guideline",
    "practice guideline",
    "consensus",
    "consensus development conference",
    "systematic review",
)


def _guideline_rank_features(item: dict[str, Any]) -> dict[str, Any]:
    publication_types = [str(value).lower() for value in item.get("publication_types", [])]
    title = str(item.get("title") or "").lower()
    abstract = str(item.get("abstract") or "").lower()
    type_boost = sum(3 for value in publication_types if any(term in value for term in GUIDELINE_TYPES))
    term_boost = sum(1 for term in GUIDELINE_TERMS if term in title or term in abstract)
    return {"guideline_boost": type_boost + term_boost}
```

In `search_literature_impl`, add parameters:

```python
response_mode: SearchResponseMode = "compact"
include_citations: IncludeCitations = "none"
text_hl_format: TextHighlightFormat = "plain"
limit: int | None = 5
entity_ids: list[str] | None = None
guideline_boost: bool = False
```

Apply:

- combine text/entity IDs before calling client,
- sort page by `rank_features["guideline_boost"]` descending then original order when `guideline_boost=True`,
- trim to `limit` after rerank,
- omit `abstract`, `annotations`, `citations`, or `text_hl` in compact mode unless requested,
- include `cache_key`, `corpus_snapshot_date`, and `source_versions={"pubtator3": "live"}`.

- [ ] **Step 5: Expose MCP and REST args**

In `mcp/tools/literature.py`, add parameters to `search_literature`:

```python
response_mode: Literal["compact", "standard", "full"] = "compact"
include_citations: Literal["none", "nlm", "bibtex", "both"] = "none"
text_hl_format: Literal["none", "plain", "annotated"] = "plain"
limit: Annotated[int | None, Field(ge=1, le=20)] = 5
entity_ids: list[str] | None = None
guideline_boost: bool = False
```

Add `pubtator.search_guidelines` as a wrapper that calls `search_literature_impl` with:

```python
publication_types=["Guideline", "Practice Guideline", "Consensus Development Conference", "Systematic Review"]
guideline_boost=True
include_citations="nlm"
limit=5
```

For REST, expose the same options but keep defaults:

```python
response_mode: SearchResponseMode = "standard"
include_citations: IncludeCitations = "both"
text_hl_format: TextHighlightFormat = "annotated"
limit: int | None = None
entity_ids: list[str] | None = None
guideline_boost: bool = False
```

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_search.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/models/responses.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/literature.py pubtator_link/api/routes/search.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_search.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: compact and stabilize literature search"
```

---

### Task 6: Add Entity Matched Terms And Output Schema

**Files:**
- Modify: `pubtator_link/models/responses.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing matched terms test**

Add:

```python
@pytest.mark.asyncio
async def test_search_entities_derives_matched_terms_from_match_text() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl

    class FakeClient:
        async def autocomplete_entity(self, query: str, concept: str | None, limit: int):
            return [
                {
                    "_id": "@DISEASE_FMF",
                    "name": "Familial Mediterranean Fever",
                    "biotype": "Disease",
                    "match": "Matched on synonyms <m>FMF, periodic fever</m>",
                }
            ]

    result = await search_biomedical_entities_impl(
        client=FakeClient(),
        query="FMF",
        concept="Disease",
    )

    assert result["matches"][0]["matched_terms"] == ["FMF", "periodic fever"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_search_entities_derives_matched_terms_from_match_text -q
```

Expected: fail because `matched_terms` is missing.

- [ ] **Step 3: Extend model and adapter**

Add to `EntityMatch`:

```python
matched_terms: list[str] = Field(default_factory=list, description="Terms derived from upstream match metadata")
```

Add helper:

```python
def _matched_terms(value: str | None) -> list[str]:
    if not value:
        return []
    cleaned = re.sub(r"</?m>", "", value)
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    if "synonyms" in cleaned.lower():
        cleaned = cleaned.split("synonyms", 1)[-1]
    return [term.strip(" .") for term in cleaned.split(",") if term.strip(" .")]
```

Pass `matched_terms=_matched_terms(item.get("match"))` when building `EntityMatch`.

Add `output_schema=EntityAutocompleteResponse.model_json_schema()` to `pubtator.search_biomedical_entities`.

- [ ] **Step 4: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/models/responses.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/literature.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: expose entity match terms"
```

---

### Task 7: Add Publication Passage Coverage, Failed PMIDs, And Warnings

**Files:**
- Modify: `pubtator_link/models/publication_passages.py`
- Modify: `pubtator_link/services/publication_passage_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_publication_passage_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing passage coverage tests**

Add to `tests/unit/test_publication_passage_service.py`:

```python
@pytest.mark.asyncio
async def test_section_text_warns_when_only_abstract_passages_returned() -> None:
    from pubtator_link.models.publication_passages import PublicationPassageRequest
    from pubtator_link.services.publication_passage_service import PublicationPassageService

    class FakePublicationService:
        async def export_publications_list(self, pmids, format, full):
            return {
                "documents": [
                    {
                        "id": "39540697",
                        "passages": [
                            {"infons": {"section_type": "title"}, "text": "FMF in Childhood"},
                            {"infons": {"section_type": "abstract"}, "text": "FMF is common."},
                        ],
                    }
                ]
            }

    service = PublicationPassageService(FakePublicationService())
    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["39540697"],
            mode="section_text",
            full=True,
            max_passages_per_pmid=5,
        )
    )

    assert response.coverage_by_pmid["39540697"] == "abstract_only"
    assert response.failed_pmids == []
    assert any("No full-text section passages" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_publication_passages_reports_failed_pmids() -> None:
    from pubtator_link.models.publication_passages import PublicationPassageRequest
    from pubtator_link.services.publication_passage_service import PublicationPassageService

    class FakePublicationService:
        async def export_publications_list(self, pmids, format, full):
            return {"documents": []}

    service = PublicationPassageService(FakePublicationService())
    response = await service.get_passages(PublicationPassageRequest(pmids=["1"]))

    assert response.coverage_by_pmid["1"] == "unknown"
    assert response.failed_pmids[0].pmid == "1"
    assert response.failed_pmids[0].reason == "No PubTator passages found"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py -q
```

Expected: fail because new fields do not exist.

- [ ] **Step 3: Extend passage models**

In `models/publication_passages.py`:

```python
PublicationCoverage = Literal["full_text", "abstract_only", "title_only", "unknown"]


class FailedPublicationPmid(BaseModel):
    pmid: str
    reason: str


class PublicationPassageResponse(BaseModel):
    ...
    coverage_by_pmid: dict[str, PublicationCoverage] = Field(default_factory=dict)
    coverage_reason_by_pmid: dict[str, str] = Field(default_factory=dict)
    failed_pmids: list[FailedPublicationPmid] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    cache_key: str | None = None
    corpus_snapshot_date: str | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Implement coverage inference**

In `PublicationPassageService`, add:

```python
def _coverage_for_pmid(self, passages: list[PublicationPassage], pmid: str) -> tuple[str, str]:
    sections = {passage.section for passage in passages if passage.pmid == pmid}
    if any(section not in {"title", "abstract"} for section in sections):
        return "full_text", "full_text_sections_returned"
    if "abstract" in sections:
        return "abstract_only", "abstract_fallback_used"
    if "title" in sections:
        return "title_only", "title_only_metadata"
    return "unknown", "no_passages_returned"
```

After budgeting, build:

```python
coverage_by_pmid = {}
coverage_reason_by_pmid = {}
failed_pmids = []
warnings = []
for pmid in request.pmids:
    coverage, reason = self._coverage_for_pmid(passages, pmid)
    coverage_by_pmid[pmid] = coverage
    coverage_reason_by_pmid[pmid] = reason
    if coverage == "unknown":
        failed_pmids.append(FailedPublicationPmid(pmid=pmid, reason="No PubTator passages found"))
    if request.full and request.mode == "section_text" and coverage in {"abstract_only", "title_only"}:
        warnings.append(
            f"No full-text section passages were available for PMID {pmid}; returned {coverage.replace('_', '-')} PubTator passages."
        )
```

Add deterministic `cache_key` and current UTC `corpus_snapshot_date`.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/models/publication_passages.py pubtator_link/services/publication_passage_service.py pubtator_link/mcp/service_adapters.py tests/unit/test_publication_passage_service.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: report publication passage coverage"
```

---

### Task 8: Add Search Coverage Preflight

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/api/routes/search.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_search.py`

- [ ] **Step 1: Write failing coverage test**

Add:

```python
@pytest.mark.asyncio
async def test_search_literature_attaches_preflight_coverage() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl
    from pubtator_link.models.review_rerag import SourceCoverageHint

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {
                "results": [{"pmid": "39540697", "title": "FMF in Childhood"}],
                "count": 1,
                "total_pages": 1,
                "page_size": 10,
            }

    class FakePreflight:
        async def preflight_pmids(self, pmids):
            return [
                SourceCoverageHint(
                    pmid="39540697",
                    expected_coverage="abstract_only",
                    coverage_reason="no_pmcid",
                )
            ]

    result = await search_literature_impl(
        client=FakeClient(),
        text="FMF",
        coverage="preflight",
        preflight_service=FakePreflight(),
    )

    assert result["results"][0]["coverage_hint"]["expected_coverage"] == "abstract_only"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_search_literature_attaches_preflight_coverage -q
```

Expected: fail because `coverage` and `preflight_service` are unsupported.

- [ ] **Step 3: Add optional preflight service parameter**

Extend `search_literature_impl`:

```python
coverage: Literal["none", "preflight"] = "none"
preflight_service: Any | None = None
```

After shaping/trimming results:

```python
if coverage == "preflight" and preflight_service is not None:
    hints = await preflight_service.preflight_pmids([result.pmid for result in search_results])
    hints_by_pmid = {hint.pmid: hint.model_dump(mode="json") for hint in hints}
    for result in search_results:
        result.coverage_hint = hints_by_pmid.get(result.pmid)
```

If preflight fails, add a response-level warning in `source_versions` or `message`:

```python
message="Coverage preflight failed; search results returned without coverage hints."
```

- [ ] **Step 4: Wire MCP and REST dependencies**

MCP `search_literature` should call `get_source_preflight_service()` only when `coverage == "preflight"`.

REST route should accept `coverage` and use the app-bound source preflight service when available.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_search.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/mcp/tools/literature.py pubtator_link/mcp/service_adapters.py pubtator_link/api/routes/search.py pubtator_link/api/routes/dependencies.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_search.py
git commit -m "feat: add search coverage preflight"
```

---

### Task 9: Add Review Retrieval Dry Run And Reproducibility Metadata

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/services/review_context/diagnostics.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/test_review_context_diagnostics.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing dry-run test**

Add to `tests/unit/test_review_context_service.py`:

```python
@pytest.mark.asyncio
async def test_batch_dry_run_returns_diagnostics_without_passage_text(repository):
    from pubtator_link.models.review_rerag import RetrieveReviewContextBatchRequest
    from pubtator_link.services.review_context_service import ReviewContextService

    service = ReviewContextService(repository=repository)
    response = await service.retrieve_context_batch(
        review_id="review-1",
        request=RetrieveReviewContextBatchRequest(
            queries=["colchicine response"],
            dry_run=True,
            response_mode="diagnostics",
        ),
    )

    assert response.response_mode == "diagnostics"
    assert response.merged_context_pack.passages == []
    assert response.cache_key is not None
    assert response.corpus_snapshot_date is not None
```

Add to `tests/unit/test_review_context_diagnostics.py`:

```python
def test_zero_result_reason_includes_coverage_abstract_only() -> None:
    from pubtator_link.models.review_rerag import QueryDiagnosticsSummary

    summary = QueryDiagnosticsSummary(
        query="dose table",
        query_tokens=["dose", "table"],
        zero_result_reason="coverage_abstract_only",
    )

    assert summary.zero_result_reason == "coverage_abstract_only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_context_diagnostics.py -q
```

Expected: fail because `dry_run`, response metadata, and new zero-result reason do not exist.

- [ ] **Step 3: Extend models**

In `ZeroResultReason`, add:

```python
"no_pmids_indexed",
"coverage_abstract_only",
```

In `RetrieveReviewContextBatchRequest`, add:

```python
dry_run: bool = False
```

In `RetrieveReviewContextBatchResponse`, add:

```python
cache_key: str | None = None
corpus_snapshot_date: str | None = None
source_versions: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Implement dry run**

In `ReviewContextService.retrieve_context_batch`, if `request.dry_run`:

- force diagnostics path,
- run the existing search/diagnostic summaries,
- return empty `merged_context_pack.passages`,
- keep `query_summaries`,
- set reproducibility metadata,
- do not pack passage text.

Use a helper:

```python
def _request_cache_key(tool_name: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps({"tool": tool_name, "payload": payload}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_context_diagnostics.py tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: pass.

Commit:

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/services/review_context/diagnostics.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py tests/unit/test_review_context_service.py tests/unit/test_review_context_diagnostics.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: add review retrieval dry run"
```

---

### Task 10: Documentation, Resources, And Instructions

**Files:**
- Modify: `README.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/development/operations-runbook.md`
- Modify: `docker/README.md`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/facade.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing docs/resource tests**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_capabilities_document_error_recovery_and_compact_search() -> None:
    resource = get_server_capabilities()
    text = json.dumps(resource).lower()

    assert "db-migrate" in text
    assert "get_publication_passages" in text
    assert "text_hl_format" in text
    assert "include_citations" in text
    assert "review_id" in text


def test_server_instructions_include_schema_failure_fallback() -> None:
    mcp = create_pubtator_mcp()
    instructions = mcp.instructions.lower()

    assert "if index_review_evidence is unavailable" in instructions
    assert "get_publication_passages" in instructions
    assert "pubtator.diagnostics" in instructions
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: fail because docs/resources do not mention new recovery flow.

- [ ] **Step 3: Update MCP instructions and resources**

In `facade.py`, include:

```text
If pubtator.index_review_evidence is unavailable, call pubtator.diagnostics and fall back to pubtator.get_publication_passages with the same PMIDs.
```

In `resources.py`, add:

- core tools list,
- advanced tools list,
- recovery flow,
- compact search default examples,
- review ID semantics,
- migration command.

- [ ] **Step 4: Update docs**

Add to docs:

- `make db-migrate` repairs existing review DBs,
- Docker rebuild does not reset existing PostgreSQL volumes,
- `review_id` is a durable caller namespace,
- `search_literature` compact defaults and opt-in citation/highlight controls,
- fallback path when review indexing is unavailable,
- diagnostics tool usage.

- [ ] **Step 5: Run tests and commit**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

Commit:

```bash
git add README.md docs/MCP_CONNECTION_GUIDE.md docs/development/operations-runbook.md docker/README.md pubtator_link/mcp/resources.py pubtator_link/mcp/facade.py tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: document MCP recovery workflow"
```

---

### Task 11: Apply Migration To Live Docker Stack And Smoke Test

**Files:**
- No source file changes unless a smoke test reveals a defect.

- [ ] **Step 1: Apply migration to the current Docker database**

Run:

```bash
PUBTATOR_LINK_DATABASE_URL=postgresql://pubtator_link:pubtator_link@localhost:55432/pubtator_link make db-migrate
```

Expected: migration applies or reports `none`; schema diagnostics are current.

- [ ] **Step 2: Verify live schema**

Run:

```bash
docker compose -f docker/docker-compose.yml exec -T pubtator-postgres psql -U pubtator_link -d pubtator_link -c "select column_name from information_schema.columns where table_name='reviews' order by ordinal_position;"
```

Expected: includes `review_id`, `created_at`, and `updated_at`.

- [ ] **Step 3: Restart server**

Run:

```bash
make docker-down
make docker-up
```

Expected: containers become healthy.

- [ ] **Step 4: Smoke test readiness and indexing**

Run:

```bash
curl -fsS http://127.0.0.1:8011/ready
curl -fsS -X POST http://127.0.0.1:8011/api/reviews/rev_eval_probe/evidence/index \
  -H 'content-type: application/json' \
  -d '{"pmids":["39540697"],"prepare_mode":"selected"}'
```

Expected:

- `/ready` reports database `schema_current: true`,
- index route returns `success: true` with queued or already prepared counts,
- no `updated_at` error appears in Docker logs.

- [ ] **Step 5: Record no source changes**

Run:

```bash
git status --short
```

Expected: no source changes from this smoke task.

---

### Task 12: Final Verification

**Files:**
- No source file changes unless verification finds a defect.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest \
  tests/unit/test_db_migrations.py \
  tests/unit/test_mcp_errors.py \
  tests/unit/test_diagnostics_service.py \
  tests/unit/test_publication_passage_service.py \
  tests/unit/test_review_context_service.py \
  tests/unit/test_review_context_diagnostics.py \
  tests/test_routes/test_search.py \
  tests/test_routes/test_reviews.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_review_rerag_mcp.py \
  -q
```

Expected: all pass.

- [ ] **Step 2: Run required repo verification**

Run:

```bash
make ci-local
```

Expected: pass.

- [ ] **Step 3: Review git history**

Run:

```bash
git status --short --branch
git log --oneline -12
```

Expected: clean except the pre-existing untracked evaluation document, if still present; commits exist for each completed task.

- [ ] **Step 4: Final commit only if verification fixes were needed**

If final verification required any fixes, stage only the files changed by those fixes after
reviewing `git status --short`:

```bash
git add -u pubtator_link tests docs docker README.md Makefile
git commit -m "fix: stabilize MCP verification"
```

If no fixes were needed, do not create an empty commit.
