"""Helpers for PubTator3 search filter parameters."""

import json
from typing import Any

MIN_SEARCH_YEAR = 1800
MAX_SEARCH_YEAR = 2030


def _validate_year_bound(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if not MIN_SEARCH_YEAR <= value <= MAX_SEARCH_YEAR:
        raise ValueError(f"{name} must be between {MIN_SEARCH_YEAR} and {MAX_SEARCH_YEAR}")
    return value


def _validate_raw_year_filter(year_filter: Any) -> None:
    if not isinstance(year_filter, dict):
        raise ValueError("year must be a JSON object")
    year_min = _validate_year_bound("year.min", year_filter.get("min"))
    year_max = _validate_year_bound("year.max", year_filter.get("max"))
    if year_min is not None and year_max is not None and year_max < year_min:
        raise ValueError("year.max must be greater than or equal to year.min")


def merge_search_filters(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
) -> str | None:
    """Merge raw PubTator3 filters JSON with flat public filter arguments."""
    merged, _warning = _merge_search_filters(
        filters,
        publication_types,
        year_min,
        year_max,
        ignore_malformed_filters=False,
    )
    return merged


def merge_search_filters_lenient(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
) -> tuple[str | None, str | None]:
    """Merge filters while ignoring malformed raw JSON for MCP tool calls."""
    return _merge_search_filters(
        filters,
        publication_types,
        year_min,
        year_max,
        ignore_malformed_filters=True,
    )


def _merge_search_filters(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
    *,
    ignore_malformed_filters: bool,
) -> tuple[str | None, str | None]:
    _validate_year_bound("year_min", year_min)
    _validate_year_bound("year_max", year_max)
    if year_min is not None and year_max is not None and year_max < year_min:
        raise ValueError("year_max must be greater than or equal to year_min")

    merged: dict[str, Any] = {}
    warning = None
    if filters:
        try:
            parsed = json.loads(filters)
        except json.JSONDecodeError as e:
            if not ignore_malformed_filters:
                raise ValueError(f"Invalid filters JSON format: {e}") from e
            parsed = {}
            warning = _ignored_filters_warning(f"Invalid filters JSON format: {e}")
        if not isinstance(parsed, dict):
            if not ignore_malformed_filters:
                raise ValueError("filters must be a JSON object")
            parsed = {}
            warning = _ignored_filters_warning("filters must be a JSON object")
        merged.update(parsed)
        if "year" in merged:
            _validate_raw_year_filter(merged["year"])

    if publication_types:
        if "type" in merged:
            raise ValueError(
                "filters already contains type; use either filters.type or publication_types"
            )
        merged["type"] = publication_types

    if year_min is not None or year_max is not None:
        if "year" in merged:
            raise ValueError(
                "filters already contains year; use either filters.year or year_min/year_max"
            )
        year_filter: dict[str, int] = {}
        if year_min is not None:
            year_filter["min"] = year_min
        if year_max is not None:
            year_filter["max"] = year_max
        merged["year"] = year_filter

    return json.dumps(merged, separators=(",", ":")) if merged else None, warning


def _ignored_filters_warning(reason: str) -> str:
    return f"Ignored malformed filters value for MCP search: {reason}"
