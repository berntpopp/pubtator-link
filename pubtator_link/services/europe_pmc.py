"""Optional Europe PMC open-access lookup helper."""

from __future__ import annotations

import httpx
from pydantic import BaseModel


class EuropePmcLookupResult(BaseModel):
    available: bool
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    full_text_url: str | None = None
    reason: str = "unknown"


class EuropePmcClient:
    def __init__(self, *, http_client: httpx.AsyncClient, base_url: str) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")

    async def lookup_open_access_record(self, pmcid_or_pmid: str) -> EuropePmcLookupResult:
        response = await self.http_client.get(
            f"{self.base_url}/search",
            params={"query": pmcid_or_pmid, "format": "json", "resultType": "core"},
        )
        if response.status_code == 404:
            return EuropePmcLookupResult(available=False, reason="upstream_404")
        response.raise_for_status()
        payload = response.json()
        records = payload.get("resultList", {}).get("result", [])
        if not records:
            return EuropePmcLookupResult(available=False, reason="not_found")
        record = records[0]
        if str(record.get("isOpenAccess", "")).upper() != "Y":
            return EuropePmcLookupResult(
                available=False,
                pmcid=record.get("pmcid"),
                doi=record.get("doi"),
                reason="license_reuse_unavailable",
            )
        urls = record.get("fullTextUrlList", {}).get("fullTextUrl", [])
        full_text_url = next((item.get("url") for item in urls if item.get("url")), None)
        return EuropePmcLookupResult(
            available=full_text_url is not None,
            pmcid=record.get("pmcid"),
            doi=record.get("doi"),
            license_or_access_hint=record.get("license") or "open_access",
            full_text_url=full_text_url,
            reason="full_text_available" if full_text_url else "parser_unsupported",
        )

    async def fetch_full_text_xml(self, url: str) -> str:
        response = await self.http_client.get(url)
        response.raise_for_status()
        return response.text
