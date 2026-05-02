from __future__ import annotations

from typing import Any
from uuid import uuid4

from pubtator_link.models.responses import SearchResponse
from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    ResearchSessionCandidateStatus,
    ResearchSessionDecisionReason,
    StageResearchSessionRequest,
    StageResearchSessionResponse,
)


class ResearchSessionSearchProvider:
    async def search(self, request: StageResearchSessionRequest) -> SearchResponse:
        raise NotImplementedError


class ResearchSessionService:
    def __init__(
        self,
        *,
        repository: Any,
        search_provider: ResearchSessionSearchProvider,
        preflight_service: Any,
        queue: Any,
    ) -> None:
        self.repository = repository
        self.search_provider = search_provider
        self.preflight_service = preflight_service
        self.queue = queue

    async def stage(
        self,
        *,
        review_id: str,
        request: StageResearchSessionRequest | dict[str, Any],
    ) -> StageResearchSessionResponse:
        stage_request = (
            request
            if isinstance(request, StageResearchSessionRequest)
            else StageResearchSessionRequest.model_validate(request)
        )
        session_id = stage_request.session_id or f"session-{uuid4().hex}"
        candidates = await self._candidate_pmids(stage_request)
        limited = candidates[: stage_request.max_candidates]
        await self.repository.upsert_research_session(
            review_id=review_id,
            session_id=session_id,
            query=stage_request.query,
            status="active",
            request=stage_request.model_dump(mode="json"),
        )

        hints = await self.preflight_service.preflight_pmids([pmid for pmid, _title in limited])
        hints_by_pmid = {hint.pmid: hint for hint in hints}
        for rank, (pmid, title) in enumerate(limited, start=1):
            hint = hints_by_pmid.get(pmid)
            should_queue = stage_request.stage_full_text and (
                hint is None or hint.expected_coverage in {"full_text", "abstract_only", "unknown"}
            )
            if should_queue and await self.queue.enqueue_pmid(review_id, pmid):
                status: ResearchSessionCandidateStatus = "queued"
                reason: ResearchSessionDecisionReason = "selected_by_rank"
            elif should_queue:
                status = "skipped"
                reason = "already_indexed"
            else:
                status = "skipped"
                reason = "metadata_only"
            await self.repository.upsert_research_session_candidate(
                review_id=review_id,
                session_id=session_id,
                candidate=ResearchSessionCandidate(
                    pmid=pmid,
                    rank=rank,
                    title=title,
                    status=status,
                    decision_reason=reason,
                    coverage_hint=hint,
                    source_id=f"PMID:{pmid}",
                ),
            )

        manifest = await self.repository.get_research_session(review_id, session_id)
        manifest.preparation_status = await self.queue.repository.preparation_status(review_id)
        return StageResearchSessionResponse(
            manifest=manifest,
            _meta={
                "next_commands": [
                    "pubtator.get_research_session_status",
                    "pubtator.inspect_review_index",
                    "pubtator.retrieve_review_context_batch",
                ],
                "unsafe_for_clinical_use": True,
            },
        )

    async def _candidate_pmids(
        self, request: StageResearchSessionRequest
    ) -> list[tuple[str, str | None]]:
        seen: set[str] = set()
        candidates: list[tuple[str, str | None]] = []
        for pmid in request.pmids:
            if pmid not in seen:
                seen.add(pmid)
                candidates.append((pmid, None))
        if request.query:
            response = await self.search_provider.search(request)
            for result in response.results:
                if result.pmid and result.pmid not in seen:
                    seen.add(result.pmid)
                    candidates.append((result.pmid, result.title))
        return candidates
