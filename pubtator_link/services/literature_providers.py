"""Provider clients for literature graph metadata and availability."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

from pubtator_link.api.retry import RetryPolicy, call_with_retries
from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteratureGraphProvenance,
    LiteraturePaper,
    ProviderWarning,
)

CROSSREF_PROVIDER = "crossref"
EUROPE_PMC_PROVIDER = "europe_pmc"
OPENALEX_PROVIDER = "openalex"
UNPAYWALL_PROVIDER = "unpaywall"
PROVIDER_DISABLED = "provider_disabled"


class CrossrefClient:
    """Small Crossref Works API client."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.crossref.org",
        mailto: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_work(self, doi: str) -> dict[str, Any]:
        params: dict[str, str] = {}
        if self.mailto:
            params["mailto"] = self.mailto
        encoded_doi = quote(doi, safe="")
        url = f"{self.base_url}/works/{encoded_doi}"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    def references_from_work(self, work: Mapping[str, Any]) -> list[LiteraturePaper]:
        message = work.get("message", work)
        if not isinstance(message, Mapping):
            return []
        references = message.get("reference", [])
        if not isinstance(references, Sequence) or isinstance(references, str | bytes):
            return []

        papers: list[LiteraturePaper] = []
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            doi = _optional_str(reference.get("DOI") or reference.get("doi"))
            title = _optional_str(
                reference.get("article-title")
                or reference.get("volume-title")
                or reference.get("unstructured")
            )
            paper = LiteraturePaper(
                doi=doi,
                title=title,
                journal=_optional_str(reference.get("journal-title")),
                year=_optional_int(reference.get("year")),
                status="resolved_metadata_only" if doi else "unresolved_reference",
                provenance=[
                    LiteratureGraphProvenance(
                        provider=CROSSREF_PROVIDER,
                        source_id=_optional_str(message.get("DOI")),
                    )
                ],
            )
            papers.append(paper)
        return papers


