"""Search sort normalization and filtered-search local fallback helpers.

PubTator3's ``/search/`` endpoint is strict: it accepts only a fixed set of sort
strings and its filtered/faceted search is periodically offline for database
updates. These helpers reconcile caller-supplied search parameters against that
contract so the MCP literature adapter can degrade gracefully instead of
surfacing opaque upstream HTTP 400s.
"""

from __future__ import annotations

import json
from typing import Any

from pubtator_link.api.client import PubTatorAPIError
from pubtator_link.api.search_filters import publication_year_of
from pubtator_link.mcp.input_normalization import InputNormalizationError

# PubTator3's /search/ endpoint accepts only these exact sort strings; any other
# value returns HTTP 400 "Incorrect sort. Should be one of {...}". PubTator3 sorts
# descending only, so ascending requests are rejected rather than silently flipped.
VALID_PUBTATOR_SORTS: tuple[str, ...] = ("score desc", "date desc", "_id desc")
_CANONICAL_SEARCH_SORTS: dict[str, str] = {
    "score": "score desc",
    "score desc": "score desc",
    "relevance": "score desc",
    "relevance desc": "score desc",
    "best": "score desc",
    "best match": "score desc",
    "date": "date desc",
    "date desc": "date desc",
    "newest": "date desc",
    "recent": "date desc",
    "most recent": "date desc",
    "publication date": "date desc",
    "pub date": "date desc",
    "_id": "_id desc",
    "_id desc": "_id desc",
    "id": "_id desc",
    "id desc": "_id desc",
}


def normalize_search_sort(sort: str | None) -> tuple[str | None, str | None]:
    """Map a caller sort value to a PubTator3-accepted sort string.

    Returns (canonical_sort, warning). Unknown or ascending values raise
    InputNormalizationError so the LLM receives actionable field guidance instead
    of an opaque internal_error from the upstream HTTP 400.
    """
    if sort is None:
        return None, None
    raw = sort.strip()
    if not raw:
        return None, None
    key = " ".join(raw.lower().split())
    canonical = _CANONICAL_SEARCH_SORTS.get(key)
    if canonical is None:
        valid = ", ".join(f"'{value}'" for value in VALID_PUBTATOR_SORTS)
        raise InputNormalizationError(
            field_errors=[
                {
                    "field": "sort",
                    "message": (
                        f"Unsupported sort '{sort}'. PubTator3 accepts only {valid} "
                        "(descending only). Use 'date desc' for newest-first or "
                        "'score desc' for relevance, or omit sort."
                    ),
                }
            ],
            recovery_hint=(
                "Retry with sort='date desc' (newest first) or sort='score desc' "
                "(relevance), or omit sort for default relevance ranking."
            ),
        )
    if canonical == raw:
        return canonical, None
    return canonical, f"Normalized sort '{sort}' to '{canonical}'."


def pubtator_filtered_search_unavailable(exc: PubTatorAPIError) -> bool:
    message = str(exc).lower()
    return "currently updating the database" in message or "please try again later" in message


def apply_local_search_filters(
    items: list[dict[str, Any]],
    filters: str | None,
) -> list[dict[str, Any]]:
    """Apply a PubTator3 server-side filter JSON locally (transient-outage path).

    Mirrors PubTator3's ``filters`` contract: ``type``/``journal``/``year`` map to
    AND-combined value lists, and ``year`` holds discrete year strings. Year
    *ranges* are not encoded here (they travel as a separate local window); see
    :func:`pubtator_link.api.search_filters.apply_year_window`.
    """
    if not filters:
        return items
    try:
        parsed = json.loads(filters)
    except json.JSONDecodeError:
        return items
    if not isinstance(parsed, dict):
        return items
    selected = items
    selected = _filter_by_year_values(selected, parsed.get("year"))
    selected = _filter_by_field(selected, parsed.get("type"), "publication_types")
    selected = _filter_by_field(selected, parsed.get("journal"), "journal")
    return selected


def _filter_by_year_values(
    items: list[dict[str, Any]],
    year_filter: Any,
) -> list[dict[str, Any]]:
    if not isinstance(year_filter, list | tuple) or not year_filter:
        return items
    allowed = {str(value).strip() for value in year_filter}
    return [
        item
        for item in items
        if (year := publication_year_of(item)) is not None and str(year) in allowed
    ]


def _filter_by_field(
    items: list[dict[str, Any]],
    field_filter: Any,
    item_key: str,
) -> list[dict[str, Any]]:
    if not isinstance(field_filter, list | tuple) or not field_filter:
        return items
    allowed = {str(value).lower() for value in field_filter}
    return [item for item in items if allowed.intersection(_item_values(item.get(item_key)))]


def _item_values(value: Any) -> set[str]:
    if isinstance(value, list | tuple):
        return {str(entry).lower() for entry in value}
    if value is None:
        return set()
    return {str(value).lower()}
