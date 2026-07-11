from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.repositories.review_rerag import ReviewPassageEmbeddingRecord
from pubtator_link.services.review_context.embeddings import (
    EmbeddingProvider,
    text_hash,
)

logger = logging.getLogger(__name__)


class EmbeddingBackfillRepository(Protocol):
    async def list_passages_missing_embeddings(
        self,
        review_id: str,
        *,
        model_name: str,
        limit: int,
    ) -> list[ReviewPassageRow]: ...

    async def upsert_passage_embeddings(
        self, records: Sequence[ReviewPassageEmbeddingRecord]
    ) -> None: ...


@dataclass(frozen=True)
class EmbeddingBackfillResult:
    review_id: str
    embedded_count: int
    failed_count: int
    error: str | None = None


async def backfill_review_passage_embeddings(
    *,
    repository: EmbeddingBackfillRepository,
    review_id: str,
    provider: EmbeddingProvider,
    model_name: str,
    embedding_dim: int,
    batch_size: int,
    limit: int,
) -> EmbeddingBackfillResult:
    started = time.monotonic()
    passages = await repository.list_passages_missing_embeddings(
        review_id,
        model_name=model_name,
        limit=limit,
    )
    embedded_count = 0
    failed_count = 0
    for offset in range(0, len(passages), batch_size):
        batch = passages[offset : offset + batch_size]
        try:
            vectors = await provider.embed_passages([passage.text for passage in batch])
        except Exception as exc:
            failed_count += len(batch)
            logger.warning(
                "review_embedding_backfill_failed",
                extra={
                    "review_id": review_id,
                    "model_name": model_name,
                    "embedding_dim": embedding_dim,
                    "missing_count": len(passages),
                    "embedded_count": embedded_count,
                    "failed_count": failed_count,
                    "batch_size": len(batch),
                    "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                    "error_type": type(exc).__name__,
                },
            )
            # Fixed classification only -- never serialize the exception prose.
            return EmbeddingBackfillResult(
                review_id=review_id,
                embedded_count=embedded_count,
                failed_count=failed_count,
                error="Embedding backfill failed.",
            )

        records = [
            ReviewPassageEmbeddingRecord(
                review_id=passage.review_id,
                passage_id=passage.passage_id,
                model_name=model_name,
                embedding_dim=embedding_dim,
                text_hash=text_hash(passage.text),
                embedding=vector,
            )
            for passage, vector in zip(batch, vectors, strict=True)
        ]
        await repository.upsert_passage_embeddings(records)
        embedded_count += len(records)

    logger.info(
        "review_embedding_backfill_completed",
        extra={
            "review_id": review_id,
            "model_name": model_name,
            "embedding_dim": embedding_dim,
            "missing_count": len(passages),
            "embedded_count": embedded_count,
            "failed_count": failed_count,
            "batch_size": batch_size,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
        },
    )
    return EmbeddingBackfillResult(
        review_id=review_id,
        embedded_count=embedded_count,
        failed_count=failed_count,
    )
