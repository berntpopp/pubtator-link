from __future__ import annotations

from pubtator_link.models.review_rerag import RetrieveReviewContextRequest, ReviewPassageRow
from pubtator_link.services.review_context.packing import (
    context_budget,
    excerpt_text,
    pack_passages,
)


def _row(passage_id: str, *, rank: float, section: str, source_kind: str) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="r1",
        source_id="s1",
        source_kind=source_kind,
        pmid="123",
        pmcid=None,
        doi=None,
        url=None,
        section=section,
        heading_path=None,
        page=None,
        text="text",
        entity_ids=[],
        relation_types=[],
        screening_status="candidate",
        source_metadata={},
        lexical_rank=rank,
    )


def test_excerpt_text_centers_first_query_token() -> None:
    text = "A" * 50 + " colchicine " + "B" * 50

    excerpt, start, end, truncated = excerpt_text(
        text,
        query_tokens=["colchicine"],
        max_chars=40,
        allow_truncated=True,
    )

    assert truncated is True
    assert "colchicine" in excerpt
    assert end - start == 40


def test_pack_passages_drops_over_budget_passage() -> None:
    row = _row("p1", rank=1.0, section="abstract", source_kind="pubtator_abstract")
    row.text = "x" * 600
    request = RetrieveReviewContextRequest(question="MEFV", max_chars=500)

    packed = pack_passages([row], request)

    assert packed.selected == []
    assert packed.dropped[0].reason == "char_budget_exceeded"


def test_context_budget_estimates_total_chars() -> None:
    budget = context_budget(max_chars=1000, text_chars=400, dropped_count=2)

    assert budget.max_chars == 1000
    assert budget.text_chars == 400
    assert budget.estimated_total_chars > 400
    assert budget.dropped_count == 2