class EuropePmcLiteratureClient:
    """Europe PMC literature metadata client."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://www.ebi.ac.uk/europepmc/webservices/rest",
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        url = f"{self.base_url}/MED/{pmid}/citations"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(
                url,
                params={"format": "json", "pageSize": str(limit)},
            ),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            return []
        citation_list = payload.get("citationList")
        if isinstance(citation_list, Mapping):
            results = citation_list.get("citation", [])
        else:
            result_list = payload.get("resultList")
            results = result_list.get("result", []) if isinstance(result_list, Mapping) else []
        if not isinstance(results, Sequence) or isinstance(results, str | bytes):
            return []
        return [_paper_from_europe_pmc(item) for item in results if isinstance(item, Mapping)][
            :limit
        ]


class OpenAlexClient:
    """OpenAlex Works API client."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.openalex.org",
        mailto: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        payload = await self._get_work_payload_by_doi(doi)
        return _paper_from_openalex(payload)

    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        payload = await self._get_work_payload_by_doi(doi)
        source_id = _optional_str(payload.get("id"))
        referenced_works = payload.get("referenced_works", [])
        if not isinstance(referenced_works, Sequence) or isinstance(referenced_works, str | bytes):
            return []
        return [
            LiteraturePaper(
                openalex_id=_optional_str(work_id),
                status="unresolved_reference",
                provenance=[
                    LiteratureGraphProvenance(
                        provider=OPENALEX_PROVIDER,
                        source_id=source_id,
                    )
                ],
            )
            for work_id in referenced_works[:limit]
            if _optional_str(work_id)
        ]

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        payload = await self._get_work_payload_by_doi(doi)
        cited_by_api_url = _optional_str(payload.get("cited_by_api_url"))
        params: dict[str, str] = {"per-page": str(limit)}
        if self.mailto:
            params["mailto"] = self.mailto
        if cited_by_api_url:
            url = cited_by_api_url
        else:
            source_work_id = _openalex_work_filter_id(_optional_str(payload.get("id")))
            if not source_work_id:
                return []
            url = f"{self.base_url}/works"
            params["filter"] = f"cites:{source_work_id}"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        cited_payload = response.json()
        if not isinstance(cited_payload, Mapping):
            return []
        results = cited_payload.get("results", [])
        if not isinstance(results, Sequence) or isinstance(results, str | bytes):
            return []
        return [_paper_from_openalex(item) for item in results if isinstance(item, Mapping)][:limit]

    async def _get_work_payload_by_doi(self, doi: str) -> Mapping[str, Any]:
        params: dict[str, str] = {}
        if self.mailto:
            params["mailto"] = self.mailto
        encoded_doi = quote(f"https://doi.org/{doi}", safe="")
        response, _metadata = await call_with_retries(
            lambda: self._client.get(f"{self.base_url}/works/{encoded_doi}", params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, Mapping) else {}


class UnpaywallClient:
    """Optional Unpaywall availability client."""

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = "https://api.unpaywall.org/v2",
        email: str | None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_availability(self, doi: str) -> LiteratureAvailability | ProviderWarning:
        if not self.email:
            return ProviderWarning(
                provider=UNPAYWALL_PROVIDER,
                status=PROVIDER_DISABLED,
                retryable=False,
                message="Unpaywall email is not configured.",
            )
        response, _metadata = await call_with_retries(
            lambda: self._client.get(
                f"{self.base_url}/{quote(doi, safe='')}",
                params={"email": self.email},
            ),
            policy=self.retry_policy,
        )
        if response.status_code == 404:
            return ProviderWarning(
                provider=UNPAYWALL_PROVIDER,
                status="provider_no_match",
                retryable=False,
                message="No Unpaywall record for DOI.",
            )
        response.raise_for_status()
        payload = response.json()
        return _availability_from_unpaywall(payload if isinstance(payload, Mapping) else {})

    async def get_oa_status(self, doi: str) -> LiteratureAvailability | ProviderWarning:
        return await self.get_availability(doi)


def _paper_from_europe_pmc(item: Mapping[str, Any]) -> LiteraturePaper:
    source = _optional_str(item.get("source"))
    pmid = _optional_str(item.get("pmid"))
    if pmid is None and source == "MED":
        pmid = _optional_str(item.get("id"))
    return LiteraturePaper(
        pmid=pmid,
        doi=_optional_str(item.get("doi")),
        pmcid=_optional_str(item.get("pmcid")),
        title=_optional_str(item.get("title")),
        journal=_optional_str(item.get("journalTitle") or item.get("journalAbbreviation")),
        year=_optional_int(item.get("pubYear")),
        availability=LiteratureAvailability(
            has_pmc_full_text=_is_truthy_flag(item.get("inPMC")),
            is_open_access=_is_truthy_flag(item.get("isOpenAccess")),
            has_pdf=_is_truthy_flag(item.get("hasPDF")),
        ),
        status="resolved_full_text_candidate"
        if _is_truthy_flag(item.get("isOpenAccess")) or _is_truthy_flag(item.get("inPMC"))
        else "resolved_metadata_only",
        provenance=[
            LiteratureGraphProvenance(
                provider=EUROPE_PMC_PROVIDER,
                source_id=pmid or _optional_str(item.get("id")),
            )
        ],
    )


def _paper_from_openalex(item: Mapping[str, Any]) -> LiteraturePaper:
    ids = item.get("ids")
    ids_mapping = ids if isinstance(ids, Mapping) else {}
    open_access = item.get("open_access")
    open_access_mapping = open_access if isinstance(open_access, Mapping) else {}
    return LiteraturePaper(
        pmid=_pmid_from_url(_optional_str(item.get("pmid") or ids_mapping.get("pmid"))),
        doi=_doi_from_url(_optional_str(item.get("doi") or ids_mapping.get("doi"))),
        openalex_id=_optional_str(item.get("id")),
        title=_optional_str(item.get("title")),
        journal=_openalex_journal(item),
        year=_optional_int(item.get("publication_year")),
        authors=_openalex_authors(item.get("authorships")),
        availability=LiteratureAvailability(
            is_open_access=bool(open_access_mapping.get("is_oa")),
            oa_status=_optional_str(open_access_mapping.get("oa_status")),
            full_text_url=_optional_str(open_access_mapping.get("oa_url")),
        ),
        status="resolved_full_text_candidate"
        if bool(open_access_mapping.get("is_oa"))
        else "resolved_metadata_only",
        provenance=[
            LiteratureGraphProvenance(
                provider=OPENALEX_PROVIDER,
                source_id=_optional_str(item.get("id")),
            )
        ],
    )


def _availability_from_unpaywall(item: Mapping[str, Any]) -> LiteratureAvailability:
    best_location = item.get("best_oa_location")
    best_location_mapping = best_location if isinstance(best_location, Mapping) else {}
    return LiteratureAvailability(
        is_open_access=bool(item.get("is_oa")),
        oa_status=_optional_str(item.get("oa_status")),
        full_text_url=_optional_str(best_location_mapping.get("url")),
        license_or_access_hint=_optional_str(best_location_mapping.get("license")),
    )


def _openalex_authors(authorships: object) -> list[LiteratureAuthor]:
    if not isinstance(authorships, Sequence) or isinstance(authorships, str | bytes):
        return []

    authors: list[LiteratureAuthor] = []
    for authorship in authorships:
        if not isinstance(authorship, Mapping):
            continue
        author = authorship.get("author")
        if not isinstance(author, Mapping):
            continue
        name = _optional_str(author.get("display_name"))
        if not name:
            continue
        institutions = authorship.get("institutions")
        authors.append(
            LiteratureAuthor(
                name=name,
                openalex_id=_optional_str(author.get("id")),
                orcid=_orcid_from_url(_optional_str(author.get("orcid"))),
                affiliations=_openalex_institutions(institutions),
            )
        )
    return authors


def _openalex_institutions(institutions: object) -> list[str]:
    if not isinstance(institutions, Sequence) or isinstance(institutions, str | bytes):
        return []
    names: list[str] = []
    for institution in institutions:
        if not isinstance(institution, Mapping):
            continue
        name = _optional_str(institution.get("display_name"))
        if name:
            names.append(name)
    return names


def _openalex_journal(item: Mapping[str, Any]) -> str | None:
    primary_location = item.get("primary_location")
    if not isinstance(primary_location, Mapping):
        return None
    source = primary_location.get("source")
    if not isinstance(source, Mapping):
        return None
    return _optional_str(source.get("display_name"))


def _doi_from_url(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = "https://doi.org/"
    return value[len(prefix) :] if value.lower().startswith(prefix) else value


def _pmid_from_url(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]


def _openalex_work_filter_id(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]


def _orcid_from_url(value: str | None) -> str | None:
    if value is None:
        return None
    prefix = "https://orcid.org/"
    return value[len(prefix) :] if value.lower().startswith(prefix) else value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _is_truthy_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().upper() in {"Y", "YES", "TRUE", "1"}
