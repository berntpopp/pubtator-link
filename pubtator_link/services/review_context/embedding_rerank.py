from __future__ import annotations

from collections.abc import Mapping, Sequence

from pubtator_link.models.review_rerag import (
    EmbeddingRerankDiagnostics,
    ReviewPassageRow,
)
from pubtator_link.services.review_context.ranking import rerank_key

GUARDED_SECTIONS = {"ref", "references", "abbr"}
RRF_STRATEGY = "lexical_top_k_dense_rrf"


def rerank_with_embeddings(
    rows: Sequence[ReviewPassageRow],
    dense_scores: Mapping[str, float],
    rrf_k: int,
) -> tuple[list[ReviewPassageRow], EmbeddingRerankDiagnostics]:
    """Rank lexical top-k candidates with dense RRF while guarding non-evidence sections."""
    lexical_rows = sorted(rows, key=rerank_key)
    embedded_candidate_count = sum(1 for row in rows if row.passage_id in dense_scores)
    diagnostics = EmbeddingRerankDiagnostics(
        enabled=True,
        candidate_count=len(rows),
        embedded_candidate_count=embedded_candidate_count,
        missing_embedding_count=len(rows) - embedded_candidate_count,
    )
    if not rows:
        diagnostics.fallback_reason = "no_candidates"
        return [], diagnostics
    if not dense_scores:
        diagnostics.fallback_reason = "no_dense_scores"
        return lexical_rows, diagnostics

    evidence_rows = [row for row in lexical_rows if not _is_guarded_section(row.section)]
    guarded_rows = [row for row in lexical_rows if _is_guarded_section(row.section)]
    if not evidence_rows:
        diagnostics.fallback_reason = "no_evidence_candidates"
        return guarded_rows, diagnostics

    diagnostics.active = True
    diagnostics.strategy = RRF_STRATEGY

    lexical_rank_by_passage_id = {
        row.passage_id: rank for rank, row in enumerate(lexical_rows, start=1)
    }
    dense_rank_by_passage_id = {
        row.passage_id: rank
        for rank, row in enumerate(_dense_ranked_evidence(evidence_rows, dense_scores), start=1)
    }

    ranked_evidence = sorted(
        evidence_rows,
        key=lambda row: (
            -_rrf_score(
                row,
                lexical_rank_by_passage_id=lexical_rank_by_passage_id,
                dense_rank_by_passage_id=dense_rank_by_passage_id,
                rrf_k=rrf_k,
            ),
            rerank_key(row),
        ),
    )
    return ranked_evidence + guarded_rows, diagnostics


def _is_guarded_section(section: str) -> bool:
    return section.strip().lower() in GUARDED_SECTIONS


def _dense_ranked_evidence(
    rows: Sequence[ReviewPassageRow],
    dense_scores: Mapping[str, float],
) -> list[ReviewPassageRow]:
    embedded_rows = [row for row in rows if row.passage_id in dense_scores]
    return sorted(
        embedded_rows,
        key=lambda row: (-dense_scores[row.passage_id], rerank_key(row)),
    )


def _rrf_score(
    row: ReviewPassageRow,
    *,
    lexical_rank_by_passage_id: Mapping[str, int],
    dense_rank_by_passage_id: Mapping[str, int],
    rrf_k: int,
) -> float:
    lexical_rank = lexical_rank_by_passage_id[row.passage_id]
    score = 1 / (rrf_k + lexical_rank)
    dense_rank = dense_rank_by_passage_id.get(row.passage_id)
    if dense_rank is not None:
        score += 1 / (rrf_k + dense_rank)
    return score
