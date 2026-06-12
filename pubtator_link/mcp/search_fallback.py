"""Search sort normalization and filtered-search local fallback helpers.

PubTator3's ``/search/`` endpoint is strict: it accepts only a fixed set of sort
strings and its filtered/faceted search is periodically offline for database
updates. These helpers reconcile caller-supplied search parameters against that
contract so the MCP literature adapter can degrade gracefully instead of
surfacing opaque upstream HTTP 400s.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pubtator_link.api.client import PubTatorAPIError
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


def filters_have_year(filters: str | None) -> bool:
    if not filters:
        return False
    try:
        parsed = json.loads(filters)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and isinstance(parsed.get("year"), dict)


def pubtator_filtered_search_unavailable(exc: PubTatorAPIError) -> bool:
    message = str(exc).lower()
    return "currently updating the database" in message or "please try again later" in message


def apply_local_search_filters(
    items: list[dict[str, Any]],
    filters: str | None,
) -> list[dict[str, Any]]:
    if not filters:
        return items
    try:
        parsed = json.loads(filters)
    except json.JSONDecodeError:
        return items
    if not isinstance(parsed, dict):
        return items
    selected = items
    year_filter = parsed.get("year")
    if isinstance(year_filter, dict):
        year_min = year_filter.get("min")
        year_max = year_filter.get("max")
        selected = [
            item
            for item in selected
            if _item_matches_year_bounds(item, year_min=year_min, year_max=year_max)
        ]
    type_filter = parsed.get("type")
    if isinstance(type_filter, list | tuple) and type_filter:
        allowed = {str(value).lower() for value in type_filter}
        selected = [
            item
            for item in selected
            if allowed.intersection(
                {str(value).lower() for value in item.get("publication_types", [])}
            )
        ]
    return selected


def _item_matches_year_bounds(
    item: dict[str, Any],
    *,
    year_min: object,
    year_max: object,
) -> bool:
    year = _item_publication_year(item)
    if year is None:
        return False
    if isinstance(year_min, int) and year < year_min:
        return False
    return not (isinstance(year_max, int) and year > year_max)


def _item_publication_year(item: dict[str, Any]) -> int | None:
    for key in ("pub_year", "pub_date", "meta_date_publication", "date"):
        value = item.get(key)
        if value is None:
            continue
        match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", str(value))
        if match is not None:
            return int(match.group(1))
    return None
