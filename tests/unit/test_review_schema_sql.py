from pathlib import Path

SCHEMA = Path("pubtator_link/db/review_schema.sql").read_text()


def test_schema_defines_required_tables_and_constraints() -> None:
    assert "create table if not exists reviews" in SCHEMA
    assert "review_id text primary key" in SCHEMA
    assert "create table if not exists review_preparation_jobs" in SCHEMA
    assert "unique(review_id, source_id)" in SCHEMA
    assert "create table if not exists full_text_retrieval_attempts" in SCHEMA
    assert "attempt_id uuid primary key" in SCHEMA
    assert "create table if not exists review_passages" in SCHEMA
    assert "primary key(review_id, passage_id)" in SCHEMA


def test_schema_defines_generated_search_vector_and_indexes() -> None:
    assert "search_vector tsvector generated always as" in SCHEMA
    assert "to_tsvector('english'" in SCHEMA
    assert "using gin(search_vector)" in SCHEMA
    assert "using gin(entity_ids)" in SCHEMA
    assert "review_passages_review_id_pmid_idx" in SCHEMA
    assert "review_attempts_audit_idx" in SCHEMA


def test_retrieval_attempts_schema_contains_audit_metadata_columns() -> None:
    for column in (
        "attempt_count",
        "last_status_code",
        "retry_after_ms",
        "backoff_ms",
        "terminal_reason",
        "pmcid",
        "doi",
        "license_or_access_hint",
    ):
        assert column in SCHEMA
