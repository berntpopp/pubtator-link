from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from pubtator_link.models.research_session_list import (
    ListResearchSessionsResponse,
    ResearchSessionSummary,
)
from pubtator_link.models.responses import SearchResponse
from pubtator_link.models.review_rerag import (
    ResearchSessionCandidate,
    ResearchSessionCandidateStatus,
    ResearchSessionDecisionReason,
    ResearchSessionStatusResponse,
    StageResearchSessionRequest,
    StageResearchSessionResponse,
)

_CURSOR_TOKEN = re.compile(r"[A-Za-z0-9_-]+")


@dataclass(frozen=True)
class _SessionCursor:
    updated_at: str | None
    session_id: str
    review_id: str


def _cursor_scope(review_id: str | None) -> str:
    material = "global" if review_id is None else f"review:{review_id}"
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _encode_cursor(*, review_id: str | None, summary: ResearchSessionSummary) -> str:
    payload = {
        "v": 1,
        "scope": _cursor_scope(review_id),
        "updated_at": summary.updated_at,
        "session_id": summary.session_id,
        "review_id": summary.review_id,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(encoded).decode().rstrip("=")


def _invalid_cursor() -> ValueError:
    return ValueError("cursor is invalid")


def _decode_cursor(*, cursor: str, review_id: str | None) -> _SessionCursor:
    if len(cursor) > 2048 or _CURSOR_TOKEN.fullmatch(cursor) is None or len(cursor) % 4 == 1:
        raise _invalid_cursor()
    try:
        raw = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError):
        raise _invalid_cursor() from None
    if not isinstance(decoded, dict) or set(decoded) != {
        "v",
        "scope",
        "updated_at",
        "session_id",
        "review_id",
    }:
        raise _invalid_cursor()
    if (
        type(decoded["v"]) is not int
        or decoded["v"] != 1
        or not isinstance(decoded["scope"], str)
        or decoded["scope"] != _cursor_scope(review_id)
        or not isinstance(decoded["session_id"], str)
        or not decoded["session_id"]
        or not isinstance(decoded["review_id"], str)
        or not decoded["review_id"]
        or (decoded["updated_at"] is not None and not isinstance(decoded["updated_at"], str))
    ):
        raise _invalid_cursor()
    if decoded["updated_at"] is not None:
        try:
            datetime.fromisoformat(decoded["updated_at"].replace("Z", "+00:00"))
        except ValueError:
            raise _invalid_cursor() from None
    if review_id is not None and decoded["review_id"] != review_id:
        raise _invalid_cursor()
    return _SessionCursor(
        updated_at=decoded["updated_at"],
        session_id=decoded["session_id"],
        review_id=decoded["review_id"],
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
                            error="Preparation failed.",
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

    async def list_sessions(
        self,
        *,
        review_id: str | None,
        limit: int = 10,
        cursor: str | None = None,
    ) -> ListResearchSessionsResponse:
        """Return one compact page without fetching session candidates."""
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")
        decoded_cursor = (
            _decode_cursor(cursor=cursor, review_id=review_id) if cursor is not None else None
        )
        list_summaries = getattr(self.repository, "list_research_session_summaries", None)
        if list_summaries is None:
            raise ValueError("Research session summary paging is unavailable.")
        rows = await list_summaries(
            review_id=review_id,
            limit=limit + 1,
            before_updated_at=(decoded_cursor.updated_at if decoded_cursor else None),
            before_session_id=(decoded_cursor.session_id if decoded_cursor else None),
            before_review_id=(decoded_cursor.review_id if decoded_cursor else None),
        )
        summaries = [ResearchSessionSummary.model_validate(row) for row in rows]
        has_next_page = len(summaries) > limit
        page = summaries[:limit]
        for summary in page:
            summary.preparation_status = await self.queue.repository.preparation_status(
                summary.review_id
            )
        return ListResearchSessionsResponse(
            sessions=page,
            limit=limit,
            next_cursor=(
                _encode_cursor(review_id=review_id, summary=page[-1])
                if has_next_page and page
                else None
            ),
            total_returned=len(page),
        )

    async def list_sessions_global(
        self, *, limit: int = 10, cursor: str | None = None
    ) -> ListResearchSessionsResponse:
        """Compatibility wrapper for callers that request the global page directly."""
        return await self.list_sessions(review_id=None, limit=limit, cursor=cursor)

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
