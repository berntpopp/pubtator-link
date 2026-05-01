from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pubtator_link.api.client import PubTator3Client
from pubtator_link.models.review_rerag import ResolverAttemptSummary, SourceCoverageHint

IdConverter = Callable[[str], Awaitable[Mapping[str, str | None]]]
PmcProbe = Callable[[str], Awaitable[bool]]
AbstractProbe = Callable[[str], Awaitable[bool]]


class SourcePreflightService:
    """Estimate source coverage before review evidence preparation."""

    def __init__(
        self,
        *,
        id_converter: IdConverter | None = None,
        pmc_bioc_available: PmcProbe | None = None,
        pubtator_abstract_available: AbstractProbe | None = None,
    ) -> None:
        self._id_converter = id_converter or self._no_id_conversion
        self._pmc_bioc_available = pmc_bioc_available or self._no_pmc_bioc
        self._pubtator_abstract_available = (
            pubtator_abstract_available or self._no_pubtator_abstract
        )

    @classmethod
    def from_pubtator_client(cls, client: PubTator3Client) -> SourcePreflightService:
        async def abstract_available(pmid: str) -> bool:
            response = await client.export_publications([pmid], format="biocjson", full=False)
            documents = response.get("documents", [])
            return bool(documents)

        async def pmc_available(pmcid: str) -> bool:
            response = await client.export_pmc_publications([pmcid], format="biocjson")
            documents = response.get("documents", [])
            return bool(documents)

        return cls(
            pmc_bioc_available=pmc_available,
            pubtator_abstract_available=abstract_available,
        )

    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
        indexed_pmids = list(dict.fromkeys(pmids))
        results: list[tuple[int, SourceCoverageHint]] = []
        for index, pmid in enumerate(indexed_pmids):
            hint = await self._preflight_one_pmid(pmid)
            results.append((index, hint))
        return [hint for _, hint in sorted(results, key=lambda item: item[0])]

    async def _preflight_one_pmid(self, pmid: str) -> SourceCoverageHint:
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
            return SourceCoverageHint(
                pmid=pmid,
                coverage_reason="unknown",
                resolver_attempts=[
                    ResolverAttemptSummary(
                        source_kind="pmc_id_converter",
                        status="failed",
                        pmid=pmid,
                        terminal_reason="unknown",
                    )
                ],
            )

        pmcid = metadata.get("pmcid")
        doi = metadata.get("doi")
        license_or_access_hint = metadata.get("license_or_access_hint")
        if pmcid:
            try:
                if await self._pmc_bioc_available(pmcid):
                    return SourceCoverageHint(
                        pmid=pmid,
                        expected_coverage="full_text",
                        coverage_reason="full_text_available",
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

        try:
            if await self._pubtator_abstract_available(pmid):
                return SourceCoverageHint(
                    pmid=pmid,
                    expected_coverage="abstract_only",
                    coverage_reason="no_pmcid" if not pmcid else "abstract_fallback_used",
                    pmcid=pmcid,
                    doi=doi,
                    license_or_access_hint=license_or_access_hint,
                    pmc_fallback_available=False,
                    resolver_attempts=[
                        ResolverAttemptSummary(
                            source_kind="pubtator_abstract",
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
                        source_kind="pubtator_abstract",
                        status="failed",
                        pmid=pmid,
                        pmcid=pmcid,
                        doi=doi,
                        terminal_reason="upstream_timeout",
                    )
                ],
            )

        return SourceCoverageHint(
            pmid=pmid,
            coverage_reason="no_pmcid" if not pmcid else "pmc_not_open_access",
            pmcid=pmcid,
            doi=doi,
            license_or_access_hint=license_or_access_hint,
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
