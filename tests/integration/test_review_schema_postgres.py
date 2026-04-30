import os
from pathlib import Path

import asyncpg
import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_review_schema_applies_to_postgres() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    conn = await asyncpg.connect(database_url)
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
