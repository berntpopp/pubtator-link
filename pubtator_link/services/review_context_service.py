"""Service for retrieving review-scoped context passages."""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote, urlencode

from pubtator_link.models.review_rerag import (
    BudgetSource,
    ContextPack,
    ContextPassage,
    EmbeddingRerankDiagnostics,
    FailedSourceSummary,
    InspectReviewIndexRequest,
    InspectReviewIndexResponse,
    NextContextOption,
    PreparationStatus,
    RetrieveReviewBatchDiagnostics,
    RetrieveReviewContextBatchRequest,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewAuditTrailResponse,
    ReviewIndexTotals,
    ReviewPassageLookupResponse,
    ReviewPassageRow,
    ReviewSourceSummary,
    SampleSectionPolicy,
    SourceCoverage,
)
from pubtator_link.services.provenance import corpus_snapshot_date, stable_cache_key
from pubtator_link.services.publication_metadata import (
    PublicationMetadataLookup,
    lookup_metadata_batched,
)
from pubtator_link.services.review_context.audit_trail import (
    audit_trail_response,
    latest_audit_passage_ids,
)
from pubtator_link.services.review_context.batch_budgeting import merge_batch_context
from pubtator_link.services.review_context.budgets import (
    REVIEW_BATCH_DEFAULT_MAX_CHARS,
    REVIEW_BATCH_DEFAULT_MAX_RESPONSE_CHARS,
    REVIEW_BATCH_MAX_CHARS_CAP,
    REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP,
    resolve_batch_budget_args,
)
from pubtator_link.services.review_context.diagnostics import (
    build_diagnostics,
    query_summary,
    recovery_from_query_summary,
)
from pubtator_link.services.review_context.embedding_rerank import rerank_with_embeddings
from pubtator_link.services.review_context.embeddings import (
    EmbeddingProvider,
    text_hash,
)
from pubtator_link.services.review_context.packing import (
    context_budget,
    context_passage_from_row,
    pack_passages,
    pack_totals,
)
from pubtator_link.services.review_context.pagination import (
    InspectReviewIndexCursor,
    decode_inspect_review_index_cursor,
    encode_inspect_review_index_cursor,
    inspect_review_index_scope_hash,
)
from pubtator_link.services.review_context.quotes import quotes_from_passages
from pubtator_link.services.review_context.ranking import (
    SOURCE_COVERAGE_SCARCITY_PRIORITY,
    rerank_key,
)
from pubtator_link.services.review_state import index_snapshot_date


