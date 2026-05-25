from pathlib import Path
from typing import NamedTuple

from pubtator_link.db.migrate import (
    MIGRATIONS_PACKAGE,
    _is_non_transactional_migration,
    required_review_schema_items,
    schema_repair_statements,
)


class RequiredSchemaItem(NamedTuple):
    kind: str
    name: str


def iter_sql_migrations() -> list[Path]:
    return sorted(Path("pubtator_link/db/migrations").glob("*.sql"))


REQUIRED_SCHEMA_ITEMS = tuple(
    RequiredSchemaItem(kind="table", name=name) for name in required_review_schema_items().tables
)


def test_migration_files_are_ordered_and_include_repair_migration() -> None:
    migration_dir = Path("pubtator_link/db/migrations")
    names = sorted(path.name for path in migration_dir.glob("*.sql"))

    assert names == [
        "0001_review_schema_base.sql",
        "0002_review_schema_drift_repair.sql",
        "0003_review_session_sources_repair.sql",
        "0004_review_llm_context.sql",
        "0005_review_passage_embeddings.sql",
        "0006_benchmark_suite.sql",
    ]
    assert MIGRATIONS_PACKAGE == "pubtator_link.db.migrations"


def test_review_passage_embeddings_migration_is_bundled() -> None:
    migration_names = [path.name for path in iter_sql_migrations()]
    assert "0005_review_passage_embeddings.sql" in migration_names


def test_required_schema_includes_review_passage_embeddings() -> None:
    required_tables = {item.name for item in REQUIRED_SCHEMA_ITEMS if item.kind == "table"}
    assert "review_passage_embeddings" in required_tables


def test_repair_migration_adds_reviews_updated_at_without_dropping_data() -> None:
    sql = Path("pubtator_link/db/migrations/0002_review_schema_drift_repair.sql").read_text()

    assert "alter table reviews add column if not exists updated_at" in sql.lower()
    assert "update reviews set updated_at = coalesce(updated_at, created_at, now())" in sql.lower()
    assert "create index if not exists reviews_updated_at_idx" in sql.lower()
    assert "drop table" not in sql.lower()
    assert "truncate" not in sql.lower()


def test_base_migration_repairs_reviews_updated_at_before_indexing() -> None:
    sql = Path("pubtator_link/db/migrations/0001_review_schema_base.sql").read_text().lower()

    repair_position = sql.index("alter table reviews add column if not exists updated_at")
    index_position = sql.index("create index if not exists reviews_updated_at_idx")

    assert repair_position < index_position


def test_required_schema_items_include_review_tables_and_columns() -> None:
    required = required_review_schema_items()

    assert ("reviews", "updated_at") in required.columns
    assert ("full_text_retrieval_attempts", "coverage_reason") in required.columns
    assert "review_research_sessions" in required.tables
    assert "review_research_session_candidates" in required.tables
    assert "review_session_sources" in required.tables
    assert "review_evidence_certainty" in required.tables
    assert "review_llm_context" in required.tables
    assert "review_llm_context_events" in required.tables
    assert ("review_llm_context", "context_id") in required.columns
    assert ("review_llm_context", "response_summary") in required.columns
    assert ("review_llm_context_events", "payload") in required.columns


def test_schema_repair_statements_are_non_destructive() -> None:
    statements = schema_repair_statements()
    joined = "\n".join(statements).lower()

    assert "drop table" not in joined
    assert "drop column" not in joined
    assert "truncate" not in joined
    assert any(
        "alter table reviews add column if not exists updated_at" in item.lower()
        for item in statements
    )


def test_migration_without_sentinel_runs_inside_transaction_wrapper() -> None:
    sql = "CREATE TABLE foo (id int);"
    assert _is_non_transactional_migration(sql) is False


def test_migration_with_sentinel_in_first_lines_skips_transaction_wrapper() -> None:
    sql = "-- pragma: non-transactional\nCREATE INDEX CONCURRENTLY ix_foo ON foo(id);"
    assert _is_non_transactional_migration(sql) is True


def test_sentinel_after_first_8_lines_is_ignored() -> None:
    sql = ("\n" * 9) + "-- pragma: non-transactional\nSELECT 1;"
    assert _is_non_transactional_migration(sql) is False
