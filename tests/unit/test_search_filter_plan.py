"""Regression tests for the PubTator3 search filter contract.

PubTator3's ``/search/`` ``filters`` parameter (empirically verified against the
live API) accepts ``type``/``journal``/``year`` as ``{field: [values]}`` where
multiple list values are AND-combined, and ``year`` takes only discrete year
strings. Range objects such as ``{"year":{"min":2020}}`` are rejected with an
HTTP 400 whose body misleadingly reads "We are currently updating the Database".

These tests pin the encoding so we never regress to the range form that silently
forced every year-filtered search into the local best-effort fallback.
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from pubtator_link.api.search_filters import (
    SearchFilterPlan,
    apply_year_window,
    build_search_filter_plan,
    publication_year_of,
)


def _server(filters=None, publication_types=None, year_min=None, year_max=None) -> dict | None:
    plan = build_search_filter_plan(
        filters=filters,
        publication_types=publication_types,
        year_min=year_min,
        year_max=year_max,
        ignore_malformed_filters=False,
    )
    return None if plan.server_filters is None else json.loads(plan.server_filters)


def test_exact_single_year_goes_server_side_as_discrete_list() -> None:
    plan = build_search_filter_plan(
        filters=None,
        publication_types=None,
        year_min=2021,
        year_max=2021,
        ignore_malformed_filters=False,
    )
    assert json.loads(plan.server_filters) == {"year": ["2021"]}
    assert not plan.has_local_year_window


def test_open_ended_year_min_becomes_local_window() -> None:
    plan = build_search_filter_plan(
        filters=None,
        publication_types=None,
        year_min=2020,
        year_max=None,
        ignore_malformed_filters=False,
    )
    # No unsupported range object is ever sent to PubTator3.
    assert plan.server_filters is None
    assert plan.local_year_min == 2020
    assert plan.local_year_max is None
    assert plan.has_local_year_window


def test_multi_year_range_keeps_type_server_side_year_local() -> None:
    plan = build_search_filter_plan(
        filters=None,
        publication_types=["Review"],
        year_min=2020,
        year_max=2026,
        ignore_malformed_filters=False,
    )
    assert json.loads(plan.server_filters) == {"type": ["Review"]}
    assert (plan.local_year_min, plan.local_year_max) == (2020, 2026)


def test_no_year_range_object_is_ever_emitted() -> None:
    for server in (
        _server(year_min=2020, year_max=2026),
        _server(year_min=2020),
        _server(filters='{"year":{"min":2020,"max":2024}}'),
    ):
        assert server is None or "min" not in json.dumps(server)
        assert server is None or not isinstance(server.get("year"), dict)


def test_raw_year_range_filter_resolves_like_flat_args() -> None:
    plan = build_search_filter_plan(
        filters='{"year":{"min":2022,"max":2022}}',
        publication_types=None,
        year_min=None,
        year_max=None,
        ignore_malformed_filters=False,
    )
    assert json.loads(plan.server_filters) == {"year": ["2022"]}


def test_native_discrete_year_list_passes_through_server_side() -> None:
    plan = build_search_filter_plan(
        filters='{"year":["2020"]}',
        publication_types=None,
        year_min=None,
        year_max=None,
        ignore_malformed_filters=False,
    )
    assert json.loads(plan.server_filters) == {"year": ["2020"]}
    assert not plan.has_local_year_window


def test_journal_filter_preserved_server_side() -> None:
    assert _server(filters='{"journal":["PLoS One"]}') == {"journal": ["PLoS One"]}


def test_year_window_uses_canonical_date_not_print_year() -> None:
    # PubTator3's year facet derives from the canonical ``date`` field. An item
    # whose e-pub ``date`` is 2020 but whose print ``meta_date_publication`` is
    # 2019 must be treated as 2020 to match server-side semantics.
    item = {"date": "2020-01-04T00:00:00Z", "meta_date_publication": "2019 Dec 28"}
    assert publication_year_of(item) == 2020
    kept = apply_year_window([item], year_min=2020, year_max=None)
    assert kept == [item]


def test_year_window_excludes_unknown_year_when_bounded() -> None:
    item = {"title": "no date here"}
    assert apply_year_window([item], year_min=2020, year_max=None) == []


def test_year_window_noop_without_bounds() -> None:
    items = [{"date": "1999-01-01T00:00:00Z"}]
    assert apply_year_window(items, year_min=None, year_max=None) == items


def test_plan_is_frozen_dataclass() -> None:
    plan = SearchFilterPlan(server_filters=None, local_year_min=None, local_year_max=None)
    with pytest.raises(FrozenInstanceError):
        plan.server_filters = "x"  # type: ignore[misc]
