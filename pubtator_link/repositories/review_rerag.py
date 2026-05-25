"""PostgreSQL repository for review-scoped re-RAG data."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from pubtator_link.models.review_rerag import (
    EvidenceCertaintyRecord,
    FailedSourceSummary,
    PreparationEnqueueResult,
    PreparationStatus,
    RecordReviewContextRequest,
    RecordReviewContextResponse,
    ResearchSessionCandidate,
    ResearchSessionManifest,
    ReviewIndexInventoryItem,
    ReviewIndexTotals,
    ReviewLlmContext,
    ReviewLlmContextEvent,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
    SampleSectionPolicy,
    UpsertEvidenceCertaintyRequest,
)
from pubtator_link.repositories import review_research_sessions
from pubtator_link.repositories.review_rerag_mappers import (
    _evidence_certainty_from_row,
    _failed_source_summary_from_row,
    _filter_or_none,
    _parse_execute_count,
    _passage_from_row,
    _passage_sample_from_row,
    _preparation_status_from_row,
    _recall_terms,
    _recall_tsquery,
    _research_session_candidate_from_row,
    _review_index_totals_from_row,
    _review_inventory_item_from_row,
    _source_summary_from_row,
)
from pubtator_link.services.review_context.embeddings import text_hash

SHORT_SAMPLE_WARNING = "Only short sample passages were available for this PMID."


@dataclass(frozen=True)
class ReviewPassageEmbeddingRecord:
    review_id: str
    passage_id: str
    model_name: str
    embedding_dim: int
    text_hash: str
    embedding: list[float]


def _sample_warning(
    samples: list[ReviewPassageSample],
    *,
    min_sample_chars: int,
) -> str | None:
    if samples and all(sample.char_count < min_sample_chars for sample in samples):
        return SHORT_SAMPLE_WARNING
    return None


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, str):
        return json.loads(value)
    return value


def _vector_literal(values: Sequence[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"


def _embedding_vector_from_value(value: Any) -> list[float]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1]
        if not stripped:
            return []
        return [float(item) for item in stripped.split(",")]
    return [float(item) for item in value]


def _llm_context_from_row(row: Mapping[str, Any]) -> ReviewLlmContext:
    return ReviewLlmContext(
        context_id=str(row["context_id"]),
        review_id=str(row["review_id"]),
        session_id=row["session_id"],
        kind=row["kind"],
        topic=row["topic"],
        research_question=row["research_question"],
        question_hash=row["question_hash"],
        request=_json_value(row["request"], {}),
        response_summary=_json_value(row["response_summary"], {}),
        selected_pmids=list(row["selected_pmids"] or []),
        rejected_pmids=list(row["rejected_pmids"] or []),
        preferred_entity_ids=list(row["preferred_entity_ids"] or []),
        active_queries=list(row["active_queries"] or []),
        successful_queries=list(row["successful_queries"] or []),
        failed_queries=list(row["failed_queries"] or []),
        selected_passage_ids=list(row["selected_passage_ids"] or []),
        audit_passage_ids=list(row["audit_passage_ids"] or []),
        open_questions=_json_value(row["open_questions"], []),
        user_decisions=_json_value(row["user_decisions"], []),
        last_next_commands=_json_value(row["last_next_commands"], []),
        stable_citation_keys=_json_value(row["stable_citation_keys"], {}),
        cache_key=row["cache_key"],
        token_estimate=row["token_estimate"],
        created_by=row["created_by"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _llm_context_event_from_row(row: Mapping[str, Any]) -> ReviewLlmContextEvent:
    return ReviewLlmContextEvent(
        event_id=str(row["event_id"]),
        context_id=str(row["context_id"]) if row["context_id"] is not None else None,
        review_id=str(row["review_id"]),
        session_id=row["session_id"],
        event_type=row["event_type"],
        summary=row["summary"],
        pmids=list(row["pmids"] or []),
        passage_ids=list(row["passage_ids"] or []),
        queries=list(row["queries"] or []),
        decision=_json_value(row["decision"], None),
        payload=_json_value(row["payload"], {}),
        created_by=row["created_by"],
        created_at=str(row["created_at"]),
    )


class ReviewReragRepository(Protocol):
    """Persistence contract for review-scoped preparation and retrieval."""

    async def enqueue_preparation_job(
        self, review_id: str, source_id: str, source_kind: str
    ) -> PreparationEnqueueResult:
        """Create or deduplicate a preparation job and return durable enqueue result."""

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        url: str | None = None,
        reason: str | None = None,
        coverage_reason: str = "unknown",
        attempt_count: int = 1,
        last_status_code: int | None = None,
        retry_after_ms: int | None = None,
        backoff_ms: int | None = None,
        terminal_reason: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        license_or_access_hint: str | None = None,
        pmc_fallback_available: bool = False,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> None:
        """Record one full-text retrieval attempt for audit/debugging."""

    async def mark_running_jobs_failed_on_startup(self) -> int:
        """Mark orphaned running jobs as failed and return the affected count."""

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus:
        """Return aggregate preparation status counts for a review."""

    async def preparation_job_statuses(
        self, review_id: str, source_ids: Sequence[str]
    ) -> dict[str, str]:
        """Return current durable job statuses for source IDs."""

    async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
        """Atomically move a queued preparation job to running if available."""

    async def link_review_session_source(
        self, review_id: str, session_id: str, source_id: str
    ) -> None:
        """Link a prepared source to a research session."""

    async def research_session_exists(self, review_id: str, session_id: str) -> bool:
        """Return whether a research session exists."""

    async def upsert_passages(self, passages: Sequence[ReviewPassageRow]) -> None:
        """Insert or replace prepared review passages."""

    async def upsert_passage_embeddings(
        self, records: Sequence[ReviewPassageEmbeddingRecord]
    ) -> None:
        """Insert or replace stored passage embeddings."""

    async def get_passage_embeddings(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        model_name: str,
        passage_text_hashes: Mapping[str, str] | None = None,
    ) -> dict[str, list[float]]:
        """Return current embeddings by passage ID."""

    async def list_passages_missing_embeddings(
        self,
        review_id: str,
        *,
        model_name: str,
        limit: int = 100,
    ) -> list[ReviewPassageRow]:
        """Return passages with absent or stale embeddings."""

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        """Search prepared passages for a review."""

    async def get_passages_by_id(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        """Return review passages in the requested passage ID order."""

    async def neighboring_passages(
        self,
        review_id: str,
        passage_id: str,
        before: int,
        after: int,
        same_section: bool,
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        """Return passages around an anchor passage."""

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
        min_sample_chars: int = 80,
        sample_section_policy: SampleSectionPolicy = "evidence_first",
        session_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReviewSourceSummary]:
        """List review source summaries, optionally with passage samples."""

    async def list_review_failed_sources(
        self,
        review_id: str,
        *,
        session_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[FailedSourceSummary]:
        """List failed review sources with audit reasons."""

    async def review_index_totals(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewIndexTotals:
        """Return aggregate index counts for a review."""

    async def available_sections(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        """Return distinct indexed sections for retrieval diagnostics."""

    async def indexed_pmids(self, review_id: str, *, session_id: str | None = None) -> list[str]:
        """Return distinct indexed PMIDs for retrieval diagnostics."""

    async def list_review_passage_ids(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        """Return stable passage IDs for a review."""

    async def record_review_audit_event(
        self,
        review_id: str,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        """Record an append-only review audit event."""

    async def list_review_audit_events(
        self, review_id: str, *, limit: int | None = None
    ) -> list[Mapping[str, object]]:
        """Return append-only review audit events."""

    async def record_llm_context_event(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        """Persist a compact LLM context snapshot and append-only context event."""

    async def get_latest_llm_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        """Return the latest durable LLM context snapshot for a review."""

    async def list_review_indexes(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        ttl_seconds: int | None = None,
    ) -> list[ReviewIndexInventoryItem]:
        """Return inventory summaries for persisted review indexes."""

    async def get_review_index_summary(
        self,
        review_id: str,
        *,
        ttl_seconds: int | None = None,
    ) -> ReviewIndexInventoryItem | None:
        """Return an inventory summary for one review index."""

    async def delete_review_index(self, review_id: str) -> bool:
        """Delete one review index and all repository-owned child rows."""

    async def upsert_research_session(
        self,
        *,
        review_id: str,
        session_id: str,
        query: str | None,
        status: str,
        request: dict[str, Any],
    ) -> None:
        """Create or update a staged research session manifest."""

    async def upsert_research_session_candidate(
        self,
        *,
        review_id: str,
        session_id: str,
        candidate: ResearchSessionCandidate,
    ) -> None:
        """Create or update one staged research session candidate."""

    async def get_research_session(
        self, review_id: str, session_id: str
    ) -> ResearchSessionManifest | None:
        """Return one staged research session manifest."""

    async def list_research_sessions(self, review_id: str) -> list[ResearchSessionManifest]:
        """List staged research session manifests for a review."""

    async def list_research_sessions_global(self, limit: int = 20) -> list[ResearchSessionManifest]:
        """List staged research session manifests across reviews."""

    async def find_research_sessions_by_session_id(
        self, session_id: str
    ) -> list[ResearchSessionManifest]:
        """Return all staged research sessions matching one session ID."""

    async def cleanup_expired_review_indexes(self, *, ttl_seconds: int) -> list[str]:
        """Delete review indexes whose updated timestamp is older than the TTL."""

    async def upsert_evidence_certainty(
        self,
        review_id: str,
        request: UpsertEvidenceCertaintyRequest,
        *,
        certainty_id: str | None = None,
    ) -> EvidenceCertaintyRecord:
        """Create or update a user-supplied certainty record."""

    async def list_evidence_certainty(self, review_id: str) -> list[EvidenceCertaintyRecord]:
        """List user-supplied certainty records for a review."""

    async def get_evidence_certainty(
        self,
        review_id: str,
        certainty_id: str,
    ) -> EvidenceCertaintyRecord | None:
        """Get one user-supplied certainty record."""

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        """Mark a preparation job as finished."""


class PostgresReviewReragRepository:
    """asyncpg-backed repository for review-scoped re-RAG persistence."""

    DEFAULT_ACQUIRE_TIMEOUT_SECONDS: float = 5.0

    def __init__(self, pool: Any, *, acquire_timeout: float | None = None) -> None:
        self._pool = pool
        self._acquire_timeout: float | None = (
            acquire_timeout if acquire_timeout is not None else self.DEFAULT_ACQUIRE_TIMEOUT_SECONDS
        )

    def _acquire(self) -> Any:
        """Acquire a pooled connection with the configured timeout.

        Returns the asyncpg pool acquire context manager. Use as
        ``async with self._acquire() as connection:``.
        """
        if self._acquire_timeout is None:
            return self._pool.acquire()
        try:
            return self._pool.acquire(timeout=self._acquire_timeout)
        except TypeError:
            # Compatibility with pool fakes that ignore the timeout kwarg
            return self._pool.acquire()

    async def enqueue_preparation_job(
        self, review_id: str, source_id: str, source_kind: str
    ) -> PreparationEnqueueResult:
        async with self._acquire() as connection, connection.transaction():
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do update
                set updated_at = now()
                """,
                review_id,
            )
            existing = await connection.fetchrow(
                """
                select status
                from review_preparation_jobs
                where review_id = $1 and source_id = $2
                for update
                """,
                review_id,
                source_id,
            )
            if existing is not None:
                status = str(existing["status"])
                if status in {"complete", "partial"}:
                    return "already_indexed"
                if status == "queued":
                    return "already_queued"
                if status == "running":
                    return "already_running"
                if status == "failed":
                    await connection.execute(
                        """
                        update review_preparation_jobs
                        set source_kind = $3,
                            status = 'queued',
                            error = null,
                            updated_at = now()
                        where review_id = $1 and source_id = $2
                        """,
                        review_id,
                        source_id,
                        source_kind,
                    )
                    return "previously_failed_requeued"

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
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
            )
            return "newly_queued"

    async def record_retrieval_attempt(
        self,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        *,
        url: str | None = None,
        reason: str | None = None,
        coverage_reason: str = "unknown",
        attempt_count: int = 1,
        last_status_code: int | None = None,
        retry_after_ms: int | None = None,
        backoff_ms: int | None = None,
        terminal_reason: str | None = None,
        pmcid: str | None = None,
        doi: str | None = None,
        license_or_access_hint: str | None = None,
        pmc_fallback_available: bool = False,
        content_type: str | None = None,
        content_length: int | None = None,
    ) -> None:
        async with self._acquire() as connection:
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
                    coverage_reason,
                    attempt_count,
                    last_status_code,
                    retry_after_ms,
                    backoff_ms,
                    terminal_reason,
                    pmcid,
                    doi,
                    license_or_access_hint,
                    pmc_fallback_available,
                    content_type,
                    content_length
                )
                values (
                    $1, $2, $3, $4, $5, $6, $7, $8,
                    $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19
                )
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
                status,
                url,
                reason,
                coverage_reason,
                attempt_count,
                last_status_code,
                retry_after_ms,
                backoff_ms,
                terminal_reason,
                pmcid,
                doi,
                license_or_access_hint,
                pmc_fallback_available,
                content_type,
                content_length,
            )
            await self._touch_review_on_connection(connection, review_id)

    async def mark_running_jobs_failed_on_startup(self) -> int:
        async with self._acquire() as connection:
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

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus:
        async with self._acquire() as connection:
            return await self._preparation_status_on_connection(
                connection, review_id, session_id=session_id
            )

    async def preparation_job_statuses(
        self, review_id: str, source_ids: Sequence[str]
    ) -> dict[str, str]:
        if not source_ids:
            return {}
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select source_id, status
                from review_preparation_jobs
                where review_id = $1 and source_id = any($2::text[])
                """,
                review_id,
                list(source_ids),
            )
        return {str(row["source_id"]): str(row["status"]) for row in rows}

    async def link_review_session_source(
        self, review_id: str, session_id: str, source_id: str
    ) -> None:
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into review_session_sources (review_id, session_id, source_id)
                values ($1, $2, $3)
                on conflict (review_id, session_id, source_id) do nothing
                """,
                review_id,
                session_id,
                source_id,
            )

    async def research_session_exists(self, review_id: str, session_id: str) -> bool:
        async with self._acquire() as connection:
            row = await connection.fetchrow(
                """
                select 1
                from review_research_sessions
                where review_id = $1 and session_id = $2
                """,
                review_id,
                session_id,
            )
        return row is not None

    async def claim_preparation_job(self, *, review_id: str, source_id: str) -> bool:
        async with self._acquire() as connection, connection.transaction():
            await connection.execute(
                "select pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"{review_id}:{source_id}",
            )
            claimed = await connection.fetchrow(
                """
                update review_preparation_jobs
                set status = 'running',
                    started_at = now(),
                    error = null
                where review_id = $1 and source_id = $2 and status = 'queued'
                returning job_id
                """,
                review_id,
                source_id,
            )
            if claimed is None:
                return False
            await self._touch_review_on_connection(connection, review_id)
            return True

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        async with self._acquire() as connection:
            await connection.execute(
                """
                with updated as (
                    update review_preparation_jobs
                    set status = $3,
                        finished_at = now(),
                        error = $4
                    where review_id = $1 and source_id = $2
                    returning review_id
                )
                update reviews
                set updated_at = now()
                where review_id in (select review_id from updated)
                """,
                review_id,
                source_id,
                status,
                error,
            )

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
        async with self._acquire() as connection:
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
            review_ids = sorted({passage.review_id for passage in passages})
            for review_id in review_ids:
                await self._touch_review_on_connection(connection, review_id)

    async def upsert_passage_embeddings(
        self, records: Sequence[ReviewPassageEmbeddingRecord]
    ) -> None:
        if not records:
            return

        args = [
            (
                record.review_id,
                record.passage_id,
                record.model_name,
                record.embedding_dim,
                record.text_hash,
                _vector_literal(record.embedding),
            )
            for record in records
        ]
        async with self._acquire() as connection:
            await connection.executemany(
                """
                insert into review_passage_embeddings (
                    review_id,
                    passage_id,
                    model_name,
                    embedding_dim,
                    text_hash,
                    embedding
                )
                values ($1, $2, $3, $4, $5, $6::vector)
                on conflict (review_id, passage_id, model_name) do update
                set embedding_dim = excluded.embedding_dim,
                    text_hash = excluded.text_hash,
                    embedding = excluded.embedding,
                    created_at = now()
                """,
                args,
            )
            review_ids = sorted({record.review_id for record in records})
            for review_id in review_ids:
                await self._touch_review_on_connection(connection, review_id)

    async def get_passage_embeddings(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        model_name: str,
        passage_text_hashes: Mapping[str, str] | None = None,
    ) -> dict[str, list[float]]:
        if not passage_ids:
            return {}

        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select passage_id, text_hash, embedding
                from review_passage_embeddings
                where review_id = $1
                  and passage_id = any($2::text[])
                  and model_name = $3
                """,
                review_id,
                list(passage_ids),
                model_name,
            )
        embeddings: dict[str, list[float]] = {}
        for row in rows:
            passage_id = str(row["passage_id"])
            if (
                passage_text_hashes is not None
                and passage_text_hashes.get(passage_id) != row["text_hash"]
            ):
                continue
            embeddings[passage_id] = _embedding_vector_from_value(row["embedding"])
        return embeddings

    async def list_passages_missing_embeddings(
        self,
        review_id: str,
        *,
        model_name: str,
        limit: int = 100,
    ) -> list[ReviewPassageRow]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select
                    p.passage_id,
                    p.review_id,
                    p.source_id,
                    p.source_kind,
                    p.pmid,
                    p.pmcid,
                    p.doi,
                    p.url,
                    p.section,
                    p.heading_path,
                    p.page,
                    p.text,
                    p.entity_ids,
                    p.relation_types,
                    p.screening_status,
                    p.source_metadata,
                    0.0::double precision as lexical_rank,
                    e.text_hash as embedding_text_hash
                from review_passages p
                left join review_passage_embeddings e
                  on e.review_id = p.review_id
                 and e.passage_id = p.passage_id
                 and e.model_name = $2
                where p.review_id = $1
                order by p.source_id, p.passage_id
                limit $3
                """,
                review_id,
                model_name,
                limit,
            )

        stale_or_missing: list[ReviewPassageRow] = []
        for row in rows:
            embedding_text_hash = row["embedding_text_hash"]
            current_text_hash = text_hash(str(row["text"]))
            if embedding_text_hash is None or str(embedding_text_hash) != current_text_hash:
                stale_or_missing.append(_passage_from_row(row))
        return stale_or_missing

    async def search_passages(
        self,
        review_id: str,
        query: str,
        *,
        entity_ids: Sequence[str] | None = None,
        pmids: Sequence[str] | None = None,
        sections: Sequence[str] | None = None,
        session_id: str | None = None,
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        entity_filter = _filter_or_none(entity_ids)
        pmid_filter = _filter_or_none(pmids)
        section_filter = _filter_or_none(sections)
        recall_query = _recall_tsquery(query)
        recall_terms = _recall_terms(query)
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                with query as (
                    select
                        phraseto_tsquery('english', $2) as phrase_query,
                        websearch_to_tsquery('english', $2) as strict_query,
                        to_tsquery('english', $7) as recall_query
                ),
                ranked as (
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
                    ts_rank_cd(search_vector, query.phrase_query) as phrase_rank,
                    ts_rank_cd(search_vector, query.strict_query) as strict_rank,
                    ts_rank_cd(search_vector, query.recall_query) as recall_rank,
                    (
                        select count(*)
                        from (
                            select distinct token
                            from regexp_split_to_table(
                                lower(review_passages.text),
                                '[^a-zA-Z0-9]+'
                            ) as token
                            where length(token) >= 3
                        ) passage_terms
                        where passage_terms.token = any($9::text[])
                    ) as recall_overlap_count
                from review_passages, query
                where review_id = $1
                  and (
                      search_vector @@ query.phrase_query
                      or search_vector @@ query.strict_query
                      or search_vector @@ query.recall_query
                  )
                  and ($3::text[] is null or entity_ids && $3::text[])
                  and ($4::text[] is null or pmid = any($4::text[]))
                  and ($5::text[] is null or section = any($5::text[]))
                  and (
                      $8::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $8
                            and rss.source_id = review_passages.source_id
                      )
                  )
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
                        phrase_rank * 3.0
                        + strict_rank * 2.0
                        + recall_rank
                    )
                    * case
                        when phrase_rank = 0
                          and strict_rank = 0
                          and recall_rank > 0
                          and array_length(regexp_split_to_array($2, E'\\s+'), 1) >= 4
                          and recall_overlap_count <= 1
                        then least(1.0, greatest(0.25, char_length(text)::double precision / 400.0))
                        else 1.0
                      end as lexical_rank
                from ranked
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
                session_id,
                recall_terms,
            )
        return [_passage_from_row(row) for row in rows]

    async def get_passages_by_id(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        if not passage_ids:
            return []
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
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
                    0.0::double precision as lexical_rank
                from review_passages
                where review_id = $1
                  and passage_id = any($2::text[])
                  and (
                      $3::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $3
                            and rss.source_id = review_passages.source_id
                      )
                  )
                """,
                review_id,
                list(passage_ids),
                session_id,
            )
        parsed_rows = [_passage_from_row(row) for row in rows]
        row_by_id = {row.passage_id: row for row in parsed_rows}
        return [row_by_id[passage_id] for passage_id in passage_ids if passage_id in row_by_id]

    async def neighboring_passages(
        self,
        review_id: str,
        passage_id: str,
        before: int,
        after: int,
        same_section: bool,
        *,
        session_id: str | None = None,
    ) -> list[ReviewPassageRow]:
        async with self._acquire() as connection:
            anchor_row = await connection.fetchrow(
                """
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
                    0.0::double precision as lexical_rank
                from review_passages
                where review_id = $1
                  and passage_id = $2
                  and (
                      $3::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $3
                            and rss.source_id = review_passages.source_id
                      )
                  )
                """,
                review_id,
                passage_id,
                session_id,
            )
            if anchor_row is None:
                return []
            anchor = _passage_from_row(anchor_row)
            rows = await connection.fetch(
                """
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
                    0.0::double precision as lexical_rank
                from review_passages
                where review_id = $1
                  and source_id = $2
                  and ($3::boolean = false or section = $4)
                  and (
                      $5::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $5
                            and rss.source_id = review_passages.source_id
                      )
                  )
                order by passage_id
                """,
                review_id,
                anchor.source_id,
                same_section,
                anchor.section,
                session_id,
            )
        candidates = [_passage_from_row(row) for row in rows]
        anchor_index = next(
            (index for index, row in enumerate(candidates) if row.passage_id == passage_id),
            None,
        )
        if anchor_index is None:
            return []
        start = max(0, anchor_index - before)
        stop = anchor_index + after + 1
        return candidates[start:stop]

    async def list_review_sources(
        self,
        review_id: str,
        pmids: Sequence[str] | None = None,
        *,
        include_passage_samples: bool = False,
        sample_per_pmid: int = 2,
        min_sample_chars: int = 80,
        sample_section_policy: SampleSectionPolicy = "evidence_first",
        session_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReviewSourceSummary]:
        pmid_filter = _filter_or_none(pmids)
        async with self._acquire() as connection:
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
                      and (
                          $3::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = j.review_id
                                and rss.session_id = $3
                                and rss.source_id = j.source_id
                          )
                      )
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
                            filter (where status is not null) as attempt_statuses,
                        (array_agg(coverage_reason order by created_at desc)
                            filter (where coverage_reason is not null))[1] as coverage_reason,
                        (array_agg(pmcid order by created_at desc)
                            filter (where pmcid is not null))[1] as pmcid,
                        (array_agg(doi order by created_at desc)
                            filter (where doi is not null))[1] as doi,
                        (array_agg(license_or_access_hint order by created_at desc)
                            filter (where license_or_access_hint is not null))[1]
                            as license_or_access_hint,
                        bool_or(pmc_fallback_available) as pmc_fallback_available,
                        jsonb_agg(
                            jsonb_build_object(
                                'source_kind', source_kind,
                                'status', status,
                                'attempt_count', attempt_count,
                                'last_status_code', last_status_code,
                                'retry_after_ms', retry_after_ms,
                                'backoff_ms', backoff_ms,
                                'terminal_reason', terminal_reason,
                                'source_id', source_id,
                                'url', url,
                                'pmid', case
                                    when source_id ~ '^[0-9]+$' then source_id
                                    when source_id ~ '^PMID:(.+)$'
                                        then substring(source_id from '^PMID:(.+)$')
                                    else null
                                end,
                                'pmcid', pmcid,
                                'doi', doi,
                                'content_type', content_type,
                                'content_length', content_length
                            )
                            order by created_at
                        ) filter (where status is not null) as resolver_attempts
                    from full_text_retrieval_attempts
                    where review_id = $1
                      and (
                          $3::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = full_text_retrieval_attempts.review_id
                                and rss.session_id = $3
                                and rss.source_id = case
                                    when full_text_retrieval_attempts.source_id ~ '^https?://'
                                        then 'URL:' || full_text_retrieval_attempts.source_id
                                    else full_text_retrieval_attempts.source_id
                                end
                          )
                      )
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
                      and (
                          $3::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = review_passages.review_id
                                and rss.session_id = $3
                                and rss.source_id = review_passages.source_id
                          )
                      )
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
                    coalesce(p.char_count, 0)::int as char_count,
                    coalesce(a.coverage_reason, 'unknown') as coverage_reason,
                    a.pmcid,
                    a.doi,
                    a.license_or_access_hint,
                    coalesce(a.pmc_fallback_available, false) as pmc_fallback_available,
                    coalesce(a.resolver_attempts, '[]'::jsonb) as resolver_attempts
                from source_scope s
                left join attempt_stats a
                    on a.review_id = s.review_id
                   and a.source_id = s.source_id
                left join passage_stats p
                    on p.review_id = s.review_id
                   and p.source_id = s.source_id
                where $2::text[] is null or s.pmid = any($2::text[])
                order by s.source_id
                limit coalesce($4::int, 2147483647)
                offset $5::int
                """,
                review_id,
                pmid_filter,
                session_id,
                limit,
                offset,
            )
            sources = [_source_summary_from_row(row) for row in rows]
            if include_passage_samples and sources and sample_per_pmid > 0:
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
                                order by
                                    case
                                        when $5::text = 'evidence_first'
                                             and char_length(text) >= $6::int then 0
                                        when $5::text = 'evidence_first' then 1
                                        else 0
                                    end,
                                    case
                                        when $5::text <> 'evidence_first' then 0
                                        when lower(section) in (
                                            'abstract',
                                            'results',
                                            'discussion',
                                            'methods',
                                            'introduction'
                                        ) then 0
                                        when lower(section) in ('background', 'conclusion') then 1
                                        else 2
                                    end,
                                    case
                                        when $5::text = 'evidence_first' then section
                                        else ''
                                    end,
                                    case
                                        when $5::text = 'evidence_first' then null
                                        else created_at
                                    end,
                                    passage_id
                            ) as sample_rank
                        from review_passages
                        where review_id = $1
                          and ($2::text[] is null or pmid = any($2::text[]))
                          and source_id = any($3::text[])
                          and (
                              $7::text is null
                              or exists (
                                  select 1
                                  from review_session_sources rss
                                  where rss.review_id = review_passages.review_id
                                    and rss.session_id = $7
                                    and rss.source_id = review_passages.source_id
                              )
                          )
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
                    sample_section_policy,
                    min_sample_chars,
                    session_id,
                )
                samples_by_source: dict[str, list[ReviewPassageSample]] = {}
                for row in sample_rows:
                    samples_by_source.setdefault(row["source_id"], []).append(
                        _passage_sample_from_row(row)
                    )
                sources = [
                    source.model_copy(
                        update={
                            "sample_passages": samples_by_source.get(source.source_id, []),
                            "sample_warning": _sample_warning(
                                samples_by_source.get(source.source_id, []),
                                min_sample_chars=min_sample_chars,
                            ),
                        }
                    )
                    for source in sources
                ]
        return sources

    async def list_review_failed_sources(
        self,
        review_id: str,
        *,
        session_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[FailedSourceSummary]:
        async with self._acquire() as connection:
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
                      and (
                          $2::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = j.review_id
                                and rss.session_id = $2
                                and rss.source_id = j.source_id
                          )
                      )
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
                    ) as attempt_statuses,
                    coalesce(
                        (array_agg(a.coverage_reason order by a.created_at desc)
                            filter (where a.coverage_reason is not null))[1],
                        'unknown'
                    ) as coverage_reason,
                    (array_agg(a.pmcid order by a.created_at desc)
                        filter (where a.pmcid is not null))[1] as pmcid,
                    (array_agg(a.doi order by a.created_at desc)
                        filter (where a.doi is not null))[1] as doi,
                    (array_agg(a.license_or_access_hint order by a.created_at desc)
                        filter (where a.license_or_access_hint is not null))[1]
                        as license_or_access_hint,
                    coalesce(bool_or(a.pmc_fallback_available), false) as pmc_fallback_available,
                    coalesce(
                        jsonb_agg(
                            jsonb_build_object(
                                'source_kind', a.source_kind,
                                'status', a.status,
                                'attempt_count', a.attempt_count,
                                'last_status_code', a.last_status_code,
                                'retry_after_ms', a.retry_after_ms,
                                'backoff_ms', a.backoff_ms,
                                'terminal_reason', a.terminal_reason,
                                'source_id', a.source_id,
                                'url', a.url,
                                'pmid', s.pmid,
                                'pmcid', a.pmcid,
                                'doi', a.doi,
                                'content_type', a.content_type,
                                'content_length', a.content_length
                            )
                            order by a.created_at
                        ) filter (where a.status is not null),
                        '[]'::jsonb
                    ) as resolver_attempts
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
                limit coalesce($3::int, 2147483647)
                offset $4::int
                """,
                review_id,
                session_id,
                limit,
                offset,
            )
        return [_failed_source_summary_from_row(row) for row in rows]

    async def review_index_totals(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewIndexTotals:
        async with self._acquire() as connection:
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
                      and (
                          $2::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = p.review_id
                                and rss.session_id = $2
                                and rss.source_id = p.source_id
                          )
                      )
                ),
                failed as (
                    select count(distinct j.source_id)::int as failed_source_count
                    from review_preparation_jobs j
                    left join full_text_retrieval_attempts a
                        on a.review_id = j.review_id
                       and a.source_id = j.source_id
                    where j.review_id = $1
                      and (
                          $2::text is null
                          or exists (
                              select 1
                              from review_session_sources rss
                              where rss.review_id = j.review_id
                                and rss.session_id = $2
                                and rss.source_id = j.source_id
                          )
                      )
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
                session_id,
            )
        return _review_index_totals_from_row(row)

    async def available_sections(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select distinct section
                from review_passages
                where review_id = $1 and section is not null
                  and (
                      $2::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $2
                            and rss.source_id = review_passages.source_id
                      )
                  )
                order by section
                """,
                review_id,
                session_id,
            )
        return [str(row["section"]) for row in rows]

    async def indexed_pmids(self, review_id: str, *, session_id: str | None = None) -> list[str]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select distinct pmid
                from review_passages
                where review_id = $1 and pmid is not null
                  and (
                      $2::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $2
                            and rss.source_id = review_passages.source_id
                      )
                  )
                order by pmid
                """,
                review_id,
                session_id,
            )
        return [str(row["pmid"]) for row in rows]

    async def list_review_passage_ids(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select passage_id
                from review_passages
                where review_id = $1
                  and (
                      $2::text is null
                      or exists (
                          select 1
                          from review_session_sources rss
                          where rss.review_id = review_passages.review_id
                            and rss.session_id = $2
                            and rss.source_id = review_passages.source_id
                      )
                  )
                order by passage_id
                """,
                review_id,
                session_id,
            )
        return [str(row["passage_id"]) for row in rows]

    async def record_review_audit_event(
        self,
        review_id: str,
        event_type: str,
        payload: Mapping[str, object],
    ) -> None:
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into review_audit_events (review_id, event_type, payload)
                values ($1, $2, $3::jsonb)
                """,
                review_id,
                event_type,
                json.dumps(payload, sort_keys=True),
            )
            await self._touch_review_on_connection(connection, review_id)

    async def list_review_audit_events(
        self, review_id: str, *, limit: int | None = None
    ) -> list[Mapping[str, object]]:
        async with self._acquire() as connection:
            query = """
                select event_type, payload, created_at
                from review_audit_events
                where review_id = $1
                order by created_at asc
                """
            args: list[object] = [review_id]
            if limit is not None:
                query += " limit $2"
                args.append(limit)
            rows = await connection.fetch(query, *args)
        return [
            {
                "event_type": row["event_type"],
                "payload": row["payload"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    async def record_llm_context_event(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        async with self._acquire() as connection, connection.transaction():
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do update
                set updated_at = now()
                """,
                review_id,
            )
            context_row = await connection.fetchrow(
                """
                insert into review_llm_context (
                    review_id,
                    session_id,
                    kind,
                    topic,
                    research_question,
                    question_hash,
                    request,
                    response_summary,
                    selected_pmids,
                    rejected_pmids,
                    preferred_entity_ids,
                    active_queries,
                    successful_queries,
                    failed_queries,
                    selected_passage_ids,
                    audit_passage_ids,
                    open_questions,
                    user_decisions,
                    last_next_commands,
                    stable_citation_keys,
                    cache_key,
                    token_estimate,
                    created_by
                )
                values (
                    $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb,
                    $9, $10, $11, $12, $13, $14, $15, $16,
                    $17::jsonb, $18::jsonb, $19::jsonb, $20::jsonb,
                    $21, $22, $23
                )
                returning *
                """,
                review_id,
                request.session_id,
                request.kind,
                request.topic,
                request.research_question,
                request.question_hash,
                json.dumps(request.request, sort_keys=True),
                json.dumps(request.response_summary, sort_keys=True),
                request.selected_pmids,
                request.rejected_pmids,
                request.preferred_entity_ids,
                request.active_queries,
                request.successful_queries,
                request.failed_queries,
                request.selected_passage_ids,
                request.audit_passage_ids,
                json.dumps(request.open_questions, sort_keys=True),
                json.dumps(request.user_decisions, sort_keys=True),
                json.dumps(request.last_next_commands, sort_keys=True),
                json.dumps(request.stable_citation_keys, sort_keys=True),
                request.cache_key,
                request.token_estimate,
                request.created_by,
            )
            event_row = await connection.fetchrow(
                """
                insert into review_llm_context_events (
                    context_id,
                    review_id,
                    session_id,
                    event_type,
                    summary,
                    pmids,
                    passage_ids,
                    queries,
                    decision,
                    payload,
                    created_by
                )
                values (
                    $1::uuid, $2, $3, $4, $5, $6, $7, $8,
                    $9::jsonb, $10::jsonb, $11
                )
                returning *
                """,
                context_row["context_id"],
                review_id,
                request.session_id,
                request.event_type,
                request.summary,
                request.pmids,
                request.passage_ids,
                request.queries,
                json.dumps(request.decision, sort_keys=True)
                if request.decision is not None
                else None,
                json.dumps(request.payload, sort_keys=True),
                request.created_by,
            )
            await self._touch_review_on_connection(connection, review_id)
        return RecordReviewContextResponse(
            context=_llm_context_from_row(context_row),
            event=_llm_context_event_from_row(event_row),
        )

    async def get_latest_llm_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        async with self._acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from review_llm_context
                where review_id = $1
                  and ($2::text is null or session_id = $2)
                order by updated_at desc, created_at desc
                limit 1
                """,
                review_id,
                session_id,
            )
        return _llm_context_from_row(row) if row is not None else None

    async def list_review_indexes(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        ttl_seconds: int | None = None,
    ) -> list[ReviewIndexInventoryItem]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                self._review_inventory_sql(filtered=False),
                limit,
                offset,
            )
        return [_review_inventory_item_from_row(row, ttl_seconds=ttl_seconds) for row in rows]

    async def get_review_index_summary(
        self,
        review_id: str,
        *,
        ttl_seconds: int | None = None,
    ) -> ReviewIndexInventoryItem | None:
        async with self._acquire() as connection:
            row = await connection.fetchrow(
                self._review_inventory_sql(filtered=True),
                1,
                0,
                review_id,
            )
        if row is None:
            return None
        return _review_inventory_item_from_row(row, ttl_seconds=ttl_seconds)

    async def delete_review_index(self, review_id: str) -> bool:
        async with self._acquire() as connection, connection.transaction():
            await connection.execute(
                """
                delete from review_research_session_candidates
                where review_id = $1
                """,
                review_id,
            )
            await connection.execute(
                "delete from review_research_sessions where review_id = $1",
                review_id,
            )
            await connection.execute(
                "delete from review_audit_events where review_id = $1", review_id
            )
            await connection.execute(
                "delete from review_llm_context_events where review_id = $1",
                review_id,
            )
            await connection.execute(
                "delete from review_llm_context where review_id = $1",
                review_id,
            )
            await connection.execute(
                "delete from review_evidence_certainty where review_id = $1",
                review_id,
            )
            await connection.execute(
                "delete from full_text_retrieval_attempts where review_id = $1",
                review_id,
            )
            await connection.execute("delete from review_passages where review_id = $1", review_id)
            await connection.execute(
                "delete from review_preparation_jobs where review_id = $1",
                review_id,
            )
            result = await connection.execute("delete from reviews where review_id = $1", review_id)
        return _parse_execute_count(result) > 0

    async def cleanup_expired_review_indexes(self, *, ttl_seconds: int) -> list[str]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select review_id
                from reviews
                where updated_at < now() - ($1::int * interval '1 second')
                order by updated_at asc, review_id asc
                """,
                ttl_seconds,
            )
        review_ids = [str(row["review_id"]) for row in rows]
        deleted: list[str] = []
        for review_id in review_ids:
            if await self.delete_review_index(review_id):
                deleted.append(review_id)
        return deleted

    async def upsert_research_session(
        self,
        *,
        review_id: str,
        session_id: str,
        query: str | None,
        status: str,
        request: dict[str, Any],
    ) -> None:
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do update
                set updated_at = now()
                """,
                review_id,
            )
            await connection.execute(
                """
                insert into review_research_sessions
                    (review_id, session_id, query, status, request, updated_at)
                values ($1, $2, $3, $4, $5::jsonb, now())
                on conflict (review_id, session_id) do update set
                    query = excluded.query,
                    status = excluded.status,
                    request = excluded.request,
                    updated_at = now()
                """,
                review_id,
                session_id,
                query,
                status,
                json.dumps(request),
            )

    async def upsert_research_session_candidate(
        self,
        *,
        review_id: str,
        session_id: str,
        candidate: ResearchSessionCandidate,
    ) -> None:
        coverage_hint = (
            json.dumps(candidate.coverage_hint.model_dump(mode="json"))
            if candidate.coverage_hint
            else None
        )
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into review_research_session_candidates
                    (review_id, session_id, pmid, rank, title, status, decision_reason,
                     coverage_hint, source_id, error, updated_at)
                values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, now())
                on conflict (review_id, session_id, pmid) do update set
                    rank = excluded.rank,
                    title = excluded.title,
                    status = excluded.status,
                    decision_reason = excluded.decision_reason,
                    coverage_hint = excluded.coverage_hint,
                    source_id = excluded.source_id,
                    error = excluded.error,
                    updated_at = now()
                """,
                review_id,
                session_id,
                candidate.pmid,
                candidate.rank,
                candidate.title,
                candidate.status,
                candidate.decision_reason,
                coverage_hint,
                candidate.source_id,
                candidate.error,
            )

    async def get_research_session(
        self, review_id: str, session_id: str
    ) -> ResearchSessionManifest | None:
        async with self._acquire() as connection:
            session = await connection.fetchrow(
                """
                select review_id, session_id, query, status,
                       created_at::text as created_at, updated_at::text as updated_at
                from review_research_sessions
                where review_id = $1 and session_id = $2
                """,
                review_id,
                session_id,
            )
            if session is None:
                return None
            rows = await connection.fetch(
                """
                select pmid, rank, title, status, decision_reason, coverage_hint,
                       source_id, error
                from review_research_session_candidates
                where review_id = $1 and session_id = $2
                order by rank nulls last, pmid
                """,
                review_id,
                session_id,
            )
        candidates = [_research_session_candidate_from_row(row) for row in rows]
        return ResearchSessionManifest(
            review_id=session["review_id"],
            session_id=session["session_id"],
            query=session["query"],
            status=session["status"],
            candidates=candidates,
            candidate_count=len(candidates),
            queued_count=sum(1 for item in candidates if item.status == "queued"),
            skipped_count=sum(1 for item in candidates if item.status == "skipped"),
            coverage_summary=_coverage_summary(candidates),
            created_at=session["created_at"],
            updated_at=session["updated_at"],
        )

    async def list_research_sessions(self, review_id: str) -> list[ResearchSessionManifest]:
        return await review_research_sessions.list_research_sessions_for_review(
            self._acquire, review_id
        )

    async def list_research_sessions_global(self, limit: int = 20) -> list[ResearchSessionManifest]:
        return await review_research_sessions.list_research_sessions_global(
            self._acquire, limit=limit
        )

    async def find_research_sessions_by_session_id(
        self, session_id: str
    ) -> list[ResearchSessionManifest]:
        return await review_research_sessions.find_research_sessions_by_session_id(
            self._acquire, session_id
        )

    async def upsert_evidence_certainty(
        self,
        review_id: str,
        request: UpsertEvidenceCertaintyRequest,
        *,
        certainty_id: str | None = None,
    ) -> EvidenceCertaintyRecord:
        record_id = certainty_id or str(uuid4())
        unresolved_passage_ids = await self._unresolved_passage_ids(
            review_id,
            request.passage_ids,
            validate=request.validate_passages,
        )
        async with self._acquire() as connection:
            await connection.execute(
                """
                insert into reviews (review_id)
                values ($1)
                on conflict (review_id) do update
                set updated_at = now()
                """,
                review_id,
            )
            row = await connection.fetchrow(
                """
                insert into review_evidence_certainty (
                    certainty_id,
                    review_id,
                    outcome,
                    question,
                    study_design,
                    risk_of_bias_notes,
                    inconsistency_notes,
                    indirectness_notes,
                    imprecision_notes,
                    publication_bias_notes,
                    overall_certainty,
                    certainty_rationale,
                    passage_ids,
                    unresolved_passage_ids,
                    created_by
                )
                values (
                    $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $14, $15
                )
                on conflict (certainty_id) do update
                set outcome = excluded.outcome,
                    question = excluded.question,
                    study_design = excluded.study_design,
                    risk_of_bias_notes = excluded.risk_of_bias_notes,
                    inconsistency_notes = excluded.inconsistency_notes,
                    indirectness_notes = excluded.indirectness_notes,
                    imprecision_notes = excluded.imprecision_notes,
                    publication_bias_notes = excluded.publication_bias_notes,
                    overall_certainty = excluded.overall_certainty,
                    certainty_rationale = excluded.certainty_rationale,
                    passage_ids = excluded.passage_ids,
                    unresolved_passage_ids = excluded.unresolved_passage_ids,
                    created_by = excluded.created_by,
                    updated_at = now()
                returning *
                """,
                record_id,
                review_id,
                request.outcome,
                request.question,
                request.study_design,
                request.risk_of_bias_notes,
                request.inconsistency_notes,
                request.indirectness_notes,
                request.imprecision_notes,
                request.publication_bias_notes,
                request.overall_certainty,
                request.certainty_rationale,
                request.passage_ids,
                unresolved_passage_ids,
                request.created_by,
            )
            await self._touch_review_on_connection(connection, review_id)
        return _evidence_certainty_from_row(row)

    async def list_evidence_certainty(self, review_id: str) -> list[EvidenceCertaintyRecord]:
        async with self._acquire() as connection:
            rows = await connection.fetch(
                """
                select *
                from review_evidence_certainty
                where review_id = $1
                order by updated_at desc, certainty_id asc
                """,
                review_id,
            )
        return [_evidence_certainty_from_row(row) for row in rows]

    async def get_evidence_certainty(
        self,
        review_id: str,
        certainty_id: str,
    ) -> EvidenceCertaintyRecord | None:
        async with self._acquire() as connection:
            row = await connection.fetchrow(
                """
                select *
                from review_evidence_certainty
                where review_id = $1 and certainty_id = $2::uuid
                """,
                review_id,
                certainty_id,
            )
        return _evidence_certainty_from_row(row) if row is not None else None

    async def _unresolved_passage_ids(
        self,
        review_id: str,
        passage_ids: list[str],
        *,
        validate: bool,
    ) -> list[str]:
        if not validate or not passage_ids:
            return []
        existing = await self.get_passages_by_id(review_id, passage_ids)
        existing_ids = {passage.passage_id for passage in existing}
        return [passage_id for passage_id in passage_ids if passage_id not in existing_ids]

    async def _preparation_status_on_connection(
        self,
        connection: Any,
        review_id: str,
        *,
        session_id: str | None = None,
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
              and (
                  $2::text is null
                  or exists (
                      select 1
                      from review_session_sources rss
                      where rss.review_id = review_preparation_jobs.review_id
                        and rss.session_id = $2
                        and rss.source_id = review_preparation_jobs.source_id
                  )
              )
            """,
            review_id,
            session_id,
        )
        return _preparation_status_from_row(row)

    async def _touch_review_on_connection(self, connection: Any, review_id: str) -> None:
        await connection.execute(
            """
            update reviews
            set updated_at = now()
            where review_id = $1
            """,
            review_id,
        )

    @staticmethod
    def _review_inventory_sql(*, filtered: bool) -> str:
        if filtered:
            return PostgresReviewReragRepository._REVIEW_INVENTORY_FILTERED_SQL
        return PostgresReviewReragRepository._REVIEW_INVENTORY_SQL

    _REVIEW_INVENTORY_SQL = """
            with job_stats as (
                select
                    review_id,
                    coalesce(sum((status = 'queued')::int), 0)::int as queued,
                    coalesce(sum((status = 'running')::int), 0)::int as running,
                    coalesce(sum((status = 'complete')::int), 0)::int as complete,
                    coalesce(sum((status = 'partial')::int), 0)::int as partial,
                    coalesce(sum((status = 'failed')::int), 0)::int as failed,
                    count(distinct source_id)::int as source_count
                from review_preparation_jobs
                group by review_id
            ),
            passage_stats as (
                select
                    review_id,
                    (count(distinct pmid) filter (where pmid is not null))::int as pmid_count,
                    count(distinct passage_id)::int as passage_count,
                    coalesce(sum(length(text)), 0)::int as approximate_bytes
                from review_passages
                group by review_id
            ),
            failed_stats as (
                select review_id, count(distinct source_id)::int as failed_source_count
                from review_preparation_jobs
                where status = 'failed'
                group by review_id
            )
            select
                r.review_id,
                r.created_at,
                r.updated_at,
                coalesce(j.queued, 0)::int as queued,
                coalesce(j.running, 0)::int as running,
                coalesce(j.complete, 0)::int as complete,
                coalesce(j.partial, 0)::int as partial,
                coalesce(j.failed, 0)::int as failed,
                coalesce(p.pmid_count, 0)::int as pmid_count,
                coalesce(j.source_count, 0)::int as source_count,
                coalesce(p.passage_count, 0)::int as passage_count,
                coalesce(f.failed_source_count, 0)::int as failed_source_count,
                coalesce(p.approximate_bytes, 0)::int as approximate_bytes
            from reviews r
            left join job_stats j on j.review_id = r.review_id
            left join passage_stats p on p.review_id = r.review_id
            left join failed_stats f on f.review_id = r.review_id
            order by r.updated_at desc, r.review_id asc
            limit $1 offset $2
            """

    _REVIEW_INVENTORY_FILTERED_SQL = """
            with job_stats as (
                select
                    review_id,
                    coalesce(sum((status = 'queued')::int), 0)::int as queued,
                    coalesce(sum((status = 'running')::int), 0)::int as running,
                    coalesce(sum((status = 'complete')::int), 0)::int as complete,
                    coalesce(sum((status = 'partial')::int), 0)::int as partial,
                    coalesce(sum((status = 'failed')::int), 0)::int as failed,
                    count(distinct source_id)::int as source_count
                from review_preparation_jobs
                group by review_id
            ),
            passage_stats as (
                select
                    review_id,
                    (count(distinct pmid) filter (where pmid is not null))::int as pmid_count,
                    count(distinct passage_id)::int as passage_count,
                    coalesce(sum(length(text)), 0)::int as approximate_bytes
                from review_passages
                group by review_id
            ),
            failed_stats as (
                select review_id, count(distinct source_id)::int as failed_source_count
                from review_preparation_jobs
                where status = 'failed'
                group by review_id
            )
            select
                r.review_id,
                r.created_at,
                r.updated_at,
                coalesce(j.queued, 0)::int as queued,
                coalesce(j.running, 0)::int as running,
                coalesce(j.complete, 0)::int as complete,
                coalesce(j.partial, 0)::int as partial,
                coalesce(j.failed, 0)::int as failed,
                coalesce(p.pmid_count, 0)::int as pmid_count,
                coalesce(j.source_count, 0)::int as source_count,
                coalesce(p.passage_count, 0)::int as passage_count,
                coalesce(f.failed_source_count, 0)::int as failed_source_count,
                coalesce(p.approximate_bytes, 0)::int as approximate_bytes
            from reviews r
            left join job_stats j on j.review_id = r.review_id
            left join passage_stats p on p.review_id = r.review_id
            left join failed_stats f on f.review_id = r.review_id
            where r.review_id = $3
            order by r.updated_at desc, r.review_id asc
            limit $1 offset $2
            """


def _coverage_summary(candidates: list[ResearchSessionCandidate]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for candidate in candidates:
        coverage = (
            candidate.coverage_hint.expected_coverage
            if candidate.coverage_hint is not None
            else "unknown"
        )
        summary[coverage] = summary.get(coverage, 0) + 1
    return summary
