from __future__ import annotations

from typing import Any
from uuid import uuid4

from pubtator_link.mcp.untrusted_content import sanitize_message
from pubtator_link.models.responses import SearchResponse
from pubtator_link.models.review_rerag import (
    ListResearchSessionsResponse,
    ResearchSessionCandidate,
    ResearchSessionCandidateStatus,
    ResearchSessionDecisionReason,
    ResearchSessionStatusResponse,
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
        request_payload = stage_request.model_dump(mode="json")
        candidates = await self._candidate_pmids(stage_request)
        limited = candidates[: stage_request.max_candidates]
        await self.repository.upsert_research_session(
            review_id=review_id,
            session_id=session_id,
            query=stage_request.query,
            status="active",
            request=request_payload,
        )

        try:
            hints = await self.preflight_service.preflight_pmids(
                [pmid for pmid, _title, _reason in limited]
            )
        except Exception as exc:
            await self.repository.upsert_research_session(
                review_id=review_id,
                session_id=session_id,
                query=stage_request.query,
                status="failed",
                request=request_payload,
            )
            raise RuntimeError(
                f"preflight failed for research session {session_id}: {exc}"
            ) from exc

        hints_by_pmid = {hint.pmid: hint for hint in hints}
        has_completed_candidate = False
        for rank, (pmid, title, source_reason) in enumerate(limited, start=1):
            hint = hints_by_pmid.get(pmid)
            should_queue = stage_request.stage_full_text and (
                hint is None or hint.expected_coverage in {"full_text", "abstract_only", "unknown"}
            )
            if should_queue:
                try:
                    queued = await self.queue.enqueue_pmid(review_id, pmid)
                except Exception as exc:
                    await self.repository.upsert_research_session_candidate(
                        review_id=review_id,
                        session_id=session_id,
                        candidate=ResearchSessionCandidate(
                            pmid=pmid,
                            rank=rank,
                            title=title,
                            status="failed",
                            decision_reason="queue_rejected",
                            coverage_hint=hint,
                            source_id=f"PMID:{pmid}",
                            error=sanitize_message(str(exc)),
                        ),
                    )
                    await self.repository.upsert_research_session(
                        review_id=review_id,
                        session_id=session_id,
                        query=stage_request.query,
                        status="partial" if has_completed_candidate else "failed",
                        request=request_payload,
                    )
                    raise RuntimeError(f"queue failed for PMID {pmid}: {exc}") from exc
                if queued:
                    status: ResearchSessionCandidateStatus = "queued"
                    reason: ResearchSessionDecisionReason = source_reason
                    await self.repository.link_review_session_source(
                        review_id, session_id, f"PMID:{pmid}"
                    )
                else:
                    status = "skipped"
                    reason = "queue_rejected"
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
            has_completed_candidate = True

        manifest = await self.repository.get_research_session(review_id, session_id)
        if manifest is None:
            raise RuntimeError(
                f"Research session manifest was not found for review_id={review_id} "
                f"session_id={session_id}"
            )
        manifest.preparation_status = await self.queue.repository.preparation_status(review_id)
        return StageResearchSessionResponse(
            manifest=manifest,
            _meta={
                "next_commands": [
                    "get_research_session_status",
                    "inspect_review_index",
                    "get_review_context_batch",
                ],
                "unsafe_for_clinical_use": True,
            },
        )

    async def get_status(
        self, *, review_id: str | None, session_id: str
    ) -> ResearchSessionStatusResponse:
        if review_id is None:
            return await self.get_status_by_session_id(session_id=session_id)
        manifest = await self.repository.get_research_session(review_id, session_id)
        if manifest is None:
            raise LookupError(f"Research session not found: {session_id}")
        manifest.preparation_status = await self.queue.repository.preparation_status(review_id)
        await self._reconcile_candidate_statuses(review_id, manifest)
        return ResearchSessionStatusResponse(manifest=manifest)

    async def get_status_by_session_id(self, *, session_id: str) -> ResearchSessionStatusResponse:
        finder = getattr(self.repository, "find_research_sessions_by_session_id", None)
        if finder is None:
            raise LookupError(f"Research session not found: {session_id}")
        sessions = [session for session in await finder(session_id) if session is not None]
        identities = {(session.review_id, session.session_id) for session in sessions}
        if not sessions:
            raise LookupError(f"Research session not found: {session_id}")
        if len(identities) > 1:
            raise ValueError(f"Research session id is ambiguous: {session_id}")
        manifest = sessions[0]
        manifest.preparation_status = await self.queue.repository.preparation_status(
            manifest.review_id
        )
        await self._reconcile_candidate_statuses(manifest.review_id, manifest)
        return ResearchSessionStatusResponse(manifest=manifest)

    async def list_sessions(self, *, review_id: str | None) -> ListResearchSessionsResponse:
        if review_id is None:
            return await self.list_sessions_global()
        sessions = await self.repository.list_research_sessions(review_id)
        preparation_status = await self.queue.repository.preparation_status(review_id)
        for session in sessions:
            session.preparation_status = preparation_status
            await self._reconcile_candidate_statuses(review_id, session)
        return ListResearchSessionsResponse(sessions=sessions)

    async def list_sessions_global(self, *, limit: int = 20) -> ListResearchSessionsResponse:
        list_global = getattr(self.repository, "list_research_sessions_global", None)
        if list_global is None:
            raise ValueError("Research session listing requires review_id for this repository.")
        sessions = sorted(
            await list_global(limit=limit),
            key=lambda session: session.updated_at or "",
            reverse=True,
        )[:limit]
        for session in sessions:
            session.preparation_status = await self.queue.repository.preparation_status(
                session.review_id
            )
            await self._reconcile_candidate_statuses(session.review_id, session)
        return ListResearchSessionsResponse(sessions=sessions)

    async def _reconcile_candidate_statuses(self, review_id: str, manifest: Any) -> None:
        list_review_sources = getattr(self.queue.repository, "list_review_sources", None)
        if list_review_sources is None:
            list_review_sources = getattr(self.repository, "list_review_sources", None)
        if list_review_sources is None:
            return
        pmids = [candidate.pmid for candidate in manifest.candidates if candidate.pmid]
        if not pmids:
            return
        sources = await list_review_sources(
            review_id,
            pmids=pmids,
            include_passage_samples=False,
            sample_per_pmid=0,
            session_id=manifest.session_id,
        )
        by_pmid = {str(getattr(source, "pmid", "") or ""): source for source in sources}
        for candidate in manifest.candidates:
            source = by_pmid.get(candidate.pmid)
            if source is None:
                continue
            job_status = str(getattr(source, "job_status", "") or "")
            passage_count = int(getattr(source, "passage_count", 0) or 0)
            coverage = str(getattr(source, "coverage", "") or "")
            if job_status != "complete" and passage_count <= 0:
                continue
            if coverage == "full_text":
                candidate.status = "full_text_ready"
            elif coverage == "abstract_only" or passage_count > 0:
                candidate.status = "abstract_ready"

    async def _candidate_pmids(
        self, request: StageResearchSessionRequest
    ) -> list[tuple[str, str | None, ResearchSessionDecisionReason]]:
        seen: set[str] = set()
        candidates: list[tuple[str, str | None, ResearchSessionDecisionReason]] = []
        for pmid in request.pmids:
            if pmid not in seen:
                seen.add(pmid)
                candidates.append((pmid, None, "explicit_pmid"))
        if request.query:
            response = await self.search_provider.search(request)
            for result in response.results:
                if result.pmid and result.pmid not in seen:
                    seen.add(result.pmid)
                    candidates.append((result.pmid, result.title, "selected_by_rank"))
        return candidates
