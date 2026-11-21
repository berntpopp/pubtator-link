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

from pubtator_link.api.client import PubTator3Client, PubTatorAPIError
from pubtator_link.api.search_filters import (
    SearchFilterPlan,
    apply_year_window,
    publication_year_of,
    year_facet_counts,
)
from pubtator_link.mcp.input_normalization import InputNormalizationError

# PubTator3's /search/ endpoint accepts only these exact sort strings; any other
# value returns HTTP 400 "Incorrect sort. Should be one of {...}". PubTator3 sorts
# descending only, so ascending requests are rejected rather than silently flipped.
# Deepest /search/ page PubTator3 served live (2026-11-21: page 50000 ok in ~8 s, 100000 failed).
_MAX_UPSTREAM_PAGE = 50_000
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
        # Never echo the rejected caller sort VALUE back into the frame -- it can
        # carry hostile prose / control-code points. Only server-authored guidance.
        raise InputNormalizationError(
            field_errors=[
                {
                    "field": "sort",
                    "message": (
                        f"Unsupported sort value. PubTator3 accepts only {valid} "
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
    return canonical, f"Normalized sort to '{canonical}'."


def pubtator_filtered_search_unavailable(exc: PubTatorAPIError) -> bool:
    # The client severs the raw upstream body and encodes PubTator3's transient
    # filtered-search outage as this stable, body-free terminal_reason signal.
    terminal_reason = exc.terminal_reason or exc.retry_metadata.get("terminal_reason")
    if terminal_reason == "filtered_search_unavailable":
        return True
    # Back-compat for exceptions still constructed with the legacy body text.
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


async def search_publications_with_filter_fallback(
    *,
    client: PubTator3Client,
    text: str,
    page: int,
    sort: str | None,
    plan: SearchFilterPlan,
    sections: str | None,
) -> tuple[dict[str, Any], str | None]:
    """Run the search, honouring PubTator3's filter limits.

    Returns ``(result, note)`` where ``note`` is ``None`` for a fully server-side
    search, ``"year_range_local"`` when a year range was trimmed locally, or
    ``"transient_outage"`` when PubTator3's filtered endpoint was unavailable and
    every filter had to be applied locally over an unfiltered page.
    """
    server_filters = plan.server_filters
    # A year range can only be honoured locally over one page, so fetch
    # newest-first (when the caller chose no sort) to avoid undercounting recent
    # literature behind relevance-ranked older hits and dropping it on the trim.
    fetch_sort = sort
    if fetch_sort is None and plan.has_local_year_window:
        fetch_sort = "date desc"
    try:
        result = await client.search_publications(
            text=text,
            page=page,
            sort=fetch_sort,
            filters=server_filters,
            sections=sections,
        )
    except PubTatorAPIError as exc:
        if server_filters is None or not pubtator_filtered_search_unavailable(exc):
            raise
        fallback = await client.search_publications(
            text=text,
            page=page,
            sort=fetch_sort,
            filters=None,
            sections=sections,
        )
        items = apply_local_search_filters(list(fallback.get("results", [])), server_filters)
        items = apply_year_window(items, plan.local_year_min, plan.local_year_max)
        return _local_single_page(fallback, items), "transient_outage"

    if plan.has_local_year_window:
        window = None
        if fetch_sort == "date desc":
            window = year_facet_counts(result, plan.local_year_min, plan.local_year_max)
        if window is not None:
            # Newest-first, the range is one contiguous run after `newer` hits: page through it
            # instead of trimming the newest page to nothing (#281).
            newer, in_window = window
            size = int(result.get("page_size") or 10)
            if newer // size:
                if page + newer // size > _MAX_UPSTREAM_PAGE:
                    raise ValueError(
                        "year_max excludes too many newer hits to page past; narrow text or set "
                        "year_min equal to year_max"
                    )
                result = await client.search_publications(
                    text=text,
                    page=page + newer // size,
                    sort=fetch_sort,
                    filters=server_filters,
                    sections=sections,
                )
            items = apply_year_window(
                list(result.get("results", [])), plan.local_year_min, plan.local_year_max
            )
            pages = -(-(newer % size + in_window) // size)
            return {**result, "results": items, "count": in_window, "total_pages": pages}, (
                "year_range_paged"
            )
        items = apply_year_window(
            list(result.get("results", [])), plan.local_year_min, plan.local_year_max
        )
        return _local_single_page(result, items), "year_range_local"
    return result, None


def _local_single_page(
    base: dict[str, Any],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    # Filters were applied locally to a SINGLE fetched page (upstream could not do it server-side).
    # The true filtered total across all upstream pages is unknown, so `total` is reported as a
    # lower bound and the upstream page count is preserved so the client can see that later pages
    # exist -- never a fabricated `total_pages: 1` that says retrieval is complete.
    upstream_pages = base.get("total_pages")
    current_page = int(base.get("page", 1) or 1)
    has_more = bool(isinstance(upstream_pages, int) and current_page < upstream_pages)
    warnings = list(base.get("warnings") or [])
    warnings.append(
        "Filters were applied locally to one fetched page; total is a lower bound and more "
        "matches may exist on later pages (increase page to continue)."
    )
    return {
        **base,
        "results": items,
        "count": len(items),
        "total": len(items),
        "total_results": len(items),
        "total_results_is_lower_bound": True,
        "has_more": has_more,
        "warnings": warnings,
    }
