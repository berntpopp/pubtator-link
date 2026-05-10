"""NCBI publication metadata client and citation mapping service."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, Protocol

import httpx
from defusedxml import ElementTree

from pubtator_link.api.retry import RetryPolicy, call_with_retries
from pubtator_link.models.publication_metadata import (
    PublicationAuthor,
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)
from pubtator_link.models.review_rerag import CoverageReason, CoverageTier
from pubtator_link.services.ncbi_discovery import NCBI_EUTILS_BASE_URL

QueryParamValue = str | int | float | bool | None
QueryParams = Mapping[str, QueryParamValue | Sequence[QueryParamValue]]
CoverageProvider = Callable[
    [list[str]],
    Awaitable[dict[str, tuple[CoverageTier, CoverageReason]]],
]
PUBLICATION_METADATA_BATCH_SIZE = 100


class PublicationMetadataLookup(Protocol):
    """Metadata lookup interface used by internal batching helpers."""

    async def get_metadata(
        self,
        request: PublicationMetadataRequest,
    ) -> PublicationMetadataResponse: ...


class _MeshXmlParseError(ValueError):
    """Internal marker for malformed PubMed EFetch XML."""


async def lookup_metadata_batched(
    metadata_service: PublicationMetadataLookup,
    pmids: Sequence[str],
    *,
    include_mesh: bool = False,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "none",
    include_coverage: bool = True,
    batch_size: int = PUBLICATION_METADATA_BATCH_SIZE,
) -> PublicationMetadataResponse:
    """Lookup publication metadata in capped internal batches."""

    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    normalized_pmids = _normalize_metadata_batch_pmids(pmids)
    if not normalized_pmids:
        return _empty_metadata_batch_response()

    effective_batch_size = min(batch_size, PUBLICATION_METADATA_BATCH_SIZE)
    metadata_by_pmid: dict[str, PublicationMetadata] = {}
    failed_pmids: dict[str, str] = {}
    source: str | None = None
    warning_counts: Counter[str] = Counter()
    warnings: list[str] = []
    failed_batch_count = 0
    batch_failure_exception_types: list[str] = []

    batches = list(_metadata_batches(normalized_pmids, effective_batch_size))
    for batch in batches:
        request = PublicationMetadataRequest(
            pmids=batch,
            include_mesh=include_mesh,
            include_publication_types=include_publication_types,
            include_citations=include_citations,
            include_coverage=include_coverage,
        )
        try:
            response = await metadata_service.get_metadata(request)
        except Exception as exc:
            failed_batch_count += 1
            failed_pmids.update(dict.fromkeys(batch, "batch_request_failed"))
            _record_metadata_batch_warning(
                "pubmed_metadata_batch_failed",
                warnings,
                warning_counts,
            )
            exception_type = type(exc).__name__
            if exception_type not in batch_failure_exception_types:
                batch_failure_exception_types.append(exception_type)
            continue

        if source is None:
            response_source = response.meta.get("source")
            if isinstance(response_source, str) and response_source:
                source = response_source

        failed_pmids.update(response.failed_pmids)
        for warning in _metadata_response_warnings(response):
            _record_metadata_batch_warning(warning, warnings, warning_counts)
        for metadata in response.metadata:
            metadata_by_pmid[metadata.pmid] = metadata

    metadata_records = [
        metadata_by_pmid[pmid]
        for pmid in normalized_pmids
        if pmid in metadata_by_pmid and pmid not in failed_pmids
    ]
    meta: dict[str, Any] = {"next_commands": _next_commands(has_metadata=bool(metadata_records))}
    if source is not None:
        meta["source"] = source
    if warnings:
        meta["warnings"] = warnings
        meta["warning_counts"] = dict(warning_counts)
    meta["batch_count"] = len(batches)
    meta["failed_batch_count"] = failed_batch_count
    if batch_failure_exception_types:
        meta["batch_failure_exception_types"] = batch_failure_exception_types

    return PublicationMetadataResponse(
        success=True,
        metadata=metadata_records,
        failed_pmids=failed_pmids,
        _meta=meta,
    )


def _normalize_metadata_batch_pmids(pmids: Sequence[str]) -> list[str]:
    normalized_pmids: list[str] = []
    seen_pmids: set[str] = set()
    for pmid in pmids:
        clean_pmid = pmid.strip()
        if clean_pmid.upper().startswith("PMID:"):
            clean_pmid = clean_pmid[5:].strip()
        if not clean_pmid:
            continue
        if not clean_pmid.isdigit():
            raise ValueError("PMID must be numeric")
        if clean_pmid not in seen_pmids:
            normalized_pmids.append(clean_pmid)
            seen_pmids.add(clean_pmid)
    return normalized_pmids


def _metadata_batches(pmids: Sequence[str], batch_size: int) -> list[list[str]]:
    return [list(pmids[index : index + batch_size]) for index in range(0, len(pmids), batch_size)]


def _empty_metadata_batch_response() -> PublicationMetadataResponse:
    return PublicationMetadataResponse(
        success=True,
        metadata=[],
        failed_pmids={},
        _meta={"next_commands": []},
    )


def _metadata_response_warnings(response: PublicationMetadataResponse) -> list[str]:
    warnings = response.meta.get("warnings", [])
    if isinstance(warnings, str):
        return [warnings]
    if isinstance(warnings, list):
        return [warning for warning in warnings if isinstance(warning, str) and warning]
    return []


def _record_metadata_batch_warning(
    warning: str,
    warnings: list[str],
    warning_counts: Counter[str],
) -> None:
    warning_counts[warning] += 1
    if warning not in warnings:
        warnings.append(warning)


class NcbiPublicationMetadataClient:
    """Small NCBI E-utilities client for PubMed citation metadata."""

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout: float = 20.0,
        tool_name: str = "publication_metadata",
    ) -> None:
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self._timeout = timeout
        self._tool_name = tool_name
        self._retry_policy = RetryPolicy()
        self._esummary_cache: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    async def fetch_esummary(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        cached = {
            pmid: self._esummary_cache[pmid] for pmid in pmids if pmid in self._esummary_cache
        }
        missing_pmids = [pmid for pmid in pmids if pmid not in cached]
        if not missing_pmids:
            return cached
        params = {"db": "pubmed", "id": ",".join(missing_pmids), "retmode": "json"}
        data = await self._get_json("esummary.fcgi", params=params)
        result = data.get("result", {})
        if not isinstance(result, dict):
            return cached
        uids = result.get("uids", [])
        if not isinstance(uids, list):
            return cached

        records: dict[str, dict[str, Any]] = dict(cached)
        for pmid in uids:
            pmid_key = str(pmid)
            record = result.get(pmid_key)
            if isinstance(record, dict) and "error" not in record:
                records[pmid_key] = record
                self._esummary_cache[pmid_key] = record
        return records

    async def fetch_mesh_headings(self, pmids: list[str]) -> dict[str, list[str]]:
        params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
        text = await self._get_text("efetch.fcgi", params=params)
        return _parse_mesh_xml(text)

    async def _get_json(self, path: str, *, params: QueryParams) -> dict[str, Any]:
        response = await self._get(path, params=params)
        data = response.json()
        return data if isinstance(data, dict) else {}

    async def _get_text(self, path: str, *, params: QueryParams) -> str:
        response = await self._get(path, params=params)
        return response.text

    async def _get(self, path: str, *, params: QueryParams) -> httpx.Response:
        url = f"{NCBI_EUTILS_BASE_URL}/{path.lstrip('/')}"
        request_params = {**params, "tool": self._tool_name}
        response, _metadata = await call_with_retries(
            lambda: self._http_client.get(
                url,
                params=request_params,
                timeout=self._timeout,
            ),
            policy=self._retry_policy,
        )
        response.raise_for_status()
        return response


class PublicationMetadataService:
    """Map NCBI PubMed metadata into citation-oriented response models."""

    def __init__(
        self,
        client: NcbiPublicationMetadataClient,
        *,
        coverage_provider: CoverageProvider | None = None,
    ) -> None:
        self._client = client
        self._coverage_provider = coverage_provider

    async def get_metadata(
        self,
        request: PublicationMetadataRequest,
    ) -> PublicationMetadataResponse:
        esummary_by_pmid = await self._client.fetch_esummary(request.pmids)
        warnings: list[str] = []
        mesh_by_pmid: dict[str, list[str]] = {}
        if request.include_mesh:
            try:
                mesh_by_pmid = await self._client.fetch_mesh_headings(request.pmids)
            except Exception:
                warnings.append("mesh_lookup_failed")

        coverage_by_pmid: dict[str, tuple[CoverageTier, CoverageReason]] = {}
        if request.include_coverage and self._coverage_provider:
            try:
                coverage_by_pmid = await self._coverage_provider(request.pmids)
            except Exception:
                warnings.append("coverage_lookup_failed")

        metadata_records: list[PublicationMetadata] = []
        failed_pmids: dict[str, str] = {}
        for pmid in request.pmids:
            item = esummary_by_pmid.get(pmid)
            if item is None:
                failed_pmids[pmid] = "metadata_not_found"
                continue

            metadata = self._metadata_from_esummary(
                pmid,
                item,
                mesh_headings=mesh_by_pmid.get(pmid, []),
                include_publication_types=request.include_publication_types,
            )
            if pmid in coverage_by_pmid:
                metadata.coverage, metadata.coverage_reason = coverage_by_pmid[pmid]

            if request.include_citations in {"nlm", "both"}:
                metadata.nlm_citation = _build_nlm_citation(metadata)
            if request.include_citations in {"bibtex", "both"}:
                metadata.bibtex = _build_bibtex(metadata)

            metadata_records.append(metadata)

        meta: dict[str, Any] = {
            "source": "NCBI ESummary and EFetch",
            "next_commands": _next_commands(has_metadata=bool(metadata_records)),
        }
        if warnings:
            meta["warnings"] = warnings

        return PublicationMetadataResponse(
            success=True,
            metadata=metadata_records,
            failed_pmids=failed_pmids,
            _meta=meta,
        )

    def _metadata_from_esummary(
        self,
        pmid: str,
        item: dict[str, Any],
        *,
        mesh_headings: list[str],
        include_publication_types: bool,
    ) -> PublicationMetadata:
        pubdate = _optional_str(item.get("pubdate")) or _optional_str(item.get("epubdate"))
        articleids = _article_ids(item.get("articleids"))
        return PublicationMetadata(
            pmid=pmid,
            title=_optional_str(item.get("title")),
            journal=_optional_str(item.get("fulljournalname")) or _optional_str(item.get("source")),
            pub_year=_parse_pub_year(pubdate, _optional_str(item.get("sortpubdate"))),
            pub_date=pubdate,
            volume=_optional_str(item.get("volume")),
            issue=_optional_str(item.get("issue")),
            pages=_optional_str(item.get("pages")),
            doi=_extract_article_id(articleids, "doi"),
            pmcid=_extract_article_id(articleids, "pmc"),
            authors=_authors(item.get("authors")),
            publication_types=_string_list(item.get("pubtype"))
            if include_publication_types
            else [],
            mesh_headings=mesh_headings,
        )


def _parse_pub_year(pubdate: str | None, sortpubdate: str | None) -> int | None:
    for value in (pubdate, sortpubdate):
        if value is None:
            continue
        match = re.search(r"\b(\d{4})\b", value)
        if match is not None:
            return int(match.group(1))
    return None


def _extract_article_id(articleids: list[dict[str, str]], idtype: str) -> str | None:
    for article_id in articleids:
        if article_id.get("idtype", "").lower() == idtype.lower():
            value = article_id.get("value")
            return value if value else None
    return None


def _parse_author(name: str) -> PublicationAuthor:
    clean_name = " ".join(name.split())
    if not clean_name:
        return PublicationAuthor()

    parts = clean_name.split(" ")
    initials = parts[-1].replace(".", "") if len(parts) > 1 else ""
    if initials.isupper() and initials.isalpha() and len(initials) <= 5:
        return PublicationAuthor(last_name=" ".join(parts[:-1]), initials=initials)
    return PublicationAuthor(last_name=clean_name)


def _parse_mesh_xml(xml_text: str) -> dict[str, list[str]]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise _MeshXmlParseError("Malformed PubMed EFetch XML") from exc

    mesh_by_pmid: dict[str, list[str]] = {}
    for article in _iter_elements(root, "PubmedArticle"):
        pmid = _first_text(article, "PMID")
        if pmid is None:
            continue

        headings: list[str] = []
        for mesh_heading in _iter_elements(article, "MeshHeading"):
            descriptor = _first_direct_child_text(mesh_heading, "DescriptorName")
            if descriptor is not None:
                headings.append(descriptor)
        mesh_by_pmid[pmid] = headings

    return mesh_by_pmid


def _build_nlm_citation(metadata: PublicationMetadata) -> str:
    parts: list[str] = []
    if metadata.vancouver_author_string:
        parts.append(_sentence(metadata.vancouver_author_string))
    if metadata.title:
        parts.append(_sentence(metadata.title))

    journal = _journal_citation(metadata)
    if journal:
        parts.append(_sentence(journal))
    if metadata.doi:
        parts.append(f"doi: {metadata.doi}.")
    parts.append(f"PMID: {metadata.pmid}.")
    if metadata.pmcid:
        parts.append(f"PMCID: {metadata.pmcid}.")
    return " ".join(parts)


def _build_bibtex(metadata: PublicationMetadata) -> str:
    fields = {
        "title": metadata.title,
        "author": " and ".join(
            author.display_name for author in metadata.authors if author.display_name
        )
        or None,
        "journal": metadata.journal,
        "year": str(metadata.pub_year) if metadata.pub_year is not None else None,
        "volume": metadata.volume,
        "number": metadata.issue,
        "pages": metadata.pages,
        "doi": metadata.doi,
        "pmcid": metadata.pmcid,
        "pmid": metadata.pmid,
    }
    rendered_fields = [
        f"  {name} = {{{_escape_bibtex(value)}}}"
        for name, value in fields.items()
        if value is not None
    ]
    return "@article{pmid" + metadata.pmid + ",\n" + ",\n".join(rendered_fields) + "\n}"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _article_ids(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    articleids: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        idtype = _optional_str(item.get("idtype"))
        article_id_value = _optional_str(item.get("value"))
        if idtype is not None and article_id_value is not None:
            articleids.append({"idtype": idtype, "value": article_id_value})
    return articleids


def _authors(value: object) -> list[PublicationAuthor]:
    if not isinstance(value, list):
        return []

    authors: list[PublicationAuthor] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _optional_str(item.get("name"))
        if name is not None:
            authors.append(_parse_author(name))
    return authors


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _iter_elements(element: Any, local_name: str) -> list[Any]:
    return [child for child in element.iter() if _local_name(child.tag) == local_name]


def _first_text(element: Any, local_name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == local_name:
            text = _optional_str(child.text)
            if text is not None:
                return text
    return None


def _first_direct_child_text(element: Any, local_name: str) -> str | None:
    for child in list(element):
        if _local_name(child.tag) == local_name:
            return _optional_str(child.text)
    return None


def _local_name(tag: object) -> str:
    tag_text = str(tag)
    if "}" in tag_text:
        return tag_text.rsplit("}", 1)[1]
    return tag_text


def _journal_citation(metadata: PublicationMetadata) -> str:
    if metadata.journal is None:
        return ""

    citation = metadata.journal
    if metadata.pub_year is not None:
        citation = f"{citation}. {metadata.pub_year}"
    if metadata.volume:
        citation = f"{citation};{metadata.volume}"
    if metadata.issue:
        citation = f"{citation}({metadata.issue})"
    if metadata.pages:
        citation = f"{citation}:{metadata.pages}"
    return citation


def _sentence(value: str) -> str:
    return value if value.endswith(".") else f"{value}."


def _escape_bibtex(value: str) -> str:
    return value.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _next_commands(*, has_metadata: bool) -> list[str]:
    if not has_metadata:
        return []
    return [
        "Use pubtator_get_publication_passages for citable passage text.",
        "Use pubtator_index_review_evidence after selecting the final PMID corpus.",
    ]
