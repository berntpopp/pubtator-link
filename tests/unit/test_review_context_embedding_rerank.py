from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.services.review_context.embedding_rerank import rerank_with_embeddings


def row(
    passage_id: str,
    *,
    lexical_rank: float,
    section: str = "results",
    source_kind: str = "pubtator_full_bioc",
) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="review-1",
        source_id=f"source-{passage_id}",
        source_kind=source_kind,
        section=section,
        text=f"text for {passage_id}",
        pmid="123",
        lexical_rank=lexical_rank,
    )


def test_guarded_dense_rerank_does_not_promote_references_above_evidence() -> None:
    rows = [
        row("evidence-low-dense", lexical_rank=2.0, section="results"),
        row("ref-high-dense", lexical_rank=1.0, section="ref"),
    ]
    dense_scores = {
        "evidence-low-dense": 0.1,
        "ref-high-dense": 0.99,
    }

    ranked, diagnostics = rerank_with_embeddings(rows, dense_scores, rrf_k=60)

    assert [passage.passage_id for passage in ranked] == [
        "evidence-low-dense",
        "ref-high-dense",
    ]
    assert diagnostics.active is True


def test_rrf_combines_lexical_and_dense_rank() -> None:
    rows = [
        row("lexical-first", lexical_rank=3.0, section="results"),
        row("dense-first", lexical_rank=2.0, section="discussion"),
        row("lexical-third", lexical_rank=1.0, section="conclusion"),
    ]
    dense_scores = {
        "lexical-first": 0.1,
        "dense-first": 0.9,
        "lexical-third": 0.8,
    }

    ranked, diagnostics = rerank_with_embeddings(rows, dense_scores, rrf_k=60)

    assert [passage.passage_id for passage in ranked] == [
        "dense-first",
        "lexical-first",
        "lexical-third",
    ]
    assert diagnostics.strategy == "lexical_top_k_dense_rrf"
    assert diagnostics.candidate_count == 3
    assert diagnostics.embedded_candidate_count == 3
    assert diagnostics.missing_embedding_count == 0
