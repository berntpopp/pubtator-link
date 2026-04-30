import asyncio
from typing import Any

import pytest

from pubtator_link.config import ReviewReragConfig
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue


def _config() -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=60,
        source_timeout_seconds=5,
        pdf_max_bytes=64,
        text_max_bytes=64,
        allow_http_urls=False,
        enable_docling=False,
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, str, str]] = []
        self.repaired_jobs = 0
        self.repair_calls = 0

    async def enqueue_preparation_job(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
    ) -> dict[str, Any]:
        self.enqueued.append((review_id, source_id, source_kind))
        return {"review_id": review_id}

    async def mark_running_jobs_failed_on_startup(self) -> int:
        self.repair_calls += 1
        return self.repaired_jobs


class SlowRecordingRepository(RecordingRepository):
    async def enqueue_preparation_job(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
    ) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        return await super().enqueue_preparation_job(review_id, source_id, source_kind)


class FailingOnceRepository(RecordingRepository):
    def __init__(self) -> None:
        super().__init__()
        self.enqueue_calls = 0

    async def enqueue_preparation_job(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
    ) -> dict[str, Any]:
        self.enqueue_calls += 1
        if self.enqueue_calls == 1:
            raise RuntimeError("temporary repository failure")
        return await super().enqueue_preparation_job(review_id, source_id, source_kind)


class RecordingPreparation:
    async def prepare_pmid(self, review_id: str, pmid: str) -> str:
        return "complete"

    async def prepare_curated_url(self, review_id: str, url: str) -> str:
        return "complete"


@pytest.mark.asyncio
async def test_enqueue_pmid_deduplicates_same_review_source_in_memory() -> None:
    repository = RecordingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    first = await queue.enqueue_pmid("review-1", "40234174")
    second = await queue.enqueue_pmid("review-1", "40234174")
    other_review = await queue.enqueue_pmid("review-2", "40234174")

    assert first is True
    assert second is False
    assert other_review is True
    assert repository.enqueued == [
        ("review-1", "PMID:40234174", "pubtator_full_bioc"),
        ("review-2", "PMID:40234174", "pubtator_full_bioc"),
    ]


@pytest.mark.asyncio
async def test_enqueue_pmid_deduplicates_concurrent_same_review_source() -> None:
    repository = SlowRecordingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    results = await asyncio.gather(
        queue.enqueue_pmid("review-1", "40234174"),
        queue.enqueue_pmid("review-1", "40234174"),
    )

    assert sorted(results) == [False, True]
    assert repository.enqueued == [("review-1", "PMID:40234174", "pubtator_full_bioc")]


@pytest.mark.asyncio
async def test_enqueue_allows_retry_after_repository_failure() -> None:
    repository = FailingOnceRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    with pytest.raises(RuntimeError, match="temporary repository failure"):
        await queue.enqueue_pmid("review-1", "40234174")

    retried = await queue.enqueue_pmid("review-1", "40234174")

    assert retried is True
    assert repository.enqueued == [("review-1", "PMID:40234174", "pubtator_full_bioc")]


@pytest.mark.asyncio
async def test_enqueue_curated_url_uses_url_source_id_and_repository_job() -> None:
    repository = RecordingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    queued = await queue.enqueue_curated_url("review-1", "https://example.test/paper.pdf")

    assert queued is True
    assert repository.enqueued == [
        ("review-1", "URL:https://example.test/paper.pdf", "curated_pdf")
    ]


@pytest.mark.asyncio
async def test_repair_startup_jobs_returns_repository_result() -> None:
    repository = RecordingRepository()
    repository.repaired_jobs = 3
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    repaired_jobs = await queue.repair_startup_jobs()

    assert repaired_jobs == 3


@pytest.mark.asyncio
async def test_start_repairs_startup_jobs_only_before_workers_are_started() -> None:
    repository = RecordingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    await queue.start()
    await queue.start()
    await queue.stop()

    assert repository.repair_calls == 1
