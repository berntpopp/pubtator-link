from typing import Any
from uuid import UUID

import pytest

from pubtator_link.models.review_rerag import PreparationStatus, ReviewPassageRow
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository


class FakeAcquire:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> "FakeConnection":
        return self.connection

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakePool:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def acquire(self) -> FakeAcquire:
        return FakeAcquire(self.connection)


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetched_rows: list[dict[str, Any]] = []
        self.fetchrow_rows: list[dict[str, Any] | None] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "EXECUTE"

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.executed.append((sql, args))
        if self.fetchrow_rows:
            return self.fetchrow_rows.pop(0)
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.executed.append((sql, args))
        return self.fetched_rows

    async def executemany(self, sql: str, args: list[tuple[Any, ...]]) -> str:
        self.executemany_calls.append((sql, args))
        return "EXECUTEMANY"


@pytest.mark.asyncio
async def test_enqueue_preparation_job_creates_review_and_returns_status() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {"queued": 1, "running": 0, "complete": 0, "partial": 0, "failed": 0}
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    status = await repository.enqueue_preparation_job(
        review_id="review-1",
        source_id="40234174",
        source_kind="pubtator_abstract",
    )

    assert status == PreparationStatus(queued=1)
    assert len(connection.executed) == 3
    assert "insert into reviews" in connection.executed[0][0].lower()
    assert connection.executed[0][1] == ("review-1",)
    upsert_sql, upsert_args = connection.executed[1]
    assert "insert into review_preparation_jobs" in upsert_sql.lower()
    assert "source_kind" in upsert_sql
    assert "on conflict (review_id, source_id)" in upsert_sql.lower()
    assert isinstance(upsert_args[0], UUID)
    assert upsert_args[1:] == ("review-1", "40234174", "pubtator_abstract")


@pytest.mark.asyncio
async def test_upsert_passages_uses_executemany() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))
    passages = [
        ReviewPassageRow(
            passage_id="PMID:40234174:abstract:0",
            review_id="review-1",
            source_id="40234174",
            source_kind="pubtator_abstract",
            pmid="40234174",
            section="abstract",
            text="Colchicine should start after clinical diagnosis.",
            entity_ids=["MESH:D005201"],
            relation_types=["treats"],
            source_metadata={"rank": 1},
        )
    ]

    await repository.upsert_passages(passages)

    assert len(connection.executemany_calls) == 1
    sql, args = connection.executemany_calls[0]
    assert "insert into review_passages" in sql.lower()
    assert "on conflict (review_id, passage_id)" in sql.lower()
    assert args == [
        (
            "PMID:40234174:abstract:0",
            "review-1",
            "40234174",
            "pubtator_abstract",
            "40234174",
            None,
            None,
            None,
            "abstract",
            None,
            None,
            "Colchicine should start after clinical diagnosis.",
            ["MESH:D005201"],
            ["treats"],
            "candidate",
            '{"rank": 1}',
        )
    ]


@pytest.mark.asyncio
async def test_search_passages_maps_rows_and_uses_none_for_empty_filters() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "passage_id": "PMID:40234174:abstract:0",
            "review_id": "review-1",
            "source_id": "40234174",
            "source_kind": "pubtator_abstract",
            "pmid": "40234174",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "abstract",
            "heading_path": None,
            "page": None,
            "text": "Colchicine should start after clinical diagnosis.",
            "entity_ids": ["MESH:D005201"],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {"source": "pubtator"},
            "lexical_rank": 0.23,
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    rows = await repository.search_passages(
        review_id="review-1",
        query="when start colchicine",
        entity_ids=[],
        pmids=[],
        sections=[],
        limit=8,
    )

    assert rows == [
        ReviewPassageRow(
            passage_id="PMID:40234174:abstract:0",
            review_id="review-1",
            source_id="40234174",
            source_kind="pubtator_abstract",
            pmid="40234174",
            section="abstract",
            text="Colchicine should start after clinical diagnosis.",
            entity_ids=["MESH:D005201"],
            source_metadata={"source": "pubtator"},
            lexical_rank=0.23,
        )
    ]
    sql, args = connection.executed[0]
    assert "websearch_to_tsquery" in sql
    assert "source_kind" in sql
    assert args == ("review-1", "when start colchicine", None, None, None, 8)
