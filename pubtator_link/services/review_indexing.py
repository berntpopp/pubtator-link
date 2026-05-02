"""Shared orchestration for review evidence indexing requests."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Protocol

from pubtator_link.models.review_rerag import (
    IndexReviewEvidenceRequest,
    IndexReviewEvidenceResponse,
    PreparationEnqueueResult,
    PreparationStatus,
)
from pubtator_link.services.review_state import index_snapshot_date, retry_after_ms_for_status

NBK_RE = re.compile(r"\bNBK\d+\b", re.IGNORECASE)


class ReviewIndexingRepository(Protocol):
    async def research_session_exists(self, review_id: str, session_id: str) -> bool: ...

    async def preparation_job_statuses(
        self, review_id: str, source_ids: list[str]
    ) -> dict[str, str]: ...

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus: ...

    async def link_review_session_source(
        self, review_id: str, session_id: str, source_id: str
    ) -> None: ...


class ReviewIndexingQueue(Protocol):
    async def enqueue_pmid(self, review_id: str, pmid: str) -> PreparationEnqueueResult: ...

    async def enqueue_curated_url(self, review_id: str, url: str) -> PreparationEnqueueResult: ...


class ReviewIndexingService:
    """Plan, enqueue, link, and optionally wait for review evidence indexing."""

    def __init__(
        self,
        *,
        repository: ReviewIndexingRepository,
        queue: ReviewIndexingQueue,
        poll_interval_ms: int = 250,
    ) -> None:
        self.repository = repository
        self.queue = queue
        self.poll_interval_ms = poll_interval_ms

    async def index_review_evidence(
        self,
        review_id: str,
        request: IndexReviewEvidenceRequest,
    ) -> IndexReviewEvidenceResponse:
        bookshelf_urls = _bookshelf_urls(request.curated_urls)
        if bookshelf_urls:
            nbk_ids = _nbk_ids(bookshelf_urls)
            if nbk_ids:
                raise ValueError(
                    "bookshelf_url_not_indexable: "
                    f"{', '.join(nbk_ids)}; "
                    "call pubtator.lookup_citation with the NBK ID and index the returned PMID"
                )
            raise ValueError(
                "bookshelf_url_not_indexable: "
                "call pubtator.lookup_citation with the Bookshelf citation or NBK ID and "
                "index the returned PMID"
            )

        if request.session_id is not None:
            exists = await self.repository.research_session_exists(review_id, request.session_id)
            if not exists:
                raise ValueError("session_not_found")

        sources = _source_specs(request)
        source_ids = [source_id for source_id, _, _ in sources]
        source_preflight_summary, source_preflight_warnings = await _source_preflight_summary(
            self.repository, review_id, source_ids
        )
        source_preflight_message = _source_preflight_message(source_preflight_summary)
        statuses = await self.repository.preparation_job_statuses(review_id, source_ids)
        counters = _counters_from_statuses(statuses) if request.dry_run else _empty_counters()

        if not request.dry_run:
            for source_id, source_type, value in sources:
                result = await self._enqueue(review_id, source_type, value)
                _increment_counter(counters, result)
                if request.session_id is not None:
                    await self.repository.link_review_session_source(
                        review_id, request.session_id, source_id
                    )

        status = await self.repository.preparation_status(review_id, session_id=request.session_id)
        waited_ms = 0
        timed_out = False
        wait_for_status = request.wait_for_status
        if wait_for_status is None and request.wait_for_completion:
            wait_for_status = "complete_or_partial"

        if wait_for_status is not None and request.timeout_ms > 0:
            started = time.monotonic()
            while not _status_satisfies(status, wait_for_status):
                waited_ms = int((time.monotonic() - started) * 1000)
                if waited_ms >= request.timeout_ms:
                    timed_out = True
                    break
                await asyncio.sleep(min(self.poll_interval_ms, request.timeout_ms) / 1000)
                status = await self.repository.preparation_status(
                    review_id, session_id=request.session_id
                )
            waited_ms = int((time.monotonic() - started) * 1000)

        queued = counters["newly_queued"] + counters["previously_failed_requeued"]
        already_prepared = counters["already_indexed"]
        return IndexReviewEvidenceResponse(
            review_id=review_id,
            queued=queued,
            already_prepared=already_prepared,
            preparation_status=status,
            retry_after_ms=1000 if timed_out else retry_after_ms_for_status(status),
            index_snapshot_date=index_snapshot_date(),
            dry_run=request.dry_run,
            waited_ms=waited_ms,
            timed_out=timed_out,
            estimated_queue_position=max(0, status.queued - queued),
            estimated_source_count=len(sources),
            already_indexed=counters["already_indexed"],
            already_queued=counters["already_queued"],
            already_running=counters["already_running"],
            newly_queued=counters["newly_queued"],
            previously_failed_requeued=counters["previously_failed_requeued"],
            source_preflight_summary=source_preflight_summary,
            source_preflight_message=source_preflight_message,
            source_preflight_warnings=source_preflight_warnings,
            lifecycle_note=(
                "Repeated calls with the same review_id and already indexed sources are no-ops. "
                "Call inspect_review_index before retrieval to verify source coverage."
            ),
        )

    async def _enqueue(
        self, review_id: str, source_type: str, value: str
    ) -> PreparationEnqueueResult:
        if source_type == "pmid":
            return await self.queue.enqueue_pmid(review_id, value)
        return await self.queue.enqueue_curated_url(review_id, value)


def _source_specs(request: IndexReviewEvidenceRequest) -> list[tuple[str, str, str]]:
    return [
        *[(f"PMID:{pmid}", "pmid", pmid) for pmid in request.pmids],
        *[(f"URL:{url}", "url", url) for url in request.curated_urls],
    ]


def _bookshelf_urls(urls: list[str]) -> list[str]:
    return [url for url in urls if "ncbi.nlm.nih.gov/books/" in url.lower()]


def _nbk_ids(values: list[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        ids.extend(match.group(0).upper() for match in NBK_RE.finditer(value))
    return list(dict.fromkeys(ids))


async def _source_preflight_summary(
    repository: ReviewIndexingRepository,
    review_id: str,
    source_ids: list[str],
) -> tuple[dict[str, int], list[str]]:
    coverage_summary_fn = getattr(repository, "source_coverage_summary", None)
    if coverage_summary_fn is None:
        return {}, []

    try:
        summary: Any = await coverage_summary_fn(review_id, source_ids)
        if not isinstance(summary, dict):
            raise ValueError("source coverage summary must be a dict")

        total_sources = int(summary.get("total_sources", len(source_ids)))
        return (
            {
                "total_sources": total_sources,
                "full_text": int(summary.get("full_text", 0)),
                "abstract_only": int(summary.get("abstract_only", 0)),
                "title_only": int(summary.get("title_only", 0)),
                "failed": int(summary.get("failed", 0)),
            },
            [],
        )
    except Exception:
        return {}, ["source_coverage_summary_unavailable"]


def _source_preflight_message(summary: dict[str, int]) -> str | None:
    if not summary:
        return None

    total_sources = summary["total_sources"]
    return (
        f"{summary['full_text']}/{total_sources} sources full_text, "
        f"{summary['abstract_only']}/{total_sources} abstract_only, "
        f"{summary['title_only']}/{total_sources} title_only, "
        f"{summary['failed']}/{total_sources} failed."
    )


def _counters_from_statuses(statuses: dict[str, str]) -> dict[str, int]:
    counters = _empty_counters()
    for status in statuses.values():
        if status in {"complete", "partial"}:
            counters["already_indexed"] += 1
        elif status == "queued":
            counters["already_queued"] += 1
        elif status == "running":
            counters["already_running"] += 1
        elif status == "failed":
            counters["previously_failed_requeued"] += 1
    return counters


def _empty_counters() -> dict[str, int]:
    return {
        "already_indexed": 0,
        "already_queued": 0,
        "already_running": 0,
        "newly_queued": 0,
        "previously_failed_requeued": 0,
    }


def _increment_counter(counters: dict[str, int], result: PreparationEnqueueResult) -> None:
    if result == "newly_queued":
        counters["newly_queued"] += 1
    elif result == "previously_failed_requeued":
        counters["previously_failed_requeued"] += 1
    elif result == "already_indexed":
        counters["already_indexed"] += 1
    elif result == "already_running":
        counters["already_running"] += 1
    else:
        counters["already_queued"] += 1


def _status_satisfies(
    status: PreparationStatus,
    wait_for_status: str,
) -> bool:
    if wait_for_status == "complete":
        return (
            status.complete > 0
            and status.queued == 0
            and status.running == 0
            and status.partial == 0
            and status.failed == 0
        )
    if wait_for_status == "complete_or_partial":
        return status.queued == 0 and status.running == 0 and (status.complete + status.partial) > 0
    return status.queued == 0 and status.running == 0
