import os
from pathlib import Path

import asyncpg
import pytest

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository

pytestmark = pytest.mark.integration


async def _connect_or_skip(database_url: str) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(database_url)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL test database is not reachable: {exc}")


@pytest.mark.asyncio
async def test_review_schema_applies_to_postgres() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    conn = await _connect_or_skip(database_url)
    try:
        await conn.execute(schema)
        rows = await conn.fetch(
            """
            select tablename
            from pg_tables
            where schemaname = 'public'
              and tablename in (
                'reviews',
                'review_preparation_jobs',
                'full_text_retrieval_attempts',
                'review_passages'
              )
            """
        )
    finally:
        await conn.close()

    assert {row["tablename"] for row in rows} == {
        "reviews",
        "review_preparation_jobs",
        "full_text_retrieval_attempts",
        "review_passages",
    }


@pytest.mark.asyncio
async def test_review_index_inspection_queries_postgres_schema() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    conn = await _connect_or_skip(database_url)
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=1)
    try:
        await conn.execute(schema)
        await conn.execute(
            """
            delete from review_passages;
            delete from full_text_retrieval_attempts;
            delete from review_preparation_jobs;
            delete from reviews;
            """
        )
        repository = PostgresReviewReragRepository(pool)
        await repository.enqueue_preparation_job("review-inspect", "111", "pubtator_abstract")
        await repository.mark_job_finished(
            review_id="review-inspect",
            source_id="111",
            status="complete",
            error=None,
        )
        await repository.enqueue_preparation_job("review-inspect", "PMID:222", "pubtator_full_bioc")
        await repository.mark_job_finished(
            review_id="review-inspect",
            source_id="PMID:222",
            status="failed",
            error="not available",
        )
        await repository.record_retrieval_attempt(
            "review-inspect",
            "PMID:222",
            "pubtator_full_bioc",
            "not_available",
            reason="not available",
        )
        await repository.enqueue_preparation_job(
            "review-inspect",
            "URL:https://example.org/paper.pdf",
            "curated_pdf",
        )
        await repository.mark_job_finished(
            review_id="review-inspect",
            source_id="URL:https://example.org/paper.pdf",
            status="failed",
            error=None,
        )
        await repository.record_retrieval_attempt(
            "review-inspect",
            "https://example.org/paper.pdf",
            "curated_pdf",
            "blocked",
            reason="Curated URL did not return PDF bytes",
        )
        await repository.upsert_passages(
            [
                ReviewPassageRow(
                    passage_id="p1",
                    review_id="review-inspect",
                    source_id="111",
                    source_kind="pubtator_abstract",
                    pmid="111",
                    section="abstract",
                    text="Indexed passage text.",
                )
            ]
        )

        sources = await repository.list_review_sources(
            "review-inspect",
            include_passage_samples=True,
            sample_per_pmid=1,
        )
        failed_sources = await repository.list_review_failed_sources("review-inspect")
        filtered_sources = await repository.list_review_sources("review-inspect", pmids=["222"])
        totals = await repository.review_index_totals("review-inspect")
    finally:
        await pool.close()
        await conn.close()

    assert sources[0].source_id == "111"
    assert sources[0].sample_passages[0].passage_id == "p1"
    failed_by_source = {source.source_id: source for source in failed_sources}
    assert failed_by_source["PMID:222"].pmid == "222"
    assert failed_by_source["PMID:222"].error == "not available"
    assert failed_by_source["URL:https://example.org/paper.pdf"].attempt_statuses == ["blocked"]
    assert failed_by_source["URL:https://example.org/paper.pdf"].error == (
        "Curated URL did not return PDF bytes"
    )
    assert [source.source_id for source in filtered_sources] == ["PMID:222"]
    assert totals.source_count == 1
    assert totals.failed_source_count == 2
