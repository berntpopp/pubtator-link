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
    assert "review_evidence_certainty" in required.tables


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
