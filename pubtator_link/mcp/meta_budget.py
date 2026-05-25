from __future__ import annotations

from copy import deepcopy
from typing import Any

DIAGNOSTIC_FIELDS = frozenset(
    {
        "_meta",
        "rrf_score",
        "lexical_rank_position",
        "dense_rank_position",
        "rank_features",
        "provider_status",
        "normalized_neighbor_score",
        "score_explanation",
        "match_reasons",
        "match_signals",
        "omitted_candidate_preview",
        "omitted_counts",
        "dropped_summary",
    }
)

PRESERVE_EMPTY_FIELDS = frozenset(
    {
        "results",
        "passages",
        "candidates",
        "candidate_pmids",
        "selected_pmids",
        "pmids",
        "source_pmids",
        "coverage_by_pmid",
        "coverage_reason_by_pmid",
        "unresolved",
        "records",
    }
)


def strip_meta_for_repeated_call(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without workflow/debug metadata for repeated MCP calls."""
    stripped = deepcopy(payload)
    _strip_diagnostic_fields(stripped)
    return stripped


def _strip_diagnostic_fields(value: Any) -> None:
    if isinstance(value, dict):
        for field in DIAGNOSTIC_FIELDS:
            value.pop(field, None)
        for key, child in list(value.items()):
            _strip_diagnostic_fields(child)
            if key not in PRESERVE_EMPTY_FIELDS and child in (None, [], {}):
                value.pop(key, None)
        return
    if isinstance(value, list):
        for item in value:
            _strip_diagnostic_fields(item)
