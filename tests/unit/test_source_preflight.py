from __future__ import annotations

import pytest

from pubtator_link.services.source_preflight import SourcePreflightService


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
