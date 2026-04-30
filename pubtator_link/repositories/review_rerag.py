"""PostgreSQL repository for review-scoped re-RAG data."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol
from uuid import uuid4

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    PreparationStatus,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
)
from pubtator_link.repositories.review_rerag_mappers import (
    _failed_source_summary_from_row,
    _filter_or_none,
    _parse_execute_count,
    _passage_from_row,
    _passage_sample_from_row,
    _preparation_status_from_row,
    _recall_tsquery,
    _review_index_totals_from_row,
    _source_summary_from_row,
)


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

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> list[ReviewSourceSummary]:
        """List review source summaries, optionally with passage samples."""

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
        """List failed review sources with audit reasons."""

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        """Return aggregate index counts for a review."""

    async def available_sections(self, review_id: str) -> list[str]:
        """Return distinct indexed sections for retrieval diagnostics."""

    async def indexed_pmids(self, review_id: str) -> list[str]:
        """Return distinct indexed PMIDs for retrieval diagnostics."""

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

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
    ) -> list[ReviewSourceSummary]:
        pmid_filter = _filter_or_none(pmids)
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                with source_scope as (
                    select
                        j.review_id,
                        j.source_id,
                        j.source_kind,
                        j.status as job_status,
                        j.error,
                        coalesce(
                            min(p.pmid) filter (where p.pmid is not null),
                            case
                                when j.source_id ~ '^[0-9]+$' then j.source_id
                                when j.source_id ~ '^PMID:(.+)$'
                                    then substring(j.source_id from '^PMID:(.+)$')
                            end
                        ) as pmid
                    from review_preparation_jobs j
                    left join review_passages p
                        on p.review_id = j.review_id
                       and p.source_id = j.source_id
                    where j.review_id = $1
                    group by j.review_id, j.source_id, j.source_kind, j.status, j.error
                ),
                attempt_stats as (
                    select
                        review_id,
                        case
                            when source_id ~ '^https?://' then 'URL:' || source_id
                            else source_id
                        end as source_id,
                        array_agg(distinct status order by status)
                            filter (where status is not null) as attempt_statuses
                    from full_text_retrieval_attempts
                    where review_id = $1
                    group by review_id, source_id
                ),
                passage_stats as (
                    select
                        review_id,
                        source_id,
                        array_agg(distinct section order by section)
                            filter (where section is not null) as sections,
                        count(distinct passage_id)::int as passage_count,
                        coalesce(sum(length(text)), 0)::int as char_count
                    from review_passages
                    where review_id = $1
                    group by review_id, source_id
                )
                select
                    s.source_id,
                    s.pmid,
                    s.source_kind,
                    s.job_status,
                    s.error,
                    coalesce(a.attempt_statuses, '{}') as attempt_statuses,
                    coalesce(p.sections, '{}') as sections,
                    coalesce(p.passage_count, 0)::int as passage_count,
                    coalesce(p.char_count, 0)::int as char_count
                from source_scope s
                left join attempt_stats a
                    on a.review_id = s.review_id
                   and a.source_id = s.source_id
                left join passage_stats p
                    on p.review_id = s.review_id
                   and p.source_id = s.source_id
                where $2::text[] is null or s.pmid = any($2::text[])
                order by s.source_id
                """,
                review_id,
                pmid_filter,
            )
            sources = [_source_summary_from_row(row) for row in rows]
            if include_passage_samples and sources:
                source_ids = [source.source_id for source in sources]
                sample_rows = await connection.fetch(
                    """
                    with ranked as (
                        select
                            source_id,
                            passage_id,
                            section,
                            text,
                            length(text)::int as char_count,
                            row_number() over (
                                partition by coalesce(pmid, source_id)
                                order by section, passage_id
                            ) as sample_rank
                        from review_passages
                        where review_id = $1
                          and ($2::text[] is null or pmid = any($2::text[]))
                          and source_id = any($3::text[])
                    )
                    select source_id, passage_id, section, text, char_count
                    from ranked
                    where sample_rank <= $4
                    order by source_id, sample_rank
                    """,
                    review_id,
                    pmid_filter,
                    source_ids,
                    sample_per_pmid,
                )
                samples_by_source: dict[str, list[ReviewPassageSample]] = {}
                for row in sample_rows:
                    samples_by_source.setdefault(row["source_id"], []).append(
                        _passage_sample_from_row(row)
                    )
                sources = [
                    source.model_copy(
                        update={"sample_passages": samples_by_source.get(source.source_id, [])}
                    )
                    for source in sources
                ]
        return sources

    async def list_review_failed_sources(self, review_id: str) -> list[FailedSourceSummary]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                with source_scope as (
                    select
                        j.review_id,
                        j.source_id,
                        j.source_kind,
                        j.status as job_status,
                        j.error,
                        coalesce(
                            min(p.pmid) filter (where p.pmid is not null),
                            case
                                when j.source_id ~ '^[0-9]+$' then j.source_id
                                when j.source_id ~ '^PMID:(.+)$'
                                    then substring(j.source_id from '^PMID:(.+)$')
                            end
                        ) as pmid
                    from review_preparation_jobs j
                    left join review_passages p
                        on p.review_id = j.review_id
                       and p.source_id = j.source_id
                    where j.review_id = $1
                    group by j.review_id, j.source_id, j.source_kind, j.status, j.error
                )
                select
                    s.source_id,
                    s.pmid,
                    s.source_kind,
                    s.job_status,
                    coalesce(
                        s.error,
                        string_agg(distinct a.reason, '; ')
                            filter (where a.reason is not null)
                    ) as error,
                    coalesce(
                        array_agg(distinct a.status order by a.status)
                            filter (where a.status is not null),
                        '{}'
                    ) as attempt_statuses
                from source_scope s
                left join full_text_retrieval_attempts a
                    on a.review_id = s.review_id
                   and (
                        a.source_id = s.source_id
                        or a.source_id = substring(s.source_id from '^URL:(.+)$')
                   )
                group by s.source_id, s.pmid, s.source_kind, s.job_status, s.error
                having s.job_status = 'failed'
                    or bool_or(a.status is not null and a.status <> 'success')
                order by s.source_id
                """,
                review_id,
            )
        return [_failed_source_summary_from_row(row) for row in rows]

    async def review_index_totals(self, review_id: str) -> ReviewIndexTotals:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                with indexed as (
                    select
                        (count(distinct p.pmid) filter (where p.pmid is not null))::int
                            as pmid_count,
                        count(distinct p.source_id)::int as source_count,
                        count(distinct p.passage_id)::int as passage_count,
                        coalesce(sum(length(p.text)), 0)::int as char_count
                    from review_passages p
                    where p.review_id = $1
                ),
                failed as (
                    select count(distinct j.source_id)::int as failed_source_count
                    from review_preparation_jobs j
                    left join full_text_retrieval_attempts a
                        on a.review_id = j.review_id
                       and a.source_id = j.source_id
                    where j.review_id = $1
                      and (
                        j.status = 'failed'
                        or (a.status is not null and a.status <> 'success')
                      )
                )
                select
                    indexed.pmid_count,
                    indexed.source_count,
                    indexed.passage_count,
                    indexed.char_count,
                    failed.failed_source_count
                from indexed, failed
                """,
                review_id,
            )
        return _review_index_totals_from_row(row)

    async def available_sections(self, review_id: str) -> list[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select distinct section
                from review_passages
                where review_id = $1 and section is not null
                order by section
                """,
                review_id,
            )
        return [str(row["section"]) for row in rows]

    async def indexed_pmids(self, review_id: str) -> list[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                select distinct pmid
                from review_passages
                where review_id = $1 and pmid is not null
                order by pmid
                """,
                review_id,
            )
        return [str(row["pmid"]) for row in rows]

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
