from pathlib import Path

from pubtator_link.db.migrate import required_review_schema_items

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


def test_schema_defines_review_audit_events_table() -> None:
    assert "create table if not exists review_audit_events" in SCHEMA
    assert "event_type text not null" in SCHEMA
    assert "payload jsonb not null default '{}'::jsonb" in SCHEMA
    assert "review_audit_events_review_id_idx" in SCHEMA


def test_review_llm_context_tables_are_declared() -> None:
    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS review_llm_context" in schema
    assert "CREATE TABLE IF NOT EXISTS review_llm_context_events" in schema
    assert "CREATE INDEX IF NOT EXISTS idx_review_llm_context_events_review" in schema
    assert "review_id TEXT NOT NULL REFERENCES reviews(review_id)" in schema
    assert "UNIQUE (context_id, review_id)" in schema
    assert (
        "FOREIGN KEY (context_id, review_id)\n"
        "        REFERENCES review_llm_context(context_id, review_id)"
    ) in schema


def test_schema_defines_research_session_tables() -> None:
    assert "create table if not exists review_research_sessions" in SCHEMA
    assert "create table if not exists review_research_session_candidates" in SCHEMA
    assert "review_research_sessions_review_id_idx" in SCHEMA
    assert "review_research_session_candidates_session_idx" in SCHEMA
    assert "unique(review_id, session_id, pmid)" in SCHEMA


def test_schema_defines_review_session_source_links() -> None:
    migration = Path("pubtator_link/db/migrations/0002_review_schema_drift_repair.sql").read_text()
    repair_migration = Path(
        "pubtator_link/db/migrations/0003_review_session_sources_repair.sql"
    ).read_text()

    for sql in (SCHEMA, migration, repair_migration):
        assert "create table if not exists review_session_sources" in sql
        assert "primary key(review_id, session_id, source_id)" in sql
        assert "references review_research_sessions(review_id, session_id)" in sql
        assert "references review_preparation_jobs(review_id, source_id)" in sql


def test_schema_diagnostics_require_review_session_source_links() -> None:
    required = required_review_schema_items()

    assert "review_session_sources" in required.tables


def test_schema_diagnostics_require_review_llm_context_columns() -> None:
    required = required_review_schema_items()

    context_columns = {
        "context_id",
        "review_id",
        "session_id",
        "kind",
        "topic",
        "research_question",
        "question_hash",
        "request",
        "response_summary",
        "selected_pmids",
        "rejected_pmids",
        "preferred_entity_ids",
        "active_queries",
        "successful_queries",
        "failed_queries",
        "selected_passage_ids",
        "audit_passage_ids",
        "open_questions",
        "user_decisions",
        "last_next_commands",
        "stable_citation_keys",
        "cache_key",
        "token_estimate",
        "created_by",
        "created_at",
        "updated_at",
    }
    event_columns = {
        "event_id",
        "context_id",
        "review_id",
        "session_id",
        "event_type",
        "summary",
        "pmids",
        "passage_ids",
        "queries",
        "decision",
        "payload",
        "created_by",
        "created_at",
    }
    for column in context_columns:
        assert ("review_llm_context", column) in required.columns
    for column in event_columns:
        assert ("review_llm_context_events", column) in required.columns


def test_schema_tracks_review_inventory_timestamps() -> None:
    assert "updated_at timestamptz not null default now()" in SCHEMA
    assert "reviews_updated_at_idx" in SCHEMA


def test_schema_defines_review_evidence_certainty_table() -> None:
    assert "create table if not exists review_evidence_certainty" in SCHEMA
    assert "certainty_id uuid primary key" in SCHEMA
    assert "overall_certainty text not null" in SCHEMA
    assert "passage_ids text[] not null default '{}'" in SCHEMA
    assert "review_evidence_certainty_review_id_idx" in SCHEMA


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
