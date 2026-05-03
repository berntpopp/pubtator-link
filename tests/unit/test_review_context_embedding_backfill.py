from __future__ import annotations

from typing import Any

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
        return self.missing

    async def upsert_passage_embeddings(
        self, records: list[ReviewPassageEmbeddingRecord]
    ) -> None:
        self.upserted.extend(records)


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


async def test_backfill_embeds_missing_passages_in_batches() -> None:
    repository = FakeEmbeddingBackfillRepository(missing=[passage("p1")])
    provider = FakeEmbeddingProvider(dim=384)

    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        limit=100,
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


async def test_backfill_reports_provider_failure_without_raising() -> None:
    repository = FakeEmbeddingBackfillRepository(missing=[passage("p1")])
    provider = FailingEmbeddingProvider()

    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        limit=100,
    )

    assert result.embedded_count == 0
    assert result.failed_count == 1
    assert result.error is not None
    assert repository.upserted == []