class ReviewContextRepository(Protocol):
    """Repository interface needed by ReviewContextService."""

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
        """Return candidate passages for a review-scoped retrieval request."""

    async def preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus | dict[str, int]:
        """Return preparation status counts for a review."""

    async def research_session_exists(self, review_id: str, session_id: str) -> bool:
        """Return whether a research session exists."""

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
        """Return index source summaries for a review."""

    async def list_review_failed_sources(
        self,
        review_id: str,
        *,
        session_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[FailedSourceSummary]:
        """Return failed source summaries for a review."""

    async def review_index_totals(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewIndexTotals:
        """Return aggregate index totals for a review."""

    async def available_sections(
        self, review_id: str, *, session_id: str | None = None
    ) -> list[str]:
        """Return indexed section names for diagnostics."""

    async def indexed_pmids(self, review_id: str, *, session_id: str | None = None) -> list[str]:
        """Return indexed PMIDs for diagnostics."""

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

    async def get_passage_embeddings(
        self,
        review_id: str,
        passage_ids: Sequence[str],
        *,
        model_name: str,
        passage_text_hashes: dict[str, str] | None = None,
    ) -> dict[str, list[float]]:
        """Return stored passage embeddings keyed by passage ID."""


@dataclass(frozen=True)
class ReviewRetrievalSnapshot:
    preparation_status: PreparationStatus
    prepared_pmids: list[str]
    still_preparing_pmids: list[str]
    failed_pmids: list[str]
    indexed_pmids: list[str]
    available_sections: list[str]
    source_summaries: list[ReviewSourceSummary]
    failed_sources: list[FailedSourceSummary]


class ReviewContextService:
    """Retrieve, rerank, and pack review-scoped context passages."""

    def __init__(
        self,
        repository: ReviewContextRepository,
        *,
        metadata_service: PublicationMetadataLookup | None = None,
        retrieval_concurrency: int = 4,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_rerank_enabled: bool = False,
        embedding_model: str = "BAAI/bge-small-en-v1.5",
        embedding_dim: int = 384,
        embedding_top_k: int = 50,
        embedding_rrf_k: int = 60,
        logger: logging.Logger | None = None,
    ) -> None:
        self.repository = repository
        self.metadata_service = metadata_service
        self.retrieval_concurrency = retrieval_concurrency
        self.logger = logger or logging.getLogger(__name__)
        self.embedding_provider = embedding_provider
        self.embedding_rerank_enabled = embedding_rerank_enabled
        self.embedding_model = embedding_model
        self.embedding_dim = embedding_dim
        self.embedding_top_k = embedding_top_k
        self.embedding_rrf_k = embedding_rrf_k

    async def retrieve_context(
        self,
        review_id: str,
        request: RetrieveReviewContextRequest,
    ) -> RetrieveReviewContextResponse:
        """Build a citable context pack for a review question."""
        await self._ensure_session_exists(review_id, request.session_id)
        candidates = await self.repository.search_passages(
            review_id,
            request.question,
            entity_ids=request.entity_ids,
            pmids=request.pmids,
            sections=request.sections,
            session_id=request.session_id,
            limit=self.embedding_top_k if self.embedding_rerank_enabled else 80,
        )
        return await self._assemble_retrieval_response(
            review_id=review_id,
            request=request,
            candidates=candidates,
        )

    async def _assemble_retrieval_response(
        self,
        *,
        review_id: str,
        request: RetrieveReviewContextRequest,
        candidates: Sequence[ReviewPassageRow],
        snapshot: ReviewRetrievalSnapshot | None = None,
    ) -> RetrieveReviewContextResponse:
        sorted_candidates, embedding_diagnostics = await self._rank_candidates(
            review_id=review_id,
            query=request.question,
            candidates=candidates,
            section_policy=request.section_policy,
        )
        packed = pack_passages(sorted_candidates, request)
        selected = packed.selected
        dropped = packed.dropped
        passages = [
            context_passage_from_row(index=index, row=row, request=request)
            for index, row in enumerate(selected, start=1)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        text_chars, estimated_tokens = pack_totals(passages)
        budget = context_budget(
            max_chars=request.max_chars,
            text_chars=text_chars,
            dropped_count=len(dropped),
        )
        diagnostics = None
        if not passages or request.include_diagnostics:
            diagnostics = await build_diagnostics(
                repository=self.repository,
                review_id=review_id,
                request=request,
                candidate_count=len(candidates),
                selected_count=len(selected),
                available_sections=snapshot.available_sections if snapshot is not None else None,
                indexed_pmids=snapshot.indexed_pmids if snapshot is not None else None,
                failed_sources=snapshot.failed_sources if snapshot is not None else None,
            )
            diagnostics.embedding_rerank = embedding_diagnostics
        if snapshot is None:
            prepared_pmids, still_preparing_pmids, failed_pmids = await self._preparation_pmids(
                review_id,
                session_id=request.session_id,
            )
            preparation_status = await self._preparation_status(
                review_id, session_id=request.session_id
            )
        else:
            prepared_pmids = snapshot.prepared_pmids
            still_preparing_pmids = snapshot.still_preparing_pmids
            failed_pmids = snapshot.failed_pmids
            preparation_status = snapshot.preparation_status
        response = RetrieveReviewContextResponse(
            review_id=review_id,
            context_pack=ContextPack(
                question=request.question,
                passages=passages,
                citation_map=citation_map,
                total_chars=text_chars,
                estimated_tokens=estimated_tokens,
                budget=budget,
                dropped=dropped,
            ),
            preparation_status=preparation_status,
            index_snapshot_date=index_snapshot_date(),
            diagnostics=diagnostics,
            prepared_pmids=prepared_pmids,
            still_preparing_pmids=still_preparing_pmids,
            failed_pmids=failed_pmids,
        )
        single_summary = query_summary(
            query=request.question,
            result=response,
            returned_count=len(passages),
            dropped_count=len(dropped),
        )
        recovery = recovery_from_query_summary(single_summary)
        if recovery is None:
            return response
        return response.model_copy(
            update={
                "recovery": recovery,
                "context_pack": response.context_pack.model_copy(update={"recovery": recovery}),
            }
        )

    async def retrieve_context_batch(
        self,
        review_id: str,
        request: RetrieveReviewContextBatchRequest,
    ) -> RetrieveReviewContextBatchResponse:
        """Retrieve multiple query variants and merge selected passages."""
        started = time.monotonic()
        await self._ensure_session_exists(review_id, request.session_id)
        if (
            isinstance(request.max_response_chars, str)
            and request.max_response_chars.lower() == "auto"
        ):
            resolved_budgets = resolve_batch_budget_args(
                max_total_passages=request.max_total_passages,
                max_chars_per_passage=request.max_chars_per_passage,
                max_chars=request.max_chars,
                max_response_chars=request.max_response_chars,
                verbosity=request.verbosity,
            )
            request = request.model_copy(
                update={
                    "max_chars": resolved_budgets.max_chars,
                    "max_response_chars": resolved_budgets.max_response_chars,
                    "budget_source": resolved_budgets.budget_source,
                }
            )
        budget_source = _effective_batch_budget_source(request)
        if budget_source != request.budget_source:
            request = request.model_copy(update={"budget_source": budget_source})
        snapshot = await self._review_retrieval_snapshot(review_id, session_id=request.session_id)
        results: list[RetrieveReviewContextResponse] = []
        query_results: list[RetrieveReviewContextResponse] = []

        semaphore = asyncio.Semaphore(self.retrieval_concurrency)

        async def retrieve_one(
            query_index: int,
            query: str,
        ) -> tuple[int, RetrieveReviewContextResponse]:
            async with semaphore:
                candidates = await self.repository.search_passages(
                    review_id,
                    query,
                    entity_ids=request.entity_ids,
                    pmids=request.pmids,
                    sections=request.sections,
                    session_id=request.session_id,
                    limit=self.embedding_top_k if self.embedding_rerank_enabled else 80,
                )
                result = await self._assemble_retrieval_response(
                    review_id=review_id,
                    request=RetrieveReviewContextRequest(
                        question=query,
                        session_id=request.session_id,
                        pmids=request.pmids,
                        entity_ids=request.entity_ids,
                        sections=request.sections,
                        max_passages=request.max_passages_per_query,
                        max_chars=request.max_chars,
                        include_diagnostics=request.include_diagnostics
                        or request.response_mode == "diagnostics",
                        include_tables=request.include_tables,
                        include_references=request.include_references,
                        table_mode=request.table_mode,
                        section_policy=request.section_policy,
                        allow_truncated_passages=request.allow_truncated_passages,
                        max_chars_per_passage=request.max_chars_per_passage,
                    ),
                    candidates=candidates,
                    snapshot=snapshot,
                )
                return query_index, result

        indexed_results: list[tuple[int, RetrieveReviewContextResponse]] = []
        query_items = list(enumerate(request.queries))
        chunk_size = max(1, self.retrieval_concurrency)
        for offset in range(0, len(query_items), chunk_size):
            chunk = query_items[offset : offset + chunk_size]
            indexed_results.extend(
                await asyncio.gather(*(retrieve_one(index, query) for index, query in chunk))
            )
        for _query_index, result in sorted(indexed_results, key=lambda item: item[0]):
            query_results.append(result)
            if request.response_mode == "full":
                results.append(result)

        query_phase_ms = round((time.monotonic() - started) * 1000, 2)
        coverage_by_source = {}
        if request.budget_strategy != "query_fair":
            coverage_by_source = _source_coverage_by_key(snapshot.source_summaries)
        merge_request = (
            request.model_copy(update={"response_mode": "compact"}) if request.dry_run else request
        )
        merged = merge_batch_context(
            request=merge_request,
            query_results=query_results,
            coverage_by_source=coverage_by_source,
        )
        merge_phase_ms = round((time.monotonic() - started) * 1000 - query_phase_ms, 2)
        next_context_options = _next_context_options(
            review_id,
            merged.passages,
            session_id=request.session_id,
        )
        include_batch_diagnostics = (
            request.include_diagnostics or request.response_mode == "diagnostics"
        )
        diagnostics = (
            RetrieveReviewBatchDiagnostics(
                query_summaries=merged.query_summaries,
                source_budget_summaries=merged.source_budget_summaries,
                pmid_status_summary=merged.pmid_status_summary,
                dropped_summary=merged.dropped_summary,
            )
            if include_batch_diagnostics
            else None
        )
        recovery = next(
            (
                hint
                for hint in (
                    recovery_from_query_summary(summary) for summary in merged.query_summaries
                )
                if hint is not None
            ),
            None,
        )
        prioritized_count = sum(1 for summary in merged.pmid_status_summary if summary.prioritized)
        self.logger.info(
            "review_context_batch_retrieved",
            extra={
                "review_id": review_id,
                "session_id": request.session_id,
                "query_count": len(request.queries),
                "response_mode": request.response_mode,
                "budget_strategy": request.budget_strategy,
                "dry_run": request.dry_run,
                "query_phase_ms": query_phase_ms,
                "merge_phase_ms": merge_phase_ms,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "returned_passage_count": len(merged.passages),
                "dropped_passage_count": merged.dropped_summary.total_dropped,
                "text_chars": merged.text_chars,
                "estimated_tokens": merged.estimated_tokens,
                "next_context_option_count": len(next_context_options),
                "prioritized_pmid_count": prioritized_count,
                "explicit_prioritize_pmid_count": len(request.prioritize_pmids),
            },
        )
        if request.dry_run:
            dry_run_budget = context_budget(
                max_chars=request.max_chars,
                text_chars=0,
                dropped_count=0,
            ).model_copy(update={"budget_source": request.budget_source})
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode="diagnostics",
                include_diagnostics=include_batch_diagnostics,
                diagnostics=diagnostics,
                results=[],
                query_summaries=merged.query_summaries,
                source_budget_summaries=merged.source_budget_summaries,
                pmid_status_summary=merged.pmid_status_summary,
                merged_context_pack=ContextPack(
                    question="\n".join(request.queries),
                    passages=[],
                    citation_map={},
                    total_chars=0,
                    estimated_tokens=0,
                    budget=dry_run_budget,
                    dropped=[],
                    dropped_summary=merged.dropped_summary,
                    recovery=recovery,
                ),
                preparation_status=snapshot.preparation_status,
                budget=dry_run_budget,
                budget_source=request.budget_source,
                cache_key=_review_batch_cache_key(review_id, request),
                corpus_snapshot_date=corpus_snapshot_date(),
                index_snapshot_date=index_snapshot_date(),
                source_versions={"review_index": "live"},
                prepared_pmids=snapshot.prepared_pmids,
                still_preparing_pmids=snapshot.still_preparing_pmids,
                failed_pmids=snapshot.failed_pmids,
                recovery=recovery,
                next_context_options=next_context_options,
            )
        record_audit_event = getattr(self.repository, "record_review_audit_event", None)
        if record_audit_event is not None:
            await record_audit_event(
                review_id,
                "retrieval_run",
                {
                    "queries": request.queries,
                    "passage_ids": [passage.passage_id for passage in merged.passages],
                },
            )
        citation_map = {passage.citation_key: passage.passage_id for passage in merged.passages}
        budget = context_budget(
            max_chars=request.max_chars,
            text_chars=merged.budget_text_chars,
            dropped_count=len(merged.dropped),
        ).model_copy(update={"budget_source": request.budget_source})
        quotes = quotes_from_passages(merged.passages) if request.response_mode == "quotes" else []
        merged_passages = [] if request.response_mode == "quotes" else merged.passages
        stable_citation_map = {
            passage.stable_citation_key: passage.passage_id
            for passage in merged.passages
            if passage.stable_citation_key is not None
        }
        return RetrieveReviewContextBatchResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            include_diagnostics=include_batch_diagnostics,
            diagnostics=diagnostics,
            results=results,
            query_summaries=merged.query_summaries,
            source_budget_summaries=merged.source_budget_summaries,
            pmid_status_summary=merged.pmid_status_summary,
            merged_context_pack=ContextPack(
                question="\n".join(request.queries),
                passages=merged_passages,
                citation_map=citation_map,
                stable_citation_map=stable_citation_map,
                total_chars=merged.text_chars,
                estimated_tokens=merged.estimated_tokens,
                budget=budget,
                dropped=merged.dropped,
                dropped_summary=merged.dropped_summary,
                recovery=recovery,
            ),
            preparation_status=snapshot.preparation_status,
            budget=budget,
            budget_source=request.budget_source,
            cache_key=_review_batch_cache_key(review_id, request),
            corpus_snapshot_date=corpus_snapshot_date(),
            index_snapshot_date=index_snapshot_date(),
            source_versions={"review_index": "live"},
            prepared_pmids=snapshot.prepared_pmids,
            still_preparing_pmids=snapshot.still_preparing_pmids,
            failed_pmids=snapshot.failed_pmids,
            recovery=recovery,
            quotes=quotes,
            next_context_options=next_context_options,
        )

    async def _rank_candidates(
        self,
        *,
        review_id: str,
        query: str,
        candidates: Sequence[ReviewPassageRow],
        section_policy: SampleSectionPolicy,
    ) -> tuple[list[ReviewPassageRow], EmbeddingRerankDiagnostics | None]:
        started = time.monotonic()
        lexical_candidates = sorted(
            candidates,
            key=lambda row: rerank_key(row, section_policy=section_policy),
        )
        if not self.embedding_rerank_enabled:
            return lexical_candidates, None

        diagnostics = EmbeddingRerankDiagnostics(
            enabled=True,
            model_name=self.embedding_model,
            embedding_dim=self.embedding_dim,
            candidate_count=len(candidates),
        )
        if not candidates:
            diagnostics.fallback_reason = "no_candidates"
            self._log_embedding_rerank_fallback(review_id, diagnostics, started)
            return lexical_candidates, diagnostics
        if self.embedding_provider is None:
            diagnostics.fallback_reason = "provider_unavailable"
            self._log_embedding_rerank_fallback(review_id, diagnostics, started)
            return lexical_candidates, diagnostics

        passage_ids = [row.passage_id for row in lexical_candidates]
        passage_hashes = {row.passage_id: text_hash(row.text) for row in lexical_candidates}
        try:
            embeddings = await self.repository.get_passage_embeddings(
                review_id,
                passage_ids,
                model_name=self.embedding_model,
                passage_text_hashes=passage_hashes,
            )
        except Exception:
            diagnostics.fallback_reason = "embedding_fetch_failed"
            self._log_embedding_rerank_fallback(review_id, diagnostics, started)
            return lexical_candidates, diagnostics

        diagnostics.embedded_candidate_count = len(embeddings)
        diagnostics.missing_embedding_count = len(candidates) - len(embeddings)
        if not embeddings:
            diagnostics.fallback_reason = "missing_embeddings"
            self._log_embedding_rerank_fallback(review_id, diagnostics, started)
            return lexical_candidates, diagnostics

        try:
            query_embedding = await self.embedding_provider.embed_query(query)
        except Exception:
            diagnostics.fallback_reason = "query_embedding_failed"
            self._log_embedding_rerank_fallback(review_id, diagnostics, started)
            return lexical_candidates, diagnostics

        dense_scores = {
            passage_id: _cosine_similarity(query_embedding, embedding)
            for passage_id, embedding in embeddings.items()
        }
        reranked, rerank_diagnostics = rerank_with_embeddings(
            lexical_candidates,
            dense_scores=dense_scores,
            rrf_k=self.embedding_rrf_k,
        )
        rerank_diagnostics.model_name = self.embedding_model
        rerank_diagnostics.embedding_dim = self.embedding_dim
        self.logger.info(
            "review_embedding_rerank_completed",
            extra={
                "review_id": review_id,
                "model_name": self.embedding_model,
                "embedding_dim": self.embedding_dim,
                "candidate_count": rerank_diagnostics.candidate_count,
                "embedded_candidate_count": rerank_diagnostics.embedded_candidate_count,
                "missing_embedding_count": rerank_diagnostics.missing_embedding_count,
                "active": rerank_diagnostics.active,
                "strategy": rerank_diagnostics.strategy,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return reranked, rerank_diagnostics

    def _log_embedding_rerank_fallback(
        self,
        review_id: str,
        diagnostics: EmbeddingRerankDiagnostics,
        started: float,
    ) -> None:
        self.logger.info(
            "review_embedding_rerank_fallback",
            extra={
                "review_id": review_id,
                "model_name": diagnostics.model_name,
                "embedding_dim": diagnostics.embedding_dim,
                "candidate_count": diagnostics.candidate_count,
                "embedded_candidate_count": diagnostics.embedded_candidate_count,
                "missing_embedding_count": diagnostics.missing_embedding_count,
                "fallback_reason": diagnostics.fallback_reason,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )

    async def inspect_review_index(
        self,
        review_id: str,
        request: InspectReviewIndexRequest,
    ) -> InspectReviewIndexResponse:
        """Inspect prepared sources, aggregate counts, and failed sources."""
        await self._ensure_session_exists(review_id, request.session_id)
        preparation_status = await self._preparation_status(
            review_id, session_id=request.session_id
        )
        scope_hash = inspect_review_index_scope_hash(
            review_id=review_id,
            session_id=request.session_id,
            pmids=request.pmids,
        )
        source_offset = 0
        failed_source_offset = 0
        if request.cursor:
            cursor = decode_inspect_review_index_cursor(
                request.cursor,
                expected_scope_hash=scope_hash,
            )
            source_offset = cursor.source_offset
            failed_source_offset = cursor.failed_source_offset

        totals = await self.repository.review_index_totals(review_id, session_id=request.session_id)
        sources = (
            []
            if request.limit is not None and source_offset >= totals.source_count
            else await self.repository.list_review_sources(
                review_id,
                request.pmids,
                include_passage_samples=request.include_passage_samples,
                sample_per_pmid=request.sample_per_pmid,
                min_sample_chars=request.min_sample_chars,
                sample_section_policy=request.sample_section_policy,
                session_id=request.session_id,
                limit=request.limit,
                offset=source_offset,
            )
        )
        failed_sources = (
            []
            if request.limit is not None and failed_source_offset >= totals.failed_source_count
            else await self.repository.list_review_failed_sources(
                review_id,
                session_id=request.session_id,
                limit=request.limit,
                offset=failed_source_offset,
            )
        )
        if request.include_metadata and self.metadata_service is not None:
            await self._attach_source_metadata(sources, request.metadata)
        next_source_offset = source_offset + len(sources)
        next_failed_source_offset = failed_source_offset + len(failed_sources)
        remaining_sources: int | None
        remaining_failed_sources: int | None
        if request.pmids:
            # `sources`/`failed_sources` are filtered by request.pmids, but `totals` is GLOBAL
            # (session-scoped at most). Computing remaining/cursor from the global count
            # over-reports remaining and re-emits a cursor after an empty filtered page -- which
            # loops. Under a PMID filter, bound pagination by page fullness (a short/empty page is
            # the end) and report remaining as unknown rather than a global number.
            more_sources = request.limit is not None and len(sources) == request.limit
            more_failed = request.limit is not None and len(failed_sources) == request.limit
            remaining_sources = None
            remaining_failed_sources = None
        else:
            remaining_sources = max(0, totals.source_count - next_source_offset)
            remaining_failed_sources = max(
                0, totals.failed_source_count - next_failed_source_offset
            )
            more_sources = remaining_sources > 0
            more_failed = remaining_failed_sources > 0
        next_cursor = None
        if request.limit is not None and (more_sources or more_failed):
            next_cursor = encode_inspect_review_index_cursor(
                InspectReviewIndexCursor(
                    scope_hash=scope_hash,
                    source_offset=next_source_offset,
                    failed_source_offset=next_failed_source_offset,
                )
            )
        omitted_counts = {
            key: value
            for key, value in {
                "sources": remaining_sources,
                "failed_sources": remaining_failed_sources,
            }.items()
            if request.limit is not None and isinstance(value, int) and value > 0
        }
        coverage_summary = {"full_text": 0, "abstract_only": 0, "title_only": 0, "unknown": 0}
        for source in sources:
            coverage_summary[source.coverage] = coverage_summary.get(source.coverage, 0) + 1
        return InspectReviewIndexResponse(
            review_id=review_id,
            response_mode=request.response_mode,
            preparation_status=preparation_status,
            sources=sources,
            totals=totals,
            failed_sources=failed_sources,
            coverage_summary=coverage_summary,
            index_snapshot_date=index_snapshot_date(),
            next_cursor=next_cursor,
            page_source_count=len(sources),
            page_failed_source_count=len(failed_sources),
            omitted_counts=omitted_counts,
        )

    async def _attach_source_metadata(
        self,
        sources: list[ReviewSourceSummary],
        metadata_mode: str,
    ) -> None:
        pmids = list(dict.fromkeys(source.pmid for source in sources if source.pmid))
        metadata_service = self.metadata_service
        if not pmids or metadata_service is None:
            return
        response = await lookup_metadata_batched(
            metadata_service,
            pmids,
            include_mesh=metadata_mode == "full",
            include_publication_types=True,
            include_citations="both" if metadata_mode == "full" else "none",
            include_coverage=True,
        )
        metadata_by_pmid = {item.pmid: item for item in getattr(response, "metadata", [])}
        for source in sources:
            if source.pmid in metadata_by_pmid:
                source.citation_metadata = metadata_by_pmid[source.pmid]

    async def get_passages_by_id(
        self,
        *,
        review_id: str,
        passage_ids: list[str],
        session_id: str | None = None,
        max_chars_per_passage: int = 2200,
    ) -> ReviewPassageLookupResponse:
        await self._ensure_session_exists(review_id, session_id)
        rows = await self.repository.get_passages_by_id(
            review_id, passage_ids, session_id=session_id
        )
        found_ids = {row.passage_id for row in rows}
        passages = self._context_passages_from_rows(
            rows,
            query=" ".join(passage_ids),
            max_chars_per_passage=max_chars_per_passage,
        )
        return ReviewPassageLookupResponse(
            review_id=review_id,
            passages=passages,
            not_found=[passage_id for passage_id in passage_ids if passage_id not in found_ids],
        )

    async def get_neighboring_passages(
        self,
        *,
        review_id: str,
        passage_id: str,
        before: int = 1,
        after: int = 1,
        same_section: bool = True,
        session_id: str | None = None,
        max_chars_per_passage: int = 2200,
    ) -> ReviewPassageLookupResponse:
        await self._ensure_session_exists(review_id, session_id)
        rows = await self.repository.neighboring_passages(
            review_id,
            passage_id=passage_id,
            before=before,
            after=after,
            same_section=same_section,
            session_id=session_id,
        )
        passages = self._context_passages_from_rows(
            rows,
            query=passage_id,
            max_chars_per_passage=max_chars_per_passage,
        )
        return ReviewPassageLookupResponse(
            review_id=review_id,
            passages=passages,
            not_found=[] if rows else [passage_id],
        )

    async def get_audit_trail(
        self,
        *,
        review_id: str,
        passage_ids: list[str] | None = None,
        session_id: str | None = None,
        max_chars_per_passage: int = 500,
    ) -> ReviewAuditTrailResponse:
        await self._ensure_session_exists(review_id, session_id)
        selected_passage_ids = passage_ids or await latest_audit_passage_ids(
            self.repository, review_id=review_id, session_id=session_id
        )
        lookup = await self.get_passages_by_id(
            review_id=review_id,
            passage_ids=selected_passage_ids,
            session_id=session_id,
            max_chars_per_passage=max_chars_per_passage,
        )
        return audit_trail_response(
            review_id=review_id,
            session_id=session_id,
            lookup=lookup,
            max_chars_per_passage=max_chars_per_passage,
        )

    def _context_passages_from_rows(
        self,
        rows: Sequence[ReviewPassageRow],
        *,
        query: str,
        max_chars_per_passage: int,
    ) -> list[ContextPassage]:
        request = RetrieveReviewContextRequest(
            question=query or "passage",
            max_passages=max(1, min(30, len(rows) or 1)),
            max_chars=max(500, min(30000, max_chars_per_passage * max(1, len(rows)))),
            max_chars_per_passage=max_chars_per_passage,
            allow_truncated_passages=True,
        )
        return [
            context_passage_from_row(index=index, row=row, request=request)
            for index, row in enumerate(rows, start=1)
        ]

    async def _source_coverage_by_key(
        self, review_id: str, *, session_id: str | None = None
    ) -> dict[str, SourceCoverage]:
        sources = await self.repository.list_review_sources(
            review_id,
            pmids=None,
            include_passage_samples=False,
            sample_per_pmid=0,
            session_id=session_id,
        )
        return _source_coverage_by_key(sources)

    async def _review_retrieval_snapshot(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewRetrievalSnapshot:
        (
            preparation_status,
            indexed_pmids,
            available_sections,
            source_summaries,
            failed_sources,
        ) = await asyncio.gather(
            self._preparation_status(review_id, session_id=session_id),
            self.repository.indexed_pmids(review_id, session_id=session_id),
            self.repository.available_sections(review_id, session_id=session_id),
            self.repository.list_review_sources(
                review_id,
                pmids=None,
                include_passage_samples=False,
                sample_per_pmid=0,
                session_id=session_id,
            ),
            self.repository.list_review_failed_sources(review_id, session_id=session_id),
        )
        prepared_pmids, still_preparing_pmids, failed_pmids = _preparation_pmids_from_sources(
            source_summaries,
            failed_sources,
        )
        return ReviewRetrievalSnapshot(
            preparation_status=preparation_status,
            prepared_pmids=prepared_pmids,
            still_preparing_pmids=still_preparing_pmids,
            failed_pmids=failed_pmids,
            indexed_pmids=indexed_pmids,
            available_sections=available_sections,
            source_summaries=source_summaries,
            failed_sources=failed_sources,
        )

    async def _preparation_status(
        self, review_id: str, *, session_id: str | None = None
    ) -> PreparationStatus:
        status = await self.repository.preparation_status(review_id, session_id=session_id)
        if isinstance(status, PreparationStatus):
            return status
        return PreparationStatus(**status)

    async def _ensure_session_exists(self, review_id: str, session_id: str | None) -> None:
        if session_id is None:
            return
        exists = await self.repository.research_session_exists(review_id, session_id)
        if not exists:
            raise ValueError("session_not_found")

    async def _preparation_pmids(
        self, review_id: str, *, session_id: str | None = None
    ) -> tuple[list[str], list[str], list[str]]:
        sources = await self.repository.list_review_sources(
            review_id,
            pmids=None,
            include_passage_samples=False,
            sample_per_pmid=0,
            session_id=session_id,
        )
        failed_sources = await self.repository.list_review_failed_sources(
            review_id, session_id=session_id
        )
        return _preparation_pmids_from_sources(sources, failed_sources)


def _preparation_pmids_from_sources(
    sources: Sequence[ReviewSourceSummary],
    failed_sources: Sequence[FailedSourceSummary],
) -> tuple[list[str], list[str], list[str]]:
    prepared = sorted(
        {
            source.pmid
            for source in sources
            if source.pmid is not None and source.job_status in {"complete", "partial"}
        }
    )
    still_preparing = sorted(
        {
            source.pmid
            for source in sources
            if source.pmid is not None and source.job_status in {"queued", "running"}
        }
    )
    failed = sorted({source.pmid for source in failed_sources if source.pmid is not None})
    return prepared, still_preparing, failed


def _source_coverage_by_key(
    sources: Sequence[ReviewSourceSummary],
) -> dict[str, SourceCoverage]:
    coverage_by_key: dict[str, SourceCoverage] = {}
    for source in sources:
        source_keys = [source.source_id]
        if source.pmid is not None:
            source_keys.append(source.pmid)
        for source_key in source_keys:
            existing = coverage_by_key.get(source_key)
            if existing is None or SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                source.coverage, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
            ) < SOURCE_COVERAGE_SCARCITY_PRIORITY.get(
                existing, SOURCE_COVERAGE_SCARCITY_PRIORITY["unknown"]
            ):
                coverage_by_key[source_key] = source.coverage
    return coverage_by_key


def _batch_auto_fit_budgets(
    *,
    max_total_passages: int,
    max_chars_per_passage: int,
) -> tuple[int, int, BudgetSource]:
    max_chars = min(
        REVIEW_BATCH_MAX_CHARS_CAP,
        max(REVIEW_BATCH_DEFAULT_MAX_CHARS, max_total_passages * max_chars_per_passage),
    )
    max_response_chars = min(
        REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP,
        max(REVIEW_BATCH_DEFAULT_MAX_RESPONSE_CHARS, max_chars * 2),
    )
    budget_source: BudgetSource = (
        "auto_fit" if max_chars != REVIEW_BATCH_DEFAULT_MAX_CHARS else "default"
    )
    return max_chars, max_response_chars, budget_source


def _effective_batch_budget_source(
    request: RetrieveReviewContextBatchRequest,
) -> BudgetSource:
    is_default_budget = (
        request.max_chars == REVIEW_BATCH_DEFAULT_MAX_CHARS
        and request.max_response_chars == REVIEW_BATCH_DEFAULT_MAX_RESPONSE_CHARS
    )
    if request.budget_source == "auto_fit":
        if is_default_budget:
            return "default"
        return "auto_fit"
    if request.budget_source == "caller":
        return "default" if is_default_budget else "caller"
    return "default" if is_default_budget else "caller"


def _review_batch_cache_key(
    review_id: str,
    request: RetrieveReviewContextBatchRequest,
) -> str:
    return stable_cache_key(
        "review_context_batch",
        {
            "review_id": review_id,
            "request": request.model_dump(mode="json"),
        },
    )


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    pairs: list[tuple[float, float]] = list(zip(left, right, strict=False))
    if not pairs:
        return 0.0
    dot: float = sum(left_value * right_value for left_value, right_value in pairs)
    left_norm: float = sum(left_value * left_value for left_value, _right_value in pairs) ** 0.5
    right_norm: float = sum(right_value * right_value for _left_value, right_value in pairs) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _next_context_options(
    review_id: str,
    passages: Sequence[ContextPassage],
    *,
    session_id: str | None = None,
) -> list[NextContextOption]:
    options: list[NextContextOption] = []
    for passage in passages:
        passage_resource = _review_resource_uri(
            review_id,
            f"passages/{passage.passage_id}",
            session_id=session_id,
        )
        neighboring_resource = _review_resource_uri(
            review_id,
            f"passages/{passage.passage_id}",
            query={"before": "1", "after": "1"},
            session_id=session_id,
        )
        audit_resource = _review_resource_uri(
            review_id,
            f"audit/{passage.passage_id}",
            session_id=session_id,
        )
        options.extend(
            [
                NextContextOption(
                    kind="passage",
                    resource=passage_resource,
                    reason="Load the exact prepared passage as resource context.",
                ),
                NextContextOption(
                    kind="neighboring_passages",
                    resource=neighboring_resource,
                    reason="Expand local context around a cited passage.",
                ),
                NextContextOption(
                    kind="audit",
                    resource=audit_resource,
                    reason="Load compact audit data for this passage.",
                ),
            ]
        )
        if len(options) >= 3:
            return options[:3]
    return options


def _review_resource_uri(
    review_id: str,
    path: str,
    *,
    query: dict[str, str] | None = None,
    session_id: str | None = None,
) -> str:
    query_params = dict(query or {})
    if session_id is not None:
        query_params["session_id"] = session_id
    encoded_review_id = quote(review_id, safe="")
    if "/" in path:
        prefix, identifier = path.split("/", maxsplit=1)
        encoded_path = f"{quote(prefix, safe='')}/{quote(identifier, safe='')}"
    else:
        encoded_path = quote(path, safe="")
    resource = f"pubtator://reviews/{encoded_review_id}/{encoded_path}"
    if query_params:
        resource = f"{resource}?{urlencode(query_params)}"
    return resource
