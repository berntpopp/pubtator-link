from __future__ import annotations

import asyncio

import pytest

from pubtator_link.services.source_preflight import SourcePreflightService


class FakeEuropePmcClient:
    def __init__(self, *, available: bool) -> None:
        self.available = available
        self.calls: list[str] = []

    async def lookup_open_access_record(self, pmcid_or_pmid: str):
        from pubtator_link.services.europe_pmc import EuropePmcLookupResult

        self.calls.append(pmcid_or_pmid)
        return EuropePmcLookupResult(
            available=self.available,
            pmcid="PMC123" if self.available else None,
            license_or_access_hint="CC BY" if self.available else None,
            full_text_url="https://example.org/full.xml" if self.available else None,
            reason="full_text_available" if self.available else "not_found",
        )


@pytest.mark.asyncio
async def test_preflight_reports_full_text_when_pmc_bioc_is_available() -> None:
    async def id_converter(pmid: str) -> dict[str, str]:
        return {"pmcid": "PMC123", "doi": f"10.1000/{pmid}", "license_or_access_hint": "oa"}

    async def pmc_bioc_available(_pmcid: str) -> bool:
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pmc_bioc_available=pmc_bioc_available,
    )

    hints = await service.preflight_pmids(["40234174"])

    assert hints[0].expected_coverage == "full_text"
    assert hints[0].coverage_reason == "full_text_available"
    assert hints[0].pmcid == "PMC123"
    assert hints[0].doi == "10.1000/40234174"
    assert hints[0].pmc_fallback_available is True


@pytest.mark.asyncio
async def test_preflight_uses_abstract_hint_when_no_pmcid_exists() -> None:
    async def id_converter(_pmid: str) -> dict[str, str]:
        return {}

    async def pubtator_abstract_available(_pmid: str) -> bool:
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pubtator_abstract_available=pubtator_abstract_available,
    )

    hints = await service.preflight_pmids(["40234174"])

    assert hints[0].expected_coverage == "abstract_only"
    assert hints[0].coverage_reason == "no_pmcid"
    assert hints[0].pmc_fallback_available is False


@pytest.mark.asyncio
async def test_preflight_reports_europe_pmc_fallback_when_enabled() -> None:
    europe_pmc = FakeEuropePmcClient(available=True)
    service = SourcePreflightService(europe_pmc_client=europe_pmc)

    hints = await service.preflight_pmids(["40234174"])

    assert hints[0].expected_coverage == "full_text"
    assert hints[0].pmc_fallback_available is True
    assert hints[0].license_or_access_hint == "CC BY"
    assert any(attempt.source_kind == "europe_pmc_jats" for attempt in hints[0].resolver_attempts)
    assert europe_pmc.calls == ["40234174"]


@pytest.mark.asyncio
async def test_preflight_skips_europe_pmc_when_client_is_absent() -> None:
    hints = await SourcePreflightService().preflight_pmids(["40234174"])

    assert hints[0].resolver_attempts == []
    assert hints[0].pmc_fallback_available is False


@pytest.mark.asyncio
async def test_preflight_isolates_upstream_timeout_as_failed_attempt() -> None:
    async def id_converter(_pmid: str) -> dict[str, str]:
        raise TimeoutError("id converter timed out")

    service = SourcePreflightService(id_converter=id_converter)

    hints = await service.preflight_pmids(["40234174"])

    assert hints[0].expected_coverage == "unknown"
    assert hints[0].coverage_reason == "upstream_timeout"
    assert len(hints[0].resolver_attempts) == 1
    assert hints[0].resolver_attempts[0].source_kind == "pmc_id_converter"
    assert hints[0].resolver_attempts[0].status == "failed"


@pytest.mark.asyncio
async def test_preflight_limits_concurrent_pmid_probes() -> None:
    in_flight = 0
    max_in_flight = 0

    async def id_converter(_pmid: str) -> dict[str, str]:
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return {}

    async def abstract_available(_pmid: str) -> bool:
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pubtator_abstract_available=abstract_available,
        preflight_concurrency=2,
    )

    hints = await service.preflight_pmids(["1", "2", "3", "4"])

    assert [hint.pmid for hint in hints] == ["1", "2", "3", "4"]
    assert max_in_flight == 2
