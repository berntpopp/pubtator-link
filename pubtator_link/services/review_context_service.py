"""Service for retrieving review-scoped context passages."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewPassageRow,
)


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
        limit: int = 8,
    ) -> list[ReviewPassageRow]:
        """Return candidate passages for a review-scoped retrieval request."""

    async def preparation_status(self, review_id: str) -> PreparationStatus | dict[str, int]:
        """Return preparation status counts for a review."""


SECTION_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "abstr": 1,
    "summary": 2,
    "introduction": 3,
    "intro": 3,
    "background": 4,
    "methods": 5,
    "method": 5,
    "materials and methods": 5,
    "results": 6,
    "result": 6,
    "discussion": 7,
    "discuss": 7,
    "conclusion": 8,
    "conclusions": 8,
    "concl": 8,
    "table": 9,
    "body": 10,
    "ref": 50,
    "references": 50,
}

SOURCE_PRIORITY = {
    "pubtator_full_bioc": 0,
    "pmc_bioc": 1,
    "europe_pmc_jats": 2,
    "curated_pdf": 3,
    "curated_html": 4,
    "docling_pdf": 5,
    "pubtator_abstract": 6,
}


class ReviewContextService:
    """Retrieve, rerank, and pack review-scoped context passages."""

    def __init__(self, repository: ReviewContextRepository) -> None:
        self.repository = repository

    async def retrieve_context(
        self,
        review_id: str,
        request: RetrieveReviewContextRequest,
    ) -> RetrieveReviewContextResponse:
        """Build a citable context pack for a review question."""
        candidates = await self.repository.search_passages(
            review_id,
            request.question,
            entity_ids=request.entity_ids,
            pmids=request.pmids,
            sections=request.sections,
            limit=80,
        )
        sorted_candidates = sorted(candidates, key=self._rerank_key)
        selected = self._pack_passages(sorted_candidates, request)
        passages = [
            ContextPassage(
                citation_key=f"S{index}",
                passage_id=row.passage_id,
                pmid=row.pmid,
                pmcid=row.pmcid,
                section=row.section,
                text=row.text,
                source_kind=row.source_kind,
            )
            for index, row in enumerate(selected, start=1)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        return RetrieveReviewContextResponse(
            review_id=review_id,
            context_pack=ContextPack(
                question=request.question,
                passages=passages,
                citation_map=citation_map,
            ),
            preparation_status=await self._preparation_status(review_id),
        )

    def _pack_passages(
        self,
        candidates: list[ReviewPassageRow],
        request: RetrieveReviewContextRequest,
    ) -> list[ReviewPassageRow]:
        selected: list[ReviewPassageRow] = []
        pmid_counts: dict[str, int] = defaultdict(int)
        total_chars = 0
        enforce_pmid_diversity = len(request.pmids) != 1

        for row in candidates:
            if len(selected) >= request.max_passages:
                break
            if (
                enforce_pmid_diversity
                and row.pmid is not None
                and pmid_counts[row.pmid] >= request.max_passages_per_pmid
            ):
                continue
            if total_chars + len(row.text) > request.max_chars:
                continue

            selected.append(row)
            total_chars += len(row.text)
            if row.pmid is not None:
                pmid_counts[row.pmid] += 1

        return selected

    async def _preparation_status(self, review_id: str) -> PreparationStatus:
        status = await self.repository.preparation_status(review_id)
        if isinstance(status, PreparationStatus):
            return status
        return PreparationStatus(**status)

    @staticmethod
    def _rerank_key(row: ReviewPassageRow) -> tuple[float, int, int, str, str]:
        return (
            -row.lexical_rank,
            SECTION_PRIORITY.get(row.section.strip().lower(), 100),
            SOURCE_PRIORITY.get(row.source_kind, 100),
            row.pmid or "",
            row.passage_id,
        )
