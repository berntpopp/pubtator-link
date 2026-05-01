from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    PreparationStatus,
    ResolverAttemptSummary,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
    SourceCoverage,
)


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except KeyError:
        return default


def _filter_or_none(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    return list(values)


def _preparation_status_from_row(row: Mapping[str, Any] | None) -> PreparationStatus:
    if row is None:
        return PreparationStatus()
    return PreparationStatus(
        queued=int(row["queued"] or 0),
        running=int(row["running"] or 0),
        complete=int(row["complete"] or 0),
        partial=int(row["partial"] or 0),
        failed=int(row["failed"] or 0),
    )


def _passage_from_row(row: Mapping[str, Any]) -> ReviewPassageRow:
    source_metadata = row["source_metadata"]
    if isinstance(source_metadata, str):
        source_metadata = json.loads(source_metadata)
    return ReviewPassageRow(
        passage_id=row["passage_id"],
        review_id=row["review_id"],
        source_id=row["source_id"],
        source_kind=row["source_kind"],
        pmid=row["pmid"],
        pmcid=row["pmcid"],
        doi=row["doi"],
        url=row["url"],
        section=row["section"],
        heading_path=row["heading_path"],
        page=row["page"],
        text=row["text"],
        entity_ids=list(row["entity_ids"] or []),
        relation_types=list(row["relation_types"] or []),
        screening_status=row["screening_status"],
        source_metadata=source_metadata,
        lexical_rank=float(row["lexical_rank"] or 0.0),
    )


def _source_summary_from_row(row: Mapping[str, Any]) -> ReviewSourceSummary:
    attempt_statuses = list(row["attempt_statuses"] or [])
    sections = list(row["sections"] or [])
    resolver_attempts = _resolver_attempts_from_value(_get(row, "resolver_attempts"))
    return ReviewSourceSummary(
        source_id=row["source_id"],
        pmid=row["pmid"],
        source_kind=row["source_kind"],
        job_status=row["job_status"],
        error=row["error"],
        attempt_statuses=attempt_statuses,
        sections=sections,
        passage_count=int(row["passage_count"] or 0),
        char_count=int(row["char_count"] or 0),
        coverage=_infer_source_coverage(
            source_kind=row["source_kind"],
            sections=sections,
            attempt_statuses=attempt_statuses,
        ),
        coverage_reason=_get(row, "coverage_reason") or "unknown",
        pmcid=_get(row, "pmcid"),
        doi=_get(row, "doi"),
        license_or_access_hint=_get(row, "license_or_access_hint"),
        pmc_fallback_available=bool(_get(row, "pmc_fallback_available", False)),
        resolver_attempts=resolver_attempts,
    )


def _infer_source_coverage(
    *,
    source_kind: str,
    sections: Sequence[str],
    attempt_statuses: Sequence[str],
) -> SourceCoverage:
    if source_kind in {"curated_pdf", "curated_html", "docling_pdf"}:
        return "curated_url"
    lowered_sections = {section.strip().lower() for section in sections}
    lowered_attempts = " ".join(attempt_statuses).lower()
    if any(section not in {"title", "abstract"} for section in lowered_sections):
        return "full_text"
    if "full_text" in lowered_attempts and "success" in lowered_attempts:
        return "full_text"
    if "abstract" in lowered_sections:
        return "abstract_only"
    if "title" in lowered_sections:
        return "title_only"
    return "unknown"


def _failed_source_summary_from_row(row: Mapping[str, Any]) -> FailedSourceSummary:
    return FailedSourceSummary(
        source_id=row["source_id"],
        pmid=row["pmid"],
        source_kind=row["source_kind"],
        job_status=row["job_status"],
        error=row["error"],
        attempt_statuses=list(row["attempt_statuses"] or []),
        coverage_reason=_get(row, "coverage_reason") or "unknown",
        pmcid=_get(row, "pmcid"),
        doi=_get(row, "doi"),
        license_or_access_hint=_get(row, "license_or_access_hint"),
        pmc_fallback_available=bool(_get(row, "pmc_fallback_available", False)),
        resolver_attempts=_resolver_attempts_from_value(_get(row, "resolver_attempts")),
    )


def _resolver_attempts_from_value(value: Any) -> list[ResolverAttemptSummary]:
    if not value:
        return []
    if isinstance(value, str):
        value = json.loads(value)
    attempts = []
    for item in value:
        if item is None:
            continue
        if isinstance(item, str):
            item = json.loads(item)
        attempts.append(ResolverAttemptSummary.model_validate(item))
    return attempts


def _passage_sample_from_row(row: Mapping[str, Any]) -> ReviewPassageSample:
    return ReviewPassageSample(
        passage_id=row["passage_id"],
        section=row["section"],
        text=row["text"],
        char_count=int(row["char_count"] or 0),
    )


def _review_index_totals_from_row(row: Mapping[str, Any] | None) -> ReviewIndexTotals:
    if row is None:
        return ReviewIndexTotals()
    return ReviewIndexTotals(
        pmid_count=int(row["pmid_count"] or 0),
        source_count=int(row["source_count"] or 0),
        passage_count=int(row["passage_count"] or 0),
        char_count=int(row["char_count"] or 0),
        failed_source_count=int(row["failed_source_count"] or 0),
    )


def _parse_execute_count(result: str) -> int:
    match = re.search(r"(\d+)$", result)
    if match is None:
        return 0
    return int(match.group(1))


def _recall_tsquery(query: str) -> str:
    tokens = []
    seen: set[str] = set()
    for token in re.findall(r"[a-zA-Z0-9]+", query.lower()):
        if len(token) < 3 or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= 12:
            break
    return " | ".join(tokens) or "review"
