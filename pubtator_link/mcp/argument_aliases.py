from __future__ import annotations

from collections.abc import Iterable


def coalesce_query(*values: str | None) -> str:
    """Return the first non-empty query-like argument."""
    selected_values: list[str] = []
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            selected_values.append(stripped)
    if not selected_values:
        raise ValueError("Provide query.")
    if len(set(selected_values)) > 1:
        raise ValueError("Provide only one query-like argument.")
    return selected_values[0]


def merge_pmids(
    pmids: Iterable[str] | None = None,
    pmid: str | None = None,
    *,
    max_items: int | None = None,
) -> list[str]:
    """Merge list and scalar PMID arguments, preserving first-seen order."""
    selected_pmids: list[str] = []
    seen_pmids: set[str] = set()

    for value in [*(pmids or []), pmid]:
        if value is None:
            continue
        stripped = value.strip()
        if not stripped or stripped in seen_pmids:
            continue
        selected_pmids.append(stripped)
        seen_pmids.add(stripped)
        if max_items is not None and len(selected_pmids) > max_items:
            raise ValueError(f"Provide at most {max_items} pmids or pmid.")
    if not selected_pmids:
        raise ValueError("Provide pmids or pmid.")
    return selected_pmids
