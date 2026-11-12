"""#182: the backfill must page through a real corpus, resume, and be a no-op when done."""

import os

import asyncpg
import pytest

from pubtator_link.db.migrate import apply_migrations
from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository
from pubtator_link.services.review_context.embedding_backfill import (
    backfill_review_passage_embeddings,
)
from pubtator_link.services.review_context.embeddings import FakeEmbeddingProvider

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_backfill_resumes_through_chunks_and_reembeds_stale_text() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")
    try:
        await apply_migrations(database_url)
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=2)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL test database is not reachable: {exc}")
    review_id = "review-embed-backfill"
    passages = [
        ReviewPassageRow(
            passage_id=f"p{index}",
            review_id=review_id,
            source_id="111",
            source_kind="pubtator_abstract",
            pmid="111",
            section="abstract",
            text=f"Passage {index} about dystrophin.",
        )
        for index in range(5)
    ]

    async def backfill() -> int:
        result = await backfill_review_passage_embeddings(
            repository=repository,
            review_id=review_id,
            provider=FakeEmbeddingProvider(dim=384),
            model_name="fake",
            embedding_dim=384,
            batch_size=2,
            chunk_size=2,
        )
        assert result.error is None
        return result.embedded_count

    try:
        await pool.execute("delete from review_passages where review_id = $1", review_id)
        await pool.execute("delete from review_passage_embeddings where review_id = $1", review_id)
        await pool.execute(
            "insert into reviews (review_id) values ($1) on conflict do nothing", review_id
        )
        repository = PostgresReviewReragRepository(pool)
        await repository.upsert_passages(passages)

        # Chunk 2 < 5 rows: before the SQL filter fix, round two re-listed round one's rows.
        assert await backfill() == 5
        assert await backfill() == 0
        await repository.upsert_passages([passages[0].model_copy(update={"text": "Edited."})])
        assert await backfill() == 1
    finally:
        await pool.execute("delete from review_passages where review_id = $1", review_id)
        await pool.execute("delete from review_passage_embeddings where review_id = $1", review_id)
        await pool.close()
