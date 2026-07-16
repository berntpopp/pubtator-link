"""Compact, cursor-paginated views of staged research sessions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from pubtator_link.models.review_rerag import PreparationStatus, ResearchSessionStatus


class ResearchSessionSummary(BaseModel):
    """One session-list row; candidate details remain behind the status endpoint."""

    session_id: str
    review_id: str
    query: str | None = None
    status: ResearchSessionStatus = "active"
    updated_at: str | None = None
    candidate_count: int = Field(default=0, ge=0)
    preparation_status: PreparationStatus | None = None


class ListResearchSessionsResponse(BaseModel):
    """A bounded page of compact research-session summaries."""

    success: bool = True
    sessions: list[ResearchSessionSummary] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=20)
    next_cursor: str | None = None
    total_returned: int = Field(default=0, ge=0)
