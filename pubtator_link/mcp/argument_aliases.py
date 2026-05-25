from __future__ import annotations

from collections.abc import Iterable


def coalesce_query(*values: str | None) -> str:
    """Return the first non-empty query-like argument."""
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    raise ValueError("Provide query.")


def merge_pmids(pmids: Iterable[str] | None = None, pmid: str | None = None) -> list[str]:
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

    if not selected_pmids:
        raise ValueError("Provide pmids or pmid.")
    return selected_pmids
