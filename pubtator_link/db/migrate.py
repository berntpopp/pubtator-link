from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from importlib import resources

import asyncpg

from pubtator_link.config import review_rerag_config

MIGRATIONS_PACKAGE = "pubtator_link.db.migrations"


@dataclass(frozen=True)
class RequiredSchemaItems:
    """Tables and columns required by the review storage layer."""

    tables: frozenset[str]
    columns: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ReviewSchemaDiagnostics:
    """Current review schema status."""

    connected: bool
    current: bool
    applied_versions: list[str]
    missing_tables: list[str]
    missing_columns: list[str]
    error: str | None = None


def required_review_schema_items() -> RequiredSchemaItems:
    """Return the minimum schema surface required by current review features."""
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
    """Return bundled SQL migrations in lexical version order."""
    package = resources.files(MIGRATIONS_PACKAGE)
    files = sorted(
        (path for path in package.iterdir() if path.name.endswith(".sql")),
        key=lambda path: path.name,
    )
    return [(path.name.removesuffix(".sql"), path.read_text()) for path in files]


def schema_repair_statements() -> list[str]:
    """Return repair migration statements for tests and diagnostics."""
    migration = resources.files(MIGRATIONS_PACKAGE).joinpath("0002_review_schema_drift_repair.sql")
    return [
        statement.strip() for statement in migration.read_text().split(";") if statement.strip()
    ]


async def apply_migrations(database_url: str | None = None) -> list[str]:
    """Apply unapplied review-storage migrations and return applied versions."""
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
    """Inspect whether review-storage schema contains the required current objects."""
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
        migration_rows = (
            await connection.fetch(
                """
                select version
                from schema_migrations
                order by version
                """
            )
            if "schema_migrations" in tables
            else []
        )
        missing_tables = sorted(required.tables - tables)
        missing_columns = [
            f"{table}.{column}" for table, column in sorted(required.columns - columns)
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
        _write_line(str(diagnostics))
        return 0 if diagnostics.current else 1
    applied = await apply_migrations()
    _write_line(f"Applied migrations: {', '.join(applied) if applied else 'none'}")
    diagnostics = await inspect_review_schema()
    if not diagnostics.current:
        _write_line(str(diagnostics))
        return 1
    return 0


def _write_line(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def main() -> None:
    raise SystemExit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
