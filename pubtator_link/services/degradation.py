"""Shared degraded-mode helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

DegradedMode = Literal["abstract_only", "metadata_only", "index_unavailable"]


def degraded_mode_from_coverage(coverage_by_pmid: Mapping[str, str]) -> DegradedMode | None:
    """Return the most severe user-visible degraded mode for source coverage."""
    values = set(coverage_by_pmid.values())
    if not values:
        return None
    if values <= {"full_text"}:
        return None
    if "title_only" in values or "unknown" in values:
        return "metadata_only"
    if "abstract_only" in values:
        return "abstract_only"
    return None
