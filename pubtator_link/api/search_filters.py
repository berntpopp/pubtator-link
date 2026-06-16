"""Helpers for PubTator3 search filter parameters.

PubTator3's ``/search/`` ``filters`` parameter is ``{field: [values]}`` where
``field`` is one of ``type`` / ``journal`` / ``year`` and multiple list values are
AND-combined. ``year`` accepts only discrete year strings (e.g. ``["2020"]``);
range objects such as ``{"year":{"min":2020}}`` are rejected by PubTator3 with an
HTTP 400 whose body misleadingly reads "We are currently updating the Database".

Because PubTator3 cannot express an open-ended or multi-year range server-side,
:func:`build_search_filter_plan` splits a caller's request into the part PubTator3
can honour (``type``/``journal`` and an *exact* single year) and a residual year
window that must be applied locally to the returned page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

MIN_SEARCH_YEAR = 1800
MAX_SEARCH_YEAR = 2030

_YEAR_RE = re.compile(r"\b(18\d{2}|19\d{2}|20\d{2})\b")


@dataclass(frozen=True)
class SearchFilterPlan:
    """Resolved search filters split into server-side and local-year parts.

    ``server_filters`` is the JSON string PubTator3 accepts verbatim (``type`` /
    ``journal`` / exact-year). ``local_year_min`` / ``local_year_max`` describe a
    year window PubTator3 cannot filter server-side and that callers must apply
    locally to the returned page (best-effort, single-page).
    """

    server_filters: str | None
    local_year_min: int | None
    local_year_max: int | None
    warning: str | None = None

    @property
    def has_local_year_window(self) -> bool:
        return self.local_year_min is not None or self.local_year_max is not None


def _validate_year_bound(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if not MIN_SEARCH_YEAR <= value <= MAX_SEARCH_YEAR:
        raise ValueError(f"{name} must be between {MIN_SEARCH_YEAR} and {MAX_SEARCH_YEAR}")
    return value


def _coerce_raw_year_window(year_filter: Any) -> tuple[int | None, int | None] | None:
    """Resolve a raw ``filters.year`` value into a (min, max) window.

    Returns ``None`` when the value is a native discrete-year list that should be
    passed to PubTator3 unchanged. Raises ``ValueError`` for unsupported shapes.
    """
    if isinstance(year_filter, list):
        for value in year_filter:
            _validate_year_bound("year", _as_year_int(value))
        return None
    if not isinstance(year_filter, dict):
        raise ValueError("year must be a JSON object or list of years")
    year_min = _validate_year_bound("year.min", year_filter.get("min"))
    year_max = _validate_year_bound("year.max", year_filter.get("max"))
    if year_min is not None and year_max is not None and year_max < year_min:
        raise ValueError("year.max must be greater than or equal to year.min")
    return year_min, year_max


def _as_year_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("year values must be integers")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise ValueError("year values must be integers")


def build_search_filter_plan(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
    *,
    ignore_malformed_filters: bool,
) -> SearchFilterPlan:
    """Split caller filters into PubTator3-server and local-year-window parts."""
    _validate_year_bound("year_min", year_min)
    _validate_year_bound("year_max", year_max)
    if year_min is not None and year_max is not None and year_max < year_min:
        raise ValueError("year_max must be greater than or equal to year_min")

    merged: dict[str, Any] = {}
    warning: str | None = None
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

    if publication_types:
        if "type" in merged:
            raise ValueError(
                "filters already contains type; use either filters.type or publication_types"
            )
        merged["type"] = publication_types

    eff_min, eff_max, raw_year_passthrough = _resolve_year_window(
        merged.pop("year", None), year_min, year_max
    )

    local_min: int | None = None
    local_max: int | None = None
    if raw_year_passthrough is not None:
        # Native discrete-year list supplied directly; PubTator3 handles it.
        merged["year"] = raw_year_passthrough
    elif eff_min is not None and eff_min == eff_max:
        # PubTator3 can filter an exact single year server-side.
        merged["year"] = [str(eff_min)]
    elif eff_min is not None or eff_max is not None:
        # Open-ended or multi-year range: PubTator3 has no server-side support,
        # so defer it to a local best-effort window over the returned page.
        local_min, local_max = eff_min, eff_max

    server_filters = json.dumps(merged, separators=(",", ":")) if merged else None
    return SearchFilterPlan(
        server_filters=server_filters,
        local_year_min=local_min,
        local_year_max=local_max,
        warning=warning,
    )


def _resolve_year_window(
    raw_year: Any,
    year_min: int | None,
    year_max: int | None,
) -> tuple[int | None, int | None, list[Any] | None]:
    if raw_year is None:
        return year_min, year_max, None
    if year_min is not None or year_max is not None:
        raise ValueError(
            "filters already contains year; use either filters.year or year_min/year_max"
        )
    window = _coerce_raw_year_window(raw_year)
    if window is None:
        # Caller passed PubTator3's native discrete-year list; honour it as-is.
        return None, None, list(raw_year)
    return window[0], window[1], None


def merge_search_filters(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
) -> str | None:
    """Server-side filters JSON for callers that do not post-filter locally.

    Year *ranges* PubTator3 cannot express server-side are dropped here; prefer
    :func:`build_search_filter_plan` when a local year window must be honoured.
    """
    return build_search_filter_plan(
        filters,
        publication_types,
        year_min,
        year_max,
        ignore_malformed_filters=False,
    ).server_filters


def merge_search_filters_lenient(
    filters: str | None,
    publication_types: list[str] | None,
    year_min: int | None,
    year_max: int | None,
) -> tuple[str | None, str | None]:
    """Like :func:`merge_search_filters` but tolerates malformed raw JSON."""
    plan = build_search_filter_plan(
        filters,
        publication_types,
        year_min,
        year_max,
        ignore_malformed_filters=True,
    )
    return plan.server_filters, plan.warning


def publication_year_of(item: dict[str, Any]) -> int | None:
    """Best-effort publication year for a raw PubTator3 search item.

    Prefers PubTator3's canonical ``date`` field (the field its ``year`` facet is
    derived from) so local filtering matches server-side semantics. Falling back
    to print-date metadata first would reintroduce e-pub vs print-year drift.
    """
    for key in ("date", "meta_date_publication", "pub_date", "pub_year"):
        value = item.get(key)
        if value is None:
            continue
        match = _YEAR_RE.search(str(value))
        if match is not None:
            return int(match.group(1))
    return None


def apply_year_window(
    items: list[dict[str, Any]],
    year_min: int | None,
    year_max: int | None,
) -> list[dict[str, Any]]:
    """Filter items to a year window using canonical-date year extraction."""
    if year_min is None and year_max is None:
        return items
    selected: list[dict[str, Any]] = []
    for item in items:
        year = publication_year_of(item)
        if year is None:
            continue
        if year_min is not None and year < year_min:
            continue
        if year_max is not None and year > year_max:
            continue
        selected.append(item)
    return selected


def _ignored_filters_warning(reason: str) -> str:
    return f"Ignored malformed filters value for MCP search: {reason}"
