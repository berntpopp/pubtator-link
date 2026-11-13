from __future__ import annotations

from collections.abc import Iterable

from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.models.literature_graph import normalize_pmid

_PMID_REASON = "PMIDs must be ASCII digits 0-9 (optionally 'PMID:'-prefixed)."


def _pmid_error(field: str, reason: str) -> InputNormalizationError:
    return InputNormalizationError(
        field_errors=[{"field": field, "reason": reason}],
        recovery_hint="Pass numeric PubMed IDs, e.g. '25741868'.",
    )


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
    field: str = "pmids",
) -> list[str]:
    """Merge list and scalar PMID arguments, preserving first-seen order."""
    selected_pmids: list[str] = []
    seen_pmids: set[str] = set()

    entries = [*((field, value) for value in pmids or []), ("pmid", pmid)]
    for source, value in entries:
        if value is None or not value.strip():
            continue
        try:
            # One PMID validator for every tool (D4): never pass a non-numeric ID upstream.
            stripped = normalize_pmid(value)
        except ValueError:
            raise _pmid_error(source, _PMID_REASON) from None
        if stripped in seen_pmids:
            continue
        selected_pmids.append(stripped)
        seen_pmids.add(stripped)
        if max_items is not None and len(selected_pmids) > max_items:
            raise _pmid_error(field, f"Provide at most {max_items} PMIDs.")
    if not selected_pmids:
        raise _pmid_error(field, "Provide at least one PMID.")
    return selected_pmids
