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


def _timeout_config() -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=1,
        document_timeout_seconds=1,
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
        self.next_enqueue_result = "newly_queued"

    async def enqueue_preparation_job(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
    ) -> str:
        self.enqueued.append((review_id, source_id, source_kind))
        return self.next_enqueue_result

    async def mark_running_jobs_failed_on_startup(self) -> int:
        self.repair_calls += 1
        return self.repaired_jobs


class SlowRecordingRepository(RecordingRepository):
    async def enqueue_preparation_job(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
    ) -> str:
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
    ) -> str:
        self.enqueue_calls += 1
        if self.enqueue_calls == 1:
            raise RuntimeError("temporary repository failure")
        return await super().enqueue_preparation_job(review_id, source_id, source_kind)


class RecordingPreparation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def prepare_pmid(self, review_id: str, pmid: str) -> str:
        self.calls.append(("pmid", review_id, pmid))
        return "complete"

    async def prepare_curated_url(self, review_id: str, url: str) -> str:
        self.calls.append(("url", review_id, url))
        return "complete"


class WorkerRepository(RecordingRepository):
    def __init__(self) -> None:
        super().__init__()
        self.claim_results: list[bool] = [True]
        self.claims: list[tuple[str, str]] = []
        self.finished: list[tuple[str, str, str, str | None]] = []
        self.attempts: list[tuple[str, str, str, str, str | None]] = []

    async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
        self.claims.append((review_id, source_id))
        if self.claim_results:
            return self.claim_results.pop(0)
        return True

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        self.finished.append((review_id, source_id, status, error))

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        reason: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.attempts.append((review_id, source_id, source_kind, status, reason))


class SlowPreparation:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def prepare_pmid(self, review_id: str, pmid: str) -> str:
        self.calls.append(("pmid", review_id, pmid))
        await asyncio.sleep(2)
        return "complete"

    async def prepare_curated_url(self, review_id: str, url: str) -> str:
        self.calls.append(("url", review_id, url))
        await asyncio.sleep(2)
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

    assert first == "newly_queued"
    assert second == "already_queued"
    assert other_review == "newly_queued"
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

    assert sorted(results) == ["already_queued", "newly_queued"]
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

    assert retried == "newly_queued"
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

    assert queued == "newly_queued"
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


@pytest.mark.asyncio
async def test_worker_records_actionable_error_on_timeout() -> None:
    repository = WorkerRepository()
    preparation = SlowPreparation()
    queue = ReviewPreparationQueue(
        config=_timeout_config(),
        repository=repository,
        preparation=preparation,
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "40234174") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert repository.claims == [("review-1", "PMID:40234174")]
    assert preparation.calls == [("pmid", "review-1", "40234174")]
    assert repository.finished == [
        (
            "review-1",
            "PMID:40234174",
            "failed",
            "Preparation timed out after 1 seconds",
        )
    ]
    assert repository.attempts == [
        (
            "review-1",
            "PMID:40234174",
            "pubtator_full_bioc",
            "failed",
            "Preparation timed out after 1 seconds",
        )
    ]


@pytest.mark.asyncio
async def test_enqueue_pmid_returns_already_indexed_without_queueing() -> None:
    repository = RecordingRepository()
    repository.next_enqueue_result = "already_indexed"
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=RecordingPreparation(),
    )

    result = await queue.enqueue_pmid("review-1", "40234174")

    assert result == "already_indexed"
    assert queue._queue.empty()


@pytest.mark.asyncio
async def test_worker_skips_preparation_when_claim_returns_false() -> None:
    repository = WorkerRepository()
    repository.claim_results = [False]
    preparation = RecordingPreparation()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=preparation,
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "40234174") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert repository.claims == [("review-1", "PMID:40234174")]
    assert preparation.calls == []
    assert repository.finished == []
    assert repository.attempts == []


@pytest.mark.asyncio
async def test_worker_starts_preparation_after_claim_completes() -> None:
    events: list[str] = []

    class ClaimTrackingRepository(WorkerRepository):
        transaction_open = False

        async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
            events.append("claim_begin")
            self.transaction_open = True
            await asyncio.sleep(0)
            self.transaction_open = False
            events.append("claim_committed")
            return True

    class AssertingPreparation(RecordingPreparation):
        async def prepare_pmid(self, review_id: str, pmid: str) -> str:
            assert repository.transaction_open is False
            events.append("prepare_started")
            return "complete"

    repository = ClaimTrackingRepository()
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=AssertingPreparation(),
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "40234174") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert events == ["claim_begin", "claim_committed", "prepare_started"]
    assert repository.finished == [("review-1", "PMID:40234174", "complete", None)]


@pytest.mark.asyncio
async def test_two_slow_preparation_jobs_run_concurrently_with_two_workers() -> None:
    started: list[str] = []
    release = asyncio.Event()

    class BlockingPreparation(RecordingPreparation):
        async def prepare_pmid(self, review_id: str, pmid: str) -> str:
            started.append(pmid)
            if len(started) == 2:
                release.set()
            await asyncio.wait_for(release.wait(), timeout=2)
            return "complete"

    repository = WorkerRepository()
    repository.claim_results = [True, True]
    queue = ReviewPreparationQueue(
        config=_config(),
        repository=repository,
        preparation=BlockingPreparation(),
    )

    await queue.start()
    try:
        assert await queue.enqueue_pmid("review-1", "111") == "newly_queued"
        assert await queue.enqueue_pmid("review-1", "222") == "newly_queued"
        await asyncio.wait_for(queue._queue.join(), timeout=2)
    finally:
        await queue.stop()

    assert set(started) == {"111", "222"}
    assert sorted(repository.finished) == [
        ("review-1", "PMID:111", "complete", None),
        ("review-1", "PMID:222", "complete", None),
    ]
