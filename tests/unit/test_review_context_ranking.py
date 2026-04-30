from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.services.review_context.ranking import rerank_key


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


def test_rerank_key_prefers_higher_rank_then_section_then_source() -> None:
    rows = [
        _row("body", rank=1.0, section="body", source_kind="pubtator_abstract"),
        _row("abstract", rank=1.0, section="abstract", source_kind="pubtator_abstract"),
        _row("full", rank=1.0, section="abstract", source_kind="pubtator_full_bioc"),
        _row("best", rank=2.0, section="body", source_kind="pubtator_abstract"),
    ]

    assert [row.passage_id for row in sorted(rows, key=rerank_key)] == [
        "best",
        "full",
        "abstract",
        "body",
    ]
