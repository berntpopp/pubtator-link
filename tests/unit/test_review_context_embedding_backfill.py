from __future__ import annotations

import logging
from typing import Any

import pytest

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.repositories.review_rerag import ReviewPassageEmbeddingRecord
from pubtator_link.services.review_context.embedding_backfill import (
    backfill_review_passage_embeddings,
)
from pubtator_link.services.review_context.embeddings import FakeEmbeddingProvider


class FakeEmbeddingBackfillRepository:
    def __init__(self, *, missing: list[ReviewPassageRow]) -> None:
        self.missing = missing
        self.upserted: list[ReviewPassageEmbeddingRecord] = []
        self.calls: list[dict[str, Any]] = []

    async def list_passages_missing_embeddings(
        self,
        review_id: str,
        *,
        model_name: str,
        limit: int,
    ) -> list[ReviewPassageRow]:
        self.calls.append({"review_id": review_id, "model_name": model_name, "limit": limit})
        done = {record.passage_id for record in self.upserted}
        return [row for row in self.missing if row.passage_id not in done][:limit]

    async def upsert_passage_embeddings(self, records: list[ReviewPassageEmbeddingRecord]) -> None:
        self.upserted.extend(records)


class StuckRepository(FakeEmbeddingBackfillRepository):
    """Re-lists rows after upsert (e.g. a text-hash mismatch) -- must not loop forever."""

    async def list_passages_missing_embeddings(
        self, review_id: str, *, model_name: str, limit: int
    ) -> list[ReviewPassageRow]:
        return self.missing[:limit]


class FailingEmbeddingProvider:
    model_name = "failing-provider"
    dim = 384

    async def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("provider failed")

    async def embed_passages(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("provider failed")


def passage(passage_id: str) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="r1",
        source_id="s1",
        source_kind="pubtator_full_bioc",
        section="DISCUSS",
        text="Colchicine dose adjustment evidence.",
        lexical_rank=1.0,
    )


async def test_backfill_embeds_missing_passages_in_batches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="pubtator_link.services.review_context.embedding_backfill",
    )
    repository = FakeEmbeddingBackfillRepository(missing=[passage("p1")])
    provider = FakeEmbeddingProvider(dim=384)

    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        chunk_size=100,
    )

    assert result.embedded_count == 1
    assert result.failed_count == 0
    assert repository.calls == [
        {
            "review_id": "r1",
            "model_name": "BAAI/bge-small-en-v1.5",
            "limit": 100,
        }
    ]
    assert repository.upserted[0].passage_id == "p1"
    assert repository.upserted[0].embedding_dim == 384
    records = [
        record
        for record in caplog.records
        if record.message == "review_embedding_backfill_completed"
    ]
    assert records
    assert records[0].review_id == "r1"
    assert records[0].embedded_count == 1
    assert records[0].elapsed_ms >= 0


async def test_backfill_reports_provider_failure_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.WARNING,
        logger="pubtator_link.services.review_context.embedding_backfill",
    )
    repository = FakeEmbeddingBackfillRepository(missing=[passage("p1")])
    provider = FailingEmbeddingProvider()

    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        chunk_size=100,
    )

    assert result.embedded_count == 0
    assert result.failed_count == 1
    assert result.error is not None
    assert repository.upserted == []
    records = [
        record for record in caplog.records if record.message == "review_embedding_backfill_failed"
    ]
    assert records
    assert records[0].failed_count == 1
    assert records[0].elapsed_ms >= 0


async def test_backfill_pages_through_chunks_and_is_idempotent() -> None:
    repository = FakeEmbeddingBackfillRepository(
        missing=[passage(f"p{index}") for index in range(5)]
    )
    progress: list[tuple[str, int]] = []

    first = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=FakeEmbeddingProvider(dim=8),
        model_name="fake",
        embedding_dim=8,
        batch_size=2,
        chunk_size=2,
        progress=lambda review_id, count: progress.append((review_id, count)),
    )
    second = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=FakeEmbeddingProvider(dim=8),
        model_name="fake",
        embedding_dim=8,
        batch_size=2,
        chunk_size=2,
    )

    assert first.embedded_count == 5
    assert progress == [("r1", 2), ("r1", 4), ("r1", 5)]
    assert second.embedded_count == 0
    assert second.error is None
    assert len(repository.upserted) == 5


async def test_backfill_stops_when_rows_are_relisted_after_upsert() -> None:
    repository = StuckRepository(missing=[passage("p1"), passage("p2")])

    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=FakeEmbeddingProvider(dim=8),
        model_name="fake",
        embedding_dim=8,
        batch_size=2,
        chunk_size=2,
    )

    assert result.embedded_count == 2
    assert result.error is not None
