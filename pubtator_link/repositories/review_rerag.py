"""PostgreSQL repository for review-scoped re-RAG data."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol
from uuid import uuid4

from pubtator_link.models.review_rerag import PreparationStatus, ReviewPassageRow


class ReviewReragRepository(Protocol):
    """Persistence contract for review-scoped preparation and retrieval."""

    async def enqueue_preparation_job(
        self, review_id: str, source_id: str, source_kind: str
    ) -> PreparationStatus:
        """Create or deduplicate a preparation job and return aggregate status."""

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        url: str | None = None,
        reason: str | None = None,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> None:
        """Record one full-text retrieval attempt for audit/debugging."""

    async def mark_running_jobs_failed_on_startup(self) -> int:
        """Mark orphaned running jobs as failed and return the affected count."""

    async def preparation_status(self, review_id: str) -> PreparationStatus:
        """Return aggregate preparation status counts for a review."""

    async def upsert_passages(self, passages: Sequence[ReviewPassageRow]) -> None:
        """Insert or replace prepared review passages."""

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        """Search prepared passages for a review."""

    async def mark_job_running(self, *, review_id: str, source_id: str) -> None:
        """Mark a preparation job as running."""

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        """Mark a preparation job as finished."""

    async def with_preparation_lock(
        self,
        *,
        review_id: str,
        source_id: str,
        callback: Callable[[], Awaitable[str]],
    ) -> str:
        """Run a callback inside a transaction-scoped preparation advisory lock."""


class PostgresReviewReragRepository:
    """asyncpg-backed repository for review-scoped re-RAG persistence."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def enqueue_preparation_job(
        self, review_id: str, source_id: str, source_kind: str
    ) -> PreparationStatus:
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do nothing
                """,
                review_id,
            )
            await connection.execute(
                """
                insert into review_preparation_jobs (
                    job_id,
                    review_id,
                    source_id,
                    source_kind,
                    status
                )
                values ($1, $2, $3, $4, 'queued')
                on conflict (review_id, source_id) do update
                set source_kind = excluded.source_kind
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
            )
            return await self._preparation_status_on_connection(connection, review_id)

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        url: str | None = None,
        reason: str | None = None,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                insert into full_text_retrieval_attempts (
                    attempt_id,
                    review_id,
                    source_id,
                    source_kind,
                    status,
                    url,
                    reason,
                    content_type,
                    content_length
                )
                values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
                status,
                url,
                reason,
                content_type,
                content_length,
            )

    async def mark_running_jobs_failed_on_startup(self) -> int:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                """
                update review_preparation_jobs
                set status = 'failed',
                    finished_at = now(),
                    error = 'Marked failed during service startup'
                where status = 'running'
                """
            )
        return _parse_execute_count(result)

    async def preparation_status(self, review_id: str) -> PreparationStatus:
        async with self._pool.acquire() as connection:
            return await self._preparation_status_on_connection(connection, review_id)

    async def mark_job_running(self, *, review_id: str, source_id: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                update review_preparation_jobs
                set status = 'running',
                    started_at = now(),
                    error = null
                where review_id = $1 and source_id = $2
                """,
                review_id,
                source_id,
            )

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                update review_preparation_jobs
                set status = $3,
                    finished_at = now(),
                    error = $4
                where review_id = $1 and source_id = $2
                """,
                review_id,
                source_id,
                status,
                error,
            )

    async def with_preparation_lock(
        self,
        *,
        review_id: str,
        source_id: str,
        callback: Callable[[], Awaitable[str]],
    ) -> str:
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "select pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"{review_id}:{source_id}",
            )
            return await callback()

    async def upsert_passages(self, passages: Sequence[ReviewPassageRow]) -> None:
        if not passages:
            return

        args = [
            (
                passage.passage_id,
                passage.review_id,
                passage.source_id,
                passage.source_kind,
                passage.pmid,
                passage.pmcid,
                passage.doi,
                passage.url,
                passage.section,
                passage.heading_path,
                passage.page,
                passage.text,
                passage.entity_ids,
                passage.relation_types,
                passage.screening_status,
                json.dumps(passage.source_metadata, sort_keys=True),
            )
            for passage in passages
        ]
        async with self._pool.acquire() as connection:
            await connection.executemany(
                """
                insert into review_passages (
                    passage_id,
                    review_id,
                    source_id,
                    source_kind,
                    pmid,
                    pmcid,
                    doi,
                    url,
                    section,
                    heading_path,
                    page,
                    text,
                    entity_ids,
                    relation_types,
                    screening_status,
                    source_metadata
                )
                values (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14, $15, $16::jsonb
                )
                on conflict (review_id, passage_id) do update
                set source_id = excluded.source_id,
                    source_kind = excluded.source_kind,
                    pmid = excluded.pmid,
                    pmcid = excluded.pmcid,
                    doi = excluded.doi,
                    url = excluded.url,
                    section = excluded.section,
                    heading_path = excluded.heading_path,
                    page = excluded.page,
                    text = excluded.text,
                    entity_ids = excluded.entity_ids,
                    relation_types = excluded.relation_types,
                    screening_status = excluded.screening_status,
                    source_metadata = excluded.source_metadata
                """,
                args,
            )

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        entity_filter = _filter_or_none(entity_ids)
        pmid_filter = _filter_or_none(pmids)
        section_filter = _filter_or_none(sections)
        recall_query = _recall_tsquery(query)
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                with query as (
                    select
                        websearch_to_tsquery('english', $2) as strict_query,
                        to_tsquery('english', $7) as recall_query
                )
                select
                    passage_id,
                    review_id,
                    source_id,
                    source_kind,
                    pmid,
                    pmcid,
                    doi,
                    url,
                    section,
                    heading_path,
                    page,
                    text,
                    entity_ids,
                    relation_types,
                    screening_status,
                    source_metadata,
                    (
                        ts_rank_cd(search_vector, query.strict_query) * 2.0
                        + ts_rank_cd(search_vector, query.recall_query)
                    ) as lexical_rank
                from review_passages, query
                where review_id = $1
                  and (search_vector @@ query.strict_query or search_vector @@ query.recall_query)
                  and ($3::text[] is null or entity_ids && $3::text[])
                  and ($4::text[] is null or pmid = any($4::text[]))
                  and ($5::text[] is null or section = any($5::text[]))
                order by lexical_rank desc, passage_id asc
                limit $6
                """,
                review_id,
                query,
                entity_filter,
                pmid_filter,
                section_filter,
                limit,
                recall_query,
            )
        return [_passage_from_row(row) for row in rows]

    async def _preparation_status_on_connection(
        self, connection: Any, review_id: str
    ) -> PreparationStatus:
        row = await connection.fetchrow(
            """
            select
                coalesce(sum((status = 'queued')::int), 0)::int as queued,
                coalesce(sum((status = 'running')::int), 0)::int as running,
                coalesce(sum((status = 'complete')::int), 0)::int as complete,
                coalesce(sum((status = 'partial')::int), 0)::int as partial,
                coalesce(sum((status = 'failed')::int), 0)::int as failed
            from review_preparation_jobs
            where review_id = $1
            """,
            review_id,
        )
        return _preparation_status_from_row(row)


def _filter_or_none(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    return list(values)


def _preparation_status_from_row(row: Mapping[str, Any] | None) -> PreparationStatus:
    if row is None:
        return PreparationStatus()
    return PreparationStatus(
        queued=int(row["queued"] or 0),
        running=int(row["running"] or 0),
        complete=int(row["complete"] or 0),
        partial=int(row["partial"] or 0),
        failed=int(row["failed"] or 0),
    )


def _passage_from_row(row: Mapping[str, Any]) -> ReviewPassageRow:
    source_metadata = row["source_metadata"]
    if isinstance(source_metadata, str):
        source_metadata = json.loads(source_metadata)
    return ReviewPassageRow(
        passage_id=row["passage_id"],
        review_id=row["review_id"],
        source_id=row["source_id"],
        source_kind=row["source_kind"],
        pmid=row["pmid"],
        pmcid=row["pmcid"],
        doi=row["doi"],
        url=row["url"],
        section=row["section"],
        heading_path=row["heading_path"],
        page=row["page"],
        text=row["text"],
        entity_ids=list(row["entity_ids"] or []),
        relation_types=list(row["relation_types"] or []),
        screening_status=row["screening_status"],
        source_metadata=source_metadata,
        lexical_rank=float(row["lexical_rank"] or 0.0),
    )


def _parse_execute_count(result: str) -> int:
    match = re.search(r"(\d+)$", result)
    if match is None:
        return 0
    return int(match.group(1))


def _recall_tsquery(query: str) -> str:
    tokens = []
    seen: set[str] = set()
    for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 12:
            break
    return " | ".join(tokens) or "review"
