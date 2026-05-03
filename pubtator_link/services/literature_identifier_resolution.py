"""Batched identifier resolution helpers for literature services."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DoiResolutionResult:
    """Result from resolving DOI identifiers to PMIDs."""

    resolved: dict[str, str] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    cached_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    timeout_count: int = 0

    @property
    def resolved_count(self) -> int:
        return len(self.resolved)

    @property
    def unresolved_count(self) -> int:
        return len(self.unresolved)


class DoiPmidResolver:
    """Resolve DOI identifiers to PMIDs with positive and negative caching."""

    def __init__(self, *, discovery_service: Any | None) -> None:
        self.discovery_service = discovery_service
        self._pmid_cache: dict[str, str] = {}
        self._unresolved_cache: set[str] = set()

    async def resolve(self, dois: list[str], *, max_ids: int) -> DoiResolutionResult:
        normalized = _dedupe_dois(dois)
        selected = normalized[:max_ids]
        skipped_count = max(0, len(normalized) - len(selected))
        resolved: dict[str, str] = {}
        unresolved: set[str] = set()
        missing: list[str] = []
        cached_count = 0

        for doi in selected:
            cached_pmid = self._pmid_cache.get(doi)
            if cached_pmid is not None:
                resolved[doi] = cached_pmid
                cached_count += 1
                continue
            if doi in self._unresolved_cache:
                unresolved.add(doi)
                cached_count += 1
                continue
            missing.append(doi)

        if not missing:
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
            )

        if self.discovery_service is None:
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
                failed_count=len(missing),
            )

        try:
            response = await self.discovery_service.convert_article_ids(missing, source="doi")
        except TimeoutError:
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
                timeout_count=len(missing),
            )
        except Exception:
            return DoiResolutionResult(
                resolved=resolved,
                unresolved=unresolved,
                cached_count=cached_count,
                skipped_count=skipped_count,
                failed_count=len(missing),
            )

        records = getattr(response, "records", response)
        seen: set[str] = set()
        for record in records:
            input_id = getattr(record, "input_id", None)
            if not input_id:
                continue
            doi = _normalize_doi(input_id)
            if doi not in missing:
                continue
            seen.add(doi)
            pmid = getattr(record, "pmid", None)
            if pmid:
                pmid_text = str(pmid)
                self._pmid_cache[doi] = pmid_text
                resolved[doi] = pmid_text
            else:
                self._unresolved_cache.add(doi)
                unresolved.add(doi)

        for doi in missing:
            if doi in seen:
                continue
            self._unresolved_cache.add(doi)
            unresolved.add(doi)

        return DoiResolutionResult(
            resolved=resolved,
            unresolved=unresolved,
            cached_count=cached_count,
            skipped_count=skipped_count,
        )


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
