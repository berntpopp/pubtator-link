"""NCBI E-utilities discovery client and response mapping service."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

import httpx

from pubtator_link.api.retry import RetryPolicy, call_with_retries
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    ArticleIdKind,
    CitationLookupRecord,
    CitationLookupResponse,
    DiscoveryMeta,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleMode,
    RelatedArticleRecord,
    RelatedArticleScoreRecord,
    RelatedArticlesResponse,
)

NCBI_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
NCBI_ID_CONVERTER_BASE_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
NCBI_EUTILS_SOURCE_URL = "https://www.ncbi.nlm.nih.gov/books/NBK25501/"
NCBI_MESH_SOURCE_URL = "https://www.ncbi.nlm.nih.gov/mesh/"
NBK_RE = re.compile(r"\bNBK\d+\b", re.IGNORECASE)
QueryParamValue = str | int | float | bool | None
QueryParams = (
    Mapping[str, QueryParamValue | Sequence[QueryParamValue]]
    | list[tuple[str, QueryParamValue]]
    | tuple[
        tuple[str, QueryParamValue],
        ...,
    ]
    | str
    | bytes
    | None
)


def extract_nbk_ids(values: Sequence[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        ids.extend(match.group(0).upper() for match in NBK_RE.finditer(value))
    return list(dict.fromkeys(ids))


class NcbiDiscoveryClientProtocol(Protocol):
    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        """Convert article identifiers to PubMed-centered records."""

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        """Resolve a DOI to a PMID via PubMed search."""

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        """Look up MeSH descriptors for a query."""

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        """Resolve free-text citations to article records."""

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        """Find related PubMed articles for source PMIDs."""

    async def find_related_article_scores(
        self,
        pmids: Sequence[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        """Find PubMed neighbor_score links for source PMIDs."""


class NcbiDiscoveryClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        base_url: str = NCBI_EUTILS_BASE_URL,
        id_converter_url: str = NCBI_ID_CONVERTER_BASE_URL,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self.base_url = base_url.rstrip("/")
        self.id_converter_url = id_converter_url
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: QueryParams) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        return response

    async def _get_absolute(self, url: str, params: QueryParams) -> httpx.Response:
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        return response

    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind,
    ) -> list[ArticleIdConversionRecord]:
        params = {"ids": ",".join(ids), "format": "json", "tool": "pubtator-link"}
        if source != "auto":
            params["idtype"] = source
        response = await self._get_absolute(self.id_converter_url, params)
        payload = response.json()
        records_payload = payload.get("records", []) if isinstance(payload, dict) else []

        records_by_requested_id: dict[str, ArticleIdConversionRecord] = {}
        for item in records_payload:
            if not isinstance(item, dict):
                continue

            pmid = _optional_str(item.get("pmid"))
            pmcid = _optional_str(item.get("pmcid"))
            doi = _optional_str(item.get("doi"))
            requested_id = _optional_str(item.get("requested-id")) or pmcid or pmid or doi
            if requested_id is None:
                continue

            resolved = pmid is not None or pmcid is not None or doi is not None
            records_by_requested_id[requested_id] = ArticleIdConversionRecord(
                input_id=requested_id,
                input_kind=source,
                status="resolved" if resolved else "unresolved",
                pmid=pmid,
                pmcid=pmcid,
                doi=doi,
                reason=None if resolved else "not_found",
            )

        return [
            records_by_requested_id.get(
                requested,
                ArticleIdConversionRecord(
                    input_id=requested,
                    input_kind=source,
                    status="unresolved",
                    reason="not_found",
                ),
            )
            for requested in ids
        ]

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        response = await self._get(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "term": f"{doi}[AID]",
                "retmode": "json",
                "retmax": "1",
                "tool": "pubtator-link",
            },
        )
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        esearch_result = payload.get("esearchresult")
        idlist_payload = (
            esearch_result.get("idlist", []) if isinstance(esearch_result, dict) else []
        )
        if not isinstance(idlist_payload, list | tuple) or not idlist_payload:
            return None
        return str(idlist_payload[0])

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        term = f'"{query}"[MeSH Terms]' if exact else query
        search_response = await self._get(
            "esearch.fcgi",
            {
                "db": "mesh",
                "term": term,
                "retmode": "json",
                "retmax": str(limit),
                "tool": "pubtator-link",
            },
        )
        search_payload = search_response.json()
        if not isinstance(search_payload, dict):
            return []

        esearch_result = search_payload.get("esearchresult")
        idlist_payload = (
            esearch_result.get("idlist", []) if isinstance(esearch_result, dict) else []
        )
        idlist = [str(mesh_id) for mesh_id in idlist_payload]
        if not idlist:
            return []

        summary_payload = search_payload
        if "result" not in summary_payload:
            summary_response = await self._get(
                "esummary.fcgi",
                {
                    "db": "mesh",
                    "id": ",".join(idlist),
                    "retmode": "json",
                    "tool": "pubtator-link",
                },
            )
            summary_json = summary_response.json()
            summary_payload = summary_json if isinstance(summary_json, dict) else {}

        result_payload = summary_payload.get("result")
        results = result_payload if isinstance(result_payload, dict) else {}
        descriptors: list[MeshDescriptor] = []
        for mesh_id in idlist:
            item = results.get(mesh_id)
            if not isinstance(item, dict):
                continue

            uid = _optional_str(item.get("uid")) or mesh_id
            mesh_terms = _string_list(item.get("ds_meshterms"))
            name = mesh_terms[0] if mesh_terms else _optional_str(item.get("title")) or uid
            descriptors.append(
                MeshDescriptor(
                    ui=_optional_str(item.get("ds_meshui")) or uid,
                    name=name,
                    scope_note=_optional_str(item.get("ds_scopenote")),
                    entry_terms=mesh_terms[1:],
                    tree_numbers=_mesh_tree_numbers(item),
                    search_terms=[f"{name}[MeSH Terms]"],
                )
            )

        return descriptors

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        response = await self._get(
            "ecitmatch.cgi",
            {
                "db": "pubmed",
                "retmode": "text",
                "bdata": "\r".join(citations),
                "tool": "pubtator-link",
            },
        )
        lines = response.text.splitlines()

        records: list[CitationLookupRecord] = []
        for index, citation in enumerate(citations):
            line = lines[index] if index < len(lines) else ""
            fields = line.split("|") if line else []
            pmid = next((field.strip() for field in reversed(fields) if field.strip()), "")
            if pmid.isdecimal() and pmid != "NOT_FOUND":
                records.append(CitationLookupRecord(citation=citation, status="matched", pmid=pmid))
            else:
                records.append(
                    CitationLookupRecord(
                        citation=citation,
                        status="not_found",
                        reason="not_found",
                    )
                )

        return records

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode,
        limit: int,
    ) -> list[RelatedArticleRecord]:
        linknames: dict[RelatedArticleMode, str] = {
            "similar": "pubmed_pubmed",
            "cited_by": "pubmed_pubmed_citedin",
            "references": "pubmed_pubmed_refs",
        }
        params: list[tuple[str, QueryParamValue]] = [
            ("dbfrom", "pubmed"),
            ("db", "pubmed"),
            *(("id", pmid) for pmid in pmids),
            ("linkname", linknames[mode]),
            ("retmode", "json"),
            ("tool", "pubtator-link"),
        ]
        response = await self._get(
            "elink.fcgi",
            params,
        )
        payload = response.json()
        linksets = payload.get("linksets", []) if isinstance(payload, dict) else []

        records: list[RelatedArticleRecord] = []
        for linkset in linksets:
            if not isinstance(linkset, dict):
                continue

            ids = linkset.get("ids")
            source_pmid = str(ids[0]) if isinstance(ids, list | tuple) and ids else None
            if source_pmid is None:
                continue

            emitted_for_source = 0
            linksetdbs = linkset.get("linksetdbs", [])
            if not isinstance(linksetdbs, list | tuple):
                continue

            for linksetdb in linksetdbs:
                if emitted_for_source >= limit:
                    break
                if not isinstance(linksetdb, dict):
                    continue

                links = linksetdb.get("links", [])
                if not isinstance(links, list | tuple):
                    continue

                for linked_pmid in links:
                    linked_pmid_str = str(linked_pmid)
                    if linked_pmid_str == source_pmid:
                        continue
                    if emitted_for_source >= limit:
                        break
                    records.append(
                        RelatedArticleRecord(
                            source_pmid=source_pmid,
                            pmid=linked_pmid_str,
                            relation=mode,
                        )
                    )
                    emitted_for_source += 1

        return records

    async def find_related_article_scores(
        self,
        pmids: Sequence[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        params: list[tuple[str, QueryParamValue]] = [
            ("dbfrom", "pubmed"),
            ("db", "pubmed"),
            *(("id", pmid) for pmid in pmids),
            ("linkname", "pubmed_pubmed"),
            ("cmd", "neighbor_score"),
            ("retmode", "json"),
            ("tool", "pubtator-link"),
        ]
        response = await self._get("elink.fcgi", params)
        payload = response.json()
        linksets = payload.get("linksets", []) if isinstance(payload, dict) else []

        records: list[RelatedArticleScoreRecord] = []
        for linkset in linksets:
            if not isinstance(linkset, dict):
                continue

            ids = linkset.get("ids")
            source_pmid = str(ids[0]) if isinstance(ids, list | tuple) and ids else None
            if source_pmid is None:
                continue

            emitted_for_source = 0
            linksetdbs = linkset.get("linksetdbs", [])
            if not isinstance(linksetdbs, list | tuple):
                continue

            for linksetdb in linksetdbs:
                if emitted_for_source >= limit:
                    break
                if not isinstance(linksetdb, dict):
                    continue

                links = linksetdb.get("links", [])
                if not isinstance(links, list | tuple):
                    continue

                for link in links:
                    if emitted_for_source >= limit:
                        break
                    linked_pmid, score = _link_id_and_score(link)
                    if linked_pmid is None or linked_pmid == source_pmid:
                        continue
                    records.append(
                        RelatedArticleScoreRecord(
                            source_pmid=source_pmid,
                            pmid=linked_pmid,
                            neighbor_score=score,
                        )
                    )
                    emitted_for_source += 1

        return records


class DiscoveryService:
    def __init__(self, client: NcbiDiscoveryClientProtocol) -> None:
        self.client = client

    async def convert_article_ids(
        self,
        ids: Sequence[str],
        source: ArticleIdKind = "auto",
    ) -> ArticleIdConversionResponse:
        records = await self.client.convert_article_ids(ids, source)
        candidate_pmids = _dedupe(record.pmid for record in records if record.pmid is not None)
        unresolved = [record.input_id for record in records if record.status != "resolved"]
        return ArticleIdConversionResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            _meta=_candidate_meta(candidate_pmids),
        )

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        return await self.client.find_pmid_by_doi(doi)

    async def lookup_mesh(
        self,
        query: str,
        limit: int = 10,
        exact: bool = False,
    ) -> MeshLookupResponse:
        descriptors = await self.client.lookup_mesh(query, limit, exact)
        next_commands: list[dict[str, object]] = [
            {
                "tool": "pubtator_search_literature",
                "arguments": {
                    "text": descriptor.search_terms[0]
                    if descriptor.search_terms
                    else descriptor.name
                },
            }
            for descriptor in descriptors
        ]
        return MeshLookupResponse(
            query=query,
            descriptors=descriptors,
            _meta=DiscoveryMeta(
                source_urls=[NCBI_MESH_SOURCE_URL],
                next_commands=next_commands,
            ),
        )

    async def lookup_citation(self, citations: Sequence[str]) -> CitationLookupResponse:
        lookup_values = _citation_lookup_values(citations)
        records = await self.client.lookup_citations(lookup_values)
        nbk_ids = extract_nbk_ids(citations)
        nbk_conversion_records: list[ArticleIdConversionRecord] = []
        if nbk_ids:
            nbk_conversion_records = await self.client.convert_article_ids(nbk_ids, "auto")
            records = [
                record.model_copy(update={"reason": "nbk_not_mapped"})
                if record.status == "not_found" and extract_nbk_ids([record.citation])
                else record
                for record in records
            ]
        candidate_pmids = _dedupe(
            [
                *(record.pmid for record in records if record.pmid is not None),
                *(record.pmid for record in nbk_conversion_records if record.pmid is not None),
            ]
        )
        meta = _candidate_meta(candidate_pmids)
        if nbk_ids:
            meta.next_commands = [
                {
                    "tool": "pubtator_lookup_citation",
                    "arguments": {"citations": [_nbk_lookup_hint(nbk_id) for nbk_id in nbk_ids]},
                },
                *meta.next_commands,
            ]
        return CitationLookupResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            _meta=meta,
        )

    async def find_related_articles(
        self,
        pmids: Sequence[str],
        mode: RelatedArticleMode = "similar",
        limit: int = 20,
    ) -> RelatedArticlesResponse:
        related_articles = await self.client.find_related_articles(pmids, mode, limit)
        candidate_pmids = _dedupe(record.pmid for record in related_articles)
        resolved_source_pmids = {record.source_pmid for record in related_articles}
        unresolved = [pmid for pmid in pmids if pmid not in resolved_source_pmids]
        return RelatedArticlesResponse(
            source_pmids=list(pmids),
            mode=mode,
            related_articles=related_articles,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            _meta=_candidate_meta(candidate_pmids),
        )


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


def _citation_lookup_values(citations: Sequence[str]) -> list[str]:
    return [
        _nbk_lookup_hint(nbk_ids[0]) if _is_bookshelf_url(citation) and nbk_ids else citation
        for citation in citations
        for nbk_ids in [extract_nbk_ids([citation])]
    ]


def _is_bookshelf_url(value: str) -> bool:
    return "ncbi.nlm.nih.gov/books/" in value.lower()


def _nbk_lookup_hint(nbk_id: str) -> str:
    if nbk_id.upper() == "NBK1139":
        return f"GeneReviews {nbk_id.upper()} familial Mediterranean fever"
    return f"GeneReviews {nbk_id.upper()}"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return [str(value)]


def _link_id_and_score(link: object) -> tuple[str | None, int]:
    if isinstance(link, dict):
        linked_id = _optional_str(link.get("id"))
        score_value = link.get("score", 0)
    else:
        linked_id = _optional_str(link)
        score_value = 0

    try:
        score = int(score_value)
    except (TypeError, ValueError):
        score = 0
    return linked_id, score


def _mesh_tree_numbers(item: Mapping[str, object]) -> list[str]:
    tree_numbers: list[str] = []
    idx_links = item.get("ds_idxlinks")
    if isinstance(idx_links, list | tuple):
        for link in idx_links:
            if not isinstance(link, dict):
                continue
            tree_number = _optional_str(link.get("treenum"))
            if tree_number is not None:
                tree_numbers.append(tree_number)
    if tree_numbers:
        return tree_numbers
    return _string_list(item.get("ds_tree"))


def _candidate_meta(candidate_pmids: list[str]) -> DiscoveryMeta:
    next_commands: list[dict[str, object]] = []
    if candidate_pmids:
        next_commands = [
            {
                "tool": "pubtator_stage_research_session",
                "arguments": {"pmids": candidate_pmids},
            },
            {
                "tool": "pubtator_index_review_evidence",
                "arguments": {"pmids": candidate_pmids},
            },
        ]
    return DiscoveryMeta(
        source_urls=[NCBI_EUTILS_SOURCE_URL],
        next_commands=next_commands,
    )
