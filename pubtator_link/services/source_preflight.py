from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pubtator_link.api.client import PubTator3Client
from pubtator_link.models.review_rerag import (
    CoverageReason,
    ResolverAttemptSummary,
    SourceCoverageHint,
)

IdConverter = Callable[[str], Awaitable[Mapping[str, str | None]]]
PmcProbe = Callable[[str], Awaitable[bool]]
AbstractProbe = Callable[[str], Awaitable[bool]]
PRE_RESOLUTION_BEST_GUESS_NOTE = (
    "PMCID conversion failed before coverage resolution; coverage is a pre-resolution best guess."
)


class SourcePreflightService:
    """Estimate source coverage before review evidence preparation."""

    def __init__(
        self,
        *,
        id_converter: IdConverter | None = None,
        pmc_bioc_available: PmcProbe | None = None,
        pubtator_abstract_available: AbstractProbe | None = None,
        preflight_concurrency: int = 3,
        europe_pmc_client: Any | None = None,
    ) -> None:
        self._id_converter = id_converter or self._no_id_conversion
        self._pmc_bioc_available = pmc_bioc_available or self._no_pmc_bioc
        self._pubtator_abstract_available = (
            pubtator_abstract_available or self._no_pubtator_abstract
        )
        self.preflight_concurrency = preflight_concurrency
        self.europe_pmc_client = europe_pmc_client

    @classmethod
    def from_pubtator_client(
        cls,
        client: PubTator3Client,
        *,
        id_converter: IdConverter | None = None,
        preflight_concurrency: int = 3,
        europe_pmc_client: Any | None = None,
    ) -> SourcePreflightService:
        async def abstract_available(pmid: str) -> bool:
            response = await client.export_publications([pmid], format="biocjson", full=False)
            documents = response.get("documents", [])
            return bool(documents)

        async def pmc_available(pmcid: str) -> bool:
            response = await client.export_pmc_publications([pmcid], format="biocjson")
            documents = response.get("documents", [])
            return bool(documents)

        return cls(
            id_converter=id_converter,
            pmc_bioc_available=pmc_available,
            pubtator_abstract_available=abstract_available,
            preflight_concurrency=preflight_concurrency,
            europe_pmc_client=europe_pmc_client,
        )

    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
        indexed_pmids = list(dict.fromkeys(pmids))
        semaphore = asyncio.Semaphore(self.preflight_concurrency)

        async def preflight_one(index: int, pmid: str) -> tuple[int, SourceCoverageHint]:
            async with semaphore:
                return index, await self._preflight_one_pmid(pmid)

        results = await asyncio.gather(
            *(preflight_one(index, pmid) for index, pmid in enumerate(indexed_pmids))
        )
        return [hint for _, hint in sorted(results, key=lambda item: item[0])]

    async def _preflight_one_pmid(self, pmid: str) -> SourceCoverageHint:
        id_resolution_attempts: list[ResolverAttemptSummary] = []
        try:
            metadata = dict(await self._id_converter(pmid))
        except TimeoutError:
            return SourceCoverageHint(
                pmid=pmid,
                coverage_reason="upstream_timeout",
                resolver_attempts=[
                    ResolverAttemptSummary(
                        source_kind="pmc_id_converter",
                        status="failed",
                        pmid=pmid,
                        terminal_reason="upstream_timeout",
                    )
                ],
            )
        except Exception:
            metadata = {}
            id_resolution_attempts.append(
                ResolverAttemptSummary(
                    source_kind="pmc_id_converter",
                    status="failed",
                    pmid=pmid,
                    terminal_reason="unknown",
                )
            )

        pmcid = metadata.get("pmcid")
        doi = metadata.get("doi")
        license_or_access_hint = metadata.get("license_or_access_hint")
        id_resolution_failed = (
            not pmcid and metadata.get("id_resolution_status") in {"unresolved", "failed"}
        ) or bool(id_resolution_attempts)
        best_guess_notes = [PRE_RESOLUTION_BEST_GUESS_NOTE] if id_resolution_failed else []
        if id_resolution_failed and not id_resolution_attempts:
            id_resolution_attempts.append(
                ResolverAttemptSummary(
                    source_kind="pmc_id_converter",
                    status="not_available",
                    pmid=pmid,
                    terminal_reason=metadata.get("id_resolution_reason")
                    or "pre_resolution_best_guess",
                )
            )

        if pmcid:
            try:
                if await self._pmc_bioc_available(pmcid):
                    return SourceCoverageHint(
                        pmid=pmid,
                        expected_coverage="full_text",
                        expected_coverage_after_index="full_text",
                        expected_coverage_confidence="high",
                        coverage_resolution_stage="preflight_resolver_chain",
                        coverage_reason="pmc_oa_bioc",
                        pmcid=pmcid,
                        doi=doi,
                        license_or_access_hint=license_or_access_hint,
                        pmc_fallback_available=True,
                        resolver_attempts=[
                            ResolverAttemptSummary(
                                source_kind="pmc_bioc",
                                status="success",
                                pmid=pmid,
                                pmcid=pmcid,
                                doi=doi,
                            )
                        ],
                    )
            except TimeoutError:
                return SourceCoverageHint(
                    pmid=pmid,
                    coverage_reason="upstream_timeout",
                    pmcid=pmcid,
                    doi=doi,
                    license_or_access_hint=license_or_access_hint,
                    resolver_attempts=[
                        ResolverAttemptSummary(
                            source_kind="pmc_bioc",
                            status="failed",
                            pmid=pmid,
                            pmcid=pmcid,
                            doi=doi,
                            terminal_reason="upstream_timeout",
                        )
                    ],
                )

        if self.europe_pmc_client is not None:
            europe_pmc_result = await self.europe_pmc_client.lookup_open_access_record(
                pmcid or pmid
            )
            if europe_pmc_result.available:
                return SourceCoverageHint(
                    pmid=pmid,
                    expected_coverage="full_text",
                    expected_coverage_after_index="full_text",
                    expected_coverage_confidence="high",
                    coverage_resolution_stage="preflight_resolver_chain",
                    coverage_reason="full_text_available",
                    pmcid=europe_pmc_result.pmcid or pmcid,
                    doi=europe_pmc_result.doi or doi,
                    license_or_access_hint=europe_pmc_result.license_or_access_hint,
                    pmc_fallback_available=True,
                    resolver_attempts=[
                        ResolverAttemptSummary(
                            source_kind="europe_pmc_jats",
                            status="success",
                            pmid=pmid,
                            pmcid=europe_pmc_result.pmcid or pmcid,
                            doi=europe_pmc_result.doi or doi,
                            url=europe_pmc_result.full_text_url,
                        )
                    ],
                )

        try:
            if await self._pubtator_abstract_available(pmid):
                coverage_reason: CoverageReason = "abstract_fallback_used" if pmcid else "no_pmcid"
                if (
                    id_resolution_failed
                    and not pmcid
                    and metadata.get("id_resolution_reason") != "no_pmcid"
                ):
                    coverage_reason = "pre_resolution_best_guess"
                return SourceCoverageHint(
                    pmid=pmid,
                    expected_coverage="abstract_only",
                    expected_coverage_after_index="abstract_only",
                    expected_coverage_confidence="moderate",
                    coverage_resolution_stage="preflight_resolver_chain",
                    coverage_reason=coverage_reason,
                    pmcid=pmcid,
                    doi=doi,
                    license_or_access_hint=license_or_access_hint,
                    pmc_fallback_available=False,
                    notes=best_guess_notes,
                    resolver_attempts=[
                        *id_resolution_attempts,
                        ResolverAttemptSummary(
                            source_kind="pubtator_abstract",
                            status="success",
                            pmid=pmid,
                            pmcid=pmcid,
                            doi=doi,
                        ),
                    ],
                )
        except TimeoutError:
            return SourceCoverageHint(
                pmid=pmid,
                coverage_reason="upstream_timeout",
                pmcid=pmcid,
                doi=doi,
                license_or_access_hint=license_or_access_hint,
                resolver_attempts=[
                    ResolverAttemptSummary(
                        source_kind="pubtator_abstract",
                        status="failed",
                        pmid=pmid,
                        pmcid=pmcid,
                        doi=doi,
                        terminal_reason="upstream_timeout",
                    )
                ],
            )

        final_coverage_reason: CoverageReason = "pmc_not_open_access" if pmcid else "no_pmcid"
        if not pmcid and id_resolution_failed:
            final_coverage_reason = "pre_resolution_best_guess"
        return SourceCoverageHint(
            pmid=pmid,
            coverage_reason=final_coverage_reason,
            pmcid=pmcid,
            doi=doi,
            license_or_access_hint=license_or_access_hint,
            notes=best_guess_notes,
            resolver_attempts=id_resolution_attempts,
        )

    @staticmethod
    async def _no_id_conversion(_pmid: str) -> Mapping[str, Any]:
        return {}

    @staticmethod
    async def _no_pmc_bioc(_pmcid: str) -> bool:
        return False

    @staticmethod
    async def _no_pubtator_abstract(_pmid: str) -> bool:
        return False
