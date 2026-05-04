"""Batched identifier resolution helpers for literature services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass(frozen=True)
class DoiResolutionResult:
    """Result from resolving DOI identifiers to PMIDs."""

    resolved: dict[str, str] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    cached_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    timeout_count: int = 0
    resolution_sources: dict[str, str] = field(default_factory=dict)
    provider_result_counts: dict[str, int] = field(default_factory=dict)
    provider_no_match_counts: dict[str, int] = field(default_factory=dict)
    provider_failed_counts: dict[str, int] = field(default_factory=dict)
    provider_timeout_counts: dict[str, int] = field(default_factory=dict)

    @property
    def resolved_count(self) -> int:
        return len(self.resolved)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved)


class DoiPmidResolver:
    """Resolve DOI identifiers to PMIDs with positive and negative caching."""

    def __init__(
        self,
        *,
        discovery_service: Any | None,
        openalex_service: Any | None = None,
        pubmed_service: Any | None = None,
    ) -> None:
        self.discovery_service = discovery_service
        self.openalex_service = openalex_service
        self.pubmed_service = pubmed_service
        self._pmid_cache: dict[str, str] = {}
        self._source_cache: dict[str, str] = {}
        self._unresolved_cache: set[str] = set()
        self._unresolved_no_match_cache: dict[str, dict[str, int]] = {}

    async def resolve(self, dois: list[str], *, max_ids: int) -> DoiResolutionResult:
        normalized = _dedupe_dois(dois)
        selected = normalized[:max_ids]
        skipped_count = max(0, len(normalized) - len(selected))
        resolved: dict[str, str] = {}
        unresolved: set[str] = set()
        missing: list[str] = []
        cached_count = 0
        resolution_sources: dict[str, str] = {}
        provider_result_counts: dict[str, int] = {}
        provider_no_match_counts: dict[str, int] = {}
        provider_failed_counts: dict[str, int] = {}
        provider_timeout_counts: dict[str, int] = {}
        failed_count = 0
        timeout_count = 0

        for doi in selected:
            cached_pmid = self._pmid_cache.get(doi)
            if cached_pmid is not None:
                resolved[doi] = cached_pmid
                source = self._source_cache.get(doi)
                if source is not None:
                    resolution_sources[doi] = source
                    _increment(provider_result_counts, source)
                cached_count += 1
                continue
            if doi in self._unresolved_cache:
                unresolved.add(doi)
                for provider, count in self._unresolved_no_match_cache.get(doi, {}).items():
                    _increment(provider_no_match_counts, provider, count)
                cached_count += 1
                continue
            missing.append(doi)

        if not missing:
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
                resolution_sources=resolution_sources,
                provider_result_counts=provider_result_counts,
                provider_no_match_counts=provider_no_match_counts,
                provider_failed_counts=provider_failed_counts,
                provider_timeout_counts=provider_timeout_counts,
            )

        if (
            self.discovery_service is None
            and self.openalex_service is None
            and self.pubmed_service is None
        ):
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
                failed_count=len(missing),
                resolution_sources=resolution_sources,
                provider_result_counts=provider_result_counts,
                provider_no_match_counts=provider_no_match_counts,
                provider_failed_counts=provider_failed_counts,
                provider_timeout_counts=provider_timeout_counts,
            )

        remaining = list(missing)
        failed_or_timeout: set[str] = set()
        if self.discovery_service is not None and remaining:
            try:
                response = await self.discovery_service.convert_article_ids(
                    remaining,
                    source="doi",
                )
            except (TimeoutError, httpx.TimeoutException):
                timeout_count += len(remaining)
                _increment(provider_timeout_counts, "ncbi_idconv", len(remaining))
                failed_or_timeout.update(remaining)
            except Exception:
                failed_count += len(remaining)
                _increment(provider_failed_counts, "ncbi_idconv", len(remaining))
                failed_or_timeout.update(remaining)
            else:
                provider_resolved = _apply_id_converter_records(
                    response,
                    remaining,
                    resolved,
                    resolution_sources,
                    self._pmid_cache,
                    self._source_cache,
                )
                _increment(provider_result_counts, "ncbi_idconv", len(provider_resolved))
                no_match_count = len(remaining) - len(provider_resolved)
                _increment(provider_no_match_counts, "ncbi_idconv", no_match_count)
                remaining = [doi for doi in remaining if doi not in provider_resolved]

        if self.openalex_service is not None and remaining:
            next_remaining: list[str] = []
            for doi in remaining:
                try:
                    paper = await self.openalex_service.get_work_by_doi(doi)
                except (TimeoutError, httpx.TimeoutException):
                    timeout_count += 1
                    _increment(provider_timeout_counts, "openalex")
                    failed_or_timeout.add(doi)
                    next_remaining.append(doi)
                    continue
                except Exception:
                    failed_count += 1
                    _increment(provider_failed_counts, "openalex")
                    failed_or_timeout.add(doi)
                    next_remaining.append(doi)
                    continue

                pmid = getattr(paper, "pmid", None)
                if pmid:
                    _resolve_doi(
                        doi,
                        str(pmid),
                        "openalex",
                        resolved,
                        resolution_sources,
                        self._pmid_cache,
                        self._source_cache,
                    )
                    _increment(provider_result_counts, "openalex")
                else:
                    _increment(provider_no_match_counts, "openalex")
                    next_remaining.append(doi)
            remaining = next_remaining

        if self.pubmed_service is not None and remaining:
            next_remaining = []
            for doi in remaining:
                try:
                    pmid = await self.pubmed_service.find_pmid_by_doi(doi)
                except (TimeoutError, httpx.TimeoutException):
                    timeout_count += 1
                    _increment(provider_timeout_counts, "pubmed_esearch")
                    failed_or_timeout.add(doi)
                    next_remaining.append(doi)
                    continue
                except Exception:
                    failed_count += 1
                    _increment(provider_failed_counts, "pubmed_esearch")
                    failed_or_timeout.add(doi)
                    next_remaining.append(doi)
                    continue

                if pmid:
                    _resolve_doi(
                        doi,
                        str(pmid),
                        "pubmed_esearch",
                        resolved,
                        resolution_sources,
                        self._pmid_cache,
                        self._source_cache,
                    )
                    _increment(provider_result_counts, "pubmed_esearch")
                else:
                    _increment(provider_no_match_counts, "pubmed_esearch")
                    next_remaining.append(doi)
            remaining = next_remaining

        for doi in remaining:
            if doi not in failed_or_timeout:
                self._unresolved_cache.add(doi)
                self._unresolved_no_match_cache[doi] = _provider_counts_for_doi(
                    provider_no_match_counts
                )
            unresolved.add(doi)

        return DoiResolutionResult(
            resolved=resolved,
            unresolved=unresolved,
            cached_count=cached_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            timeout_count=timeout_count,
            resolution_sources=resolution_sources,
            provider_result_counts=provider_result_counts,
            provider_no_match_counts=provider_no_match_counts,
            provider_failed_counts=provider_failed_counts,
            provider_timeout_counts=provider_timeout_counts,
        )


def _apply_id_converter_records(
    response: Any,
    missing: list[str],
    resolved: dict[str, str],
    resolution_sources: dict[str, str],
    pmid_cache: dict[str, str],
    source_cache: dict[str, str],
) -> set[str]:
    records = getattr(response, "records", response)
    missing_set = set(missing)
    provider_resolved: set[str] = set()
    for record in records:
        input_id = getattr(record, "input_id", None)
        if not input_id:
            continue
        doi = _normalize_doi(input_id)
        if doi not in missing_set:
            continue
        pmid = getattr(record, "pmid", None)
        if not pmid:
            continue
        _resolve_doi(
            doi,
            str(pmid),
            "ncbi_idconv",
            resolved,
            resolution_sources,
            pmid_cache,
            source_cache,
        )
        provider_resolved.add(doi)
    return provider_resolved


def _resolve_doi(
    doi: str,
    pmid: str,
    source: str,
    resolved: dict[str, str],
    resolution_sources: dict[str, str],
    pmid_cache: dict[str, str],
    source_cache: dict[str, str],
) -> None:
    pmid_cache[doi] = pmid
    source_cache[doi] = source
    resolved[doi] = pmid
    resolution_sources[doi] = source


def _provider_counts_for_doi(counts: dict[str, int]) -> dict[str, int]:
    return {provider: 1 for provider, count in counts.items() if count > 0}


def _increment(counts: dict[str, int], key: str, amount: int = 1) -> None:
    if amount <= 0:
        return
    counts[key] = counts.get(key, 0) + amount


def _dedupe_dois(dois: list[str]) -> list[str]:
    """Normalize and deduplicate DOI strings while preserving first occurrence order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for doi in dois:
        normalized = _normalize_doi(doi)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _normalize_doi(doi: str) -> str:
    clean = doi.strip()
    if clean.casefold().startswith("doi:"):
        clean = clean[4:].strip()
    return clean.casefold()
