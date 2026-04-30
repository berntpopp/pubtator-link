"""Background queue for review-scoped full-text preparation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from pubtator_link.config import ReviewReragConfig
from pubtator_link.repositories.review_rerag import ReviewReragRepository
from pubtator_link.services.full_text_preparation import FullTextPreparationService


class ReviewPreparationQueue:
    """Coordinate in-memory background preparation for review sources."""

    def __init__(
        self,
        config: ReviewReragConfig,
        repository: ReviewReragRepository,
        preparation: FullTextPreparationService,
        logger: Any | None = None,
    ) -> None:
        self.config = config
        self.repository = repository
        self.preparation = preparation
        self.logger = logger or logging.getLogger(__name__)
        self._queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue()
        self._queued: set[tuple[str, str]] = set()
        self._queued_lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        """Repair abandoned jobs and start background workers."""
        if self._workers:
            return

        await self.repair_startup_jobs()
        for index in range(self.config.prep_concurrency):
            self._workers.append(
                asyncio.create_task(
                    self._worker(),
                    name=f"review-preparation-worker-{index}",
                )
            )

    async def stop(self) -> None:
        """Cancel all background workers."""
        for worker in self._workers:
            worker.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def repair_startup_jobs(self) -> int:
        """Mark jobs left running by a previous process as failed."""
        return await self.repository.mark_running_jobs_failed_on_startup()

    async def enqueue_pmid(self, review_id: str, pmid: str) -> bool:
        """Queue preparation for a PubTator PMID source."""
        return await self._enqueue(
            review_id=review_id,
            source_id=f"PMID:{pmid}",
            source_kind="pubtator_full_bioc",
            source_value=pmid,
        )

    async def enqueue_curated_url(self, review_id: str, url: str) -> bool:
        """Queue preparation for a curated PDF URL source."""
        return await self._enqueue(
            review_id=review_id,
            source_id=f"URL:{url}",
            source_kind="curated_pdf",
            source_value=url,
        )

    async def _enqueue(
        self,
        *,
        review_id: str,
        source_id: str,
        source_kind: str,
        source_value: str,
    ) -> bool:
        key = (review_id, source_id)
        async with self._queued_lock:
            if key in self._queued:
                return False
            self._queued.add(key)

        try:
            await self.repository.enqueue_preparation_job(review_id, source_id, source_kind)
            await self._queue.put((review_id, source_id, source_kind, source_value))
            return True
        except Exception:
            async with self._queued_lock:
                self._queued.discard(key)
            raise

    async def _worker(self) -> None:
        while True:
            review_id, source_id, source_kind, source_value = await self._queue.get()
            try:
                await self.repository.mark_job_running(review_id=review_id, source_id=source_id)

                async def run_preparation(
                    review_id: str = review_id,
                    source_id: str = source_id,
                    source_kind: str = source_kind,
                    source_value: str = source_value,
                ) -> str:
                    if source_kind == "pubtator_full_bioc":
                        return await asyncio.wait_for(
                            self.preparation.prepare_pmid(review_id, source_value),
                            timeout=self.config.document_timeout_seconds,
                        )
                    if source_kind == "curated_pdf":
                        return await asyncio.wait_for(
                            self.preparation.prepare_curated_url(review_id, source_value),
                            timeout=self.config.document_timeout_seconds,
                        )
                    self.logger.warning(
                        "Unknown review preparation source kind",
                        extra={
                            "review_id": review_id,
                            "source_id": source_id,
                            "source_kind": source_kind,
                        },
                    )
                    return "failed"

                result = await self.repository.with_preparation_lock(
                    review_id=review_id,
                    source_id=source_id,
                    callback=run_preparation,
                )
                await self.repository.mark_job_finished(
                    review_id=review_id,
                    source_id=source_id,
                    status=result,
                    error=None,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.exception(
                    "Review preparation job failed",
                    extra={
                        "review_id": review_id,
                        "source_id": source_id,
                        "source_kind": source_kind,
                    },
                )
                await self.repository.mark_job_finished(
                    review_id=review_id,
                    source_id=source_id,
                    status="failed",
                    error=str(exc)[:500],
                )
            finally:
                async with self._queued_lock:
                    self._queued.discard((review_id, source_id))
                self._queue.task_done()
