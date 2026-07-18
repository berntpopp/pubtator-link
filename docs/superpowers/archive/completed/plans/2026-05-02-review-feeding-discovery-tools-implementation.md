# Review-Feeding Discovery Tools Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add NCBI-backed discovery tools for article ID conversion, MeSH lookup, citation lookup, and related-article expansion that feed PubTator-Link review staging and indexing.

**Architecture:** Add typed discovery models, a focused NCBI discovery client/service layer, REST routes, and MCP tools. The service returns candidate PMIDs and `_meta.next_commands` so agents can hand results directly to `stage_research_session` or `index_review_evidence`.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, httpx, existing `RetryPolicy`, pytest, respx-style HTTP fakes where already used.

---

## File Map

- Create `pubtator_link/models/discovery.py`: typed request/response models for discovery surfaces.
- Create `pubtator_link/services/ncbi_discovery.py`: async NCBI client plus public service mapping.
- Create `pubtator_link/api/routes/discovery.py`: REST endpoints mirroring MCP behavior.
- Create `pubtator_link/mcp/tools/discovery.py`: four read-only MCP tools.
- Modify `pubtator_link/api/routes/dependencies.py`: app-scoped discovery service construction and dependency getter.
- Modify `pubtator_link/server_manager.py`: include the discovery router beside existing routers.
- Modify `pubtator_link/mcp/facade.py`: register discovery MCP tools.
- Modify `pubtator_link/mcp/resources.py`: document discovery workflow and next-step handoff.
- Modify `README.md`: add MCP/REST discovery tool summary.
- Test `tests/unit/test_discovery_models.py`.
- Test `tests/unit/test_ncbi_discovery_service.py`.
- Test `tests/test_routes/test_discovery.py`.
- Test `tests/unit/mcp/test_mcp_service_adapters.py` or a new focused MCP discovery test.
- Test `tests/unit/mcp/test_mcp_facade.py` for inventory/schema/research-use contract.

---

### Task 1: Add Discovery Models

**Files:**
- Create: `pubtator_link/models/discovery.py`
- Test: `tests/unit/test_discovery_models.py`

- [ ] **Step 1: Write failing model tests**

Add `tests/unit/test_discovery_models.py`:

```python
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    CitationLookupRecord,
    CitationLookupResponse,
    DiscoveryMeta,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleRecord,
    RelatedArticlesResponse,
)


def test_article_id_conversion_response_serializes_meta_alias() -> None:
    response = ArticleIdConversionResponse(
        records=[
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
                doi="10.1000/example",
            )
        ],
        candidate_pmids=["123"],
        unresolved=[],
        meta=DiscoveryMeta(
            source_urls=["https://eutils.ncbi.nlm.nih.gov/entrez/eutils/idconv/v1.0/"],
            next_commands=[
                {
                    "tool": "pubtator.stage_research_session",
                    "arguments": {"candidate_pmids": ["123"]},
                }
            ],
        ),
    )

    dumped = response.model_dump(by_alias=True)

    assert dumped["_meta"]["research_use_only"] is True
    assert dumped["candidate_pmids"] == ["123"]
    assert dumped["records"][0]["pmid"] == "123"


def test_mesh_lookup_response_keeps_descriptor_fields() -> None:
    response = MeshLookupResponse(
        query="familial mediterranean fever",
        descriptors=[
            MeshDescriptor(
                ui="D010505",
                name="Familial Mediterranean Fever",
                scope_note="Autoinflammatory disorder.",
                entry_terms=["FMF"],
                tree_numbers=["C16.320.565"],
                search_terms=["Familial Mediterranean Fever[MeSH Terms]"],
            )
        ],
        meta=DiscoveryMeta(next_commands=[]),
    )

    assert response.descriptors[0].entry_terms == ["FMF"]
    assert response.candidate_pmids == []


def test_citation_lookup_response_tracks_statuses_and_candidates() -> None:
    response = CitationLookupResponse(
        records=[
            CitationLookupRecord(
                citation="Ann Rheum Dis. 2024;83:1-2.",
                status="matched",
                pmid="39596913",
                doi="10.1136/example",
            ),
            CitationLookupRecord(citation="Unknown citation", status="not_found"),
        ],
        candidate_pmids=["39596913"],
        meta=DiscoveryMeta(next_commands=[]),
    )

    assert [record.status for record in response.records] == ["matched", "not_found"]
    assert response.candidate_pmids == ["39596913"]


def test_related_articles_response_deduplicates_candidates_in_caller_order() -> None:
    response = RelatedArticlesResponse(
        source_pmids=["1", "2"],
        mode="similar",
        related_articles=[
            RelatedArticleRecord(source_pmid="1", pmid="10", relation="similar"),
            RelatedArticleRecord(source_pmid="2", pmid="10", relation="similar"),
            RelatedArticleRecord(source_pmid="2", pmid="11", relation="similar"),
        ],
        candidate_pmids=["10", "11"],
        unresolved=[],
        meta=DiscoveryMeta(next_commands=[]),
    )

    assert response.candidate_pmids == ["10", "11"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_discovery_models.py -q
```

Expected: FAIL because `pubtator_link.models.discovery` does not exist.

- [ ] **Step 3: Implement discovery models**

Create `pubtator_link/models/discovery.py`:

```python
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


ArticleIdKind = Literal["pmid", "pmcid", "doi", "auto"]
ArticleIdTarget = Literal["pmid", "pmcid", "doi"]
ArticleIdStatus = Literal["resolved", "unresolved", "invalid", "failed"]
CitationLookupStatus = Literal["matched", "not_found", "ambiguous", "failed"]
RelatedArticleMode = Literal["similar", "cited_by", "references"]
RelatedArticleStatus = Literal["resolved", "no_links", "failed"]


class DiscoveryMeta(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    source_urls: list[str] = Field(default_factory=list)
    next_commands: list[dict[str, object]] = Field(default_factory=list)
    research_use_only: bool = True


class ArticleIdConversionRequest(BaseModel):
    ids: Annotated[list[str], Field(min_length=1, max_length=200)]
    source: ArticleIdKind = "auto"
    target: list[ArticleIdTarget] | None = None


class ArticleIdConversionRecord(BaseModel):
    input_id: str
    input_kind: ArticleIdKind
    status: ArticleIdStatus
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    reason: str | None = None


class ArticleIdConversionResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    records: list[ArticleIdConversionRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class MeshLookupRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    exact: bool = False


class MeshDescriptor(BaseModel):
    ui: str
    name: str
    scope_note: str | None = None
    entry_terms: list[str] = Field(default_factory=list)
    tree_numbers: list[str] = Field(default_factory=list)
    search_terms: list[str] = Field(default_factory=list)


class MeshLookupResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    query: str
    descriptors: list[MeshDescriptor]
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class CitationLookupRequest(BaseModel):
    citations: Annotated[list[str], Field(min_length=1, max_length=100)]


class CitationLookupRecord(BaseModel):
    citation: str
    status: CitationLookupStatus
    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: str | None = None
    reason: str | None = None


class CitationLookupResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    records: list[CitationLookupRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")


class RelatedArticlesRequest(BaseModel):
    pmids: Annotated[list[str], Field(min_length=1, max_length=100)]
    mode: RelatedArticleMode = "similar"
    limit: Annotated[int, Field(ge=1, le=100)] = 20


class RelatedArticleRecord(BaseModel):
    source_pmid: str
    pmid: str
    relation: RelatedArticleMode
    title: str | None = None
    journal: str | None = None
    year: str | None = None


class RelatedArticlesResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    source_pmids: list[str]
    mode: RelatedArticleMode
    related_articles: list[RelatedArticleRecord]
    candidate_pmids: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    meta: DiscoveryMeta = Field(default_factory=DiscoveryMeta, alias="_meta")
```

- [ ] **Step 4: Run model tests**

Run:

```bash
uv run pytest tests/unit/test_discovery_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/discovery.py tests/unit/test_discovery_models.py
git commit -m "feat: add discovery response models"
```

---

### Task 2: Add NCBI Discovery Service

**Files:**
- Create: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Write service tests with fake client methods**

Add `tests/unit/test_ncbi_discovery_service.py`:

```python
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    CitationLookupRecord,
    MeshDescriptor,
    RelatedArticleRecord,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService


class FakeNcbiClient:
    async def convert_article_ids(self, ids, source):
        return [
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
            ),
            ArticleIdConversionRecord(
                input_id="bad",
                input_kind="auto",
                status="unresolved",
                reason="not_found",
            ),
        ]

    async def lookup_mesh(self, query, limit, exact):
        return [
            MeshDescriptor(
                ui="D010505",
                name="Familial Mediterranean Fever",
                entry_terms=["FMF"],
                search_terms=["Familial Mediterranean Fever[MeSH Terms]"],
            )
        ]

    async def lookup_citations(self, citations):
        return [
            CitationLookupRecord(citation=citations[0], status="matched", pmid="123"),
            CitationLookupRecord(citation=citations[1], status="not_found"),
        ]

    async def find_related_articles(self, pmids, mode, limit):
        return [
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="456", relation=mode),
            RelatedArticleRecord(source_pmid="123", pmid="789", relation=mode),
        ]


async def test_convert_article_ids_adds_candidates_and_next_commands() -> None:
    service = DiscoveryService(FakeNcbiClient())

    response = await service.convert_article_ids(ids=["PMC123", "bad"], source="auto")

    assert response.candidate_pmids == ["123"]
    assert response.unresolved == ["bad"]
    assert response.meta.next_commands[0]["tool"] == "pubtator.stage_research_session"


async def test_lookup_mesh_returns_search_next_command() -> None:
    service = DiscoveryService(FakeNcbiClient())

    response = await service.lookup_mesh(query="FMF", limit=5, exact=False)

    assert response.descriptors[0].ui == "D010505"
    assert response.meta.next_commands[0]["tool"] == "pubtator.search_literature"


async def test_lookup_citation_deduplicates_candidate_pmids() -> None:
    service = DiscoveryService(FakeNcbiClient())

    response = await service.lookup_citation(citations=["known", "unknown"])

    assert response.candidate_pmids == ["123"]
    assert response.records[1].status == "not_found"


async def test_find_related_articles_deduplicates_candidates() -> None:
    service = DiscoveryService(FakeNcbiClient())

    response = await service.find_related_articles(pmids=["123"], mode="similar", limit=20)

    assert response.candidate_pmids == ["456", "789"]
    assert response.meta.next_commands[0]["arguments"]["candidate_pmids"] == ["456", "789"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: FAIL because `pubtator_link.services.ncbi_discovery` does not exist.

- [ ] **Step 3: Implement service and client skeleton**

Create `pubtator_link/services/ncbi_discovery.py`:

```python
from __future__ import annotations

from collections.abc import Iterable, Sequence
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
    RelatedArticlesResponse,
)


class NcbiDiscoveryClientProtocol(Protocol):
    async def convert_article_ids(
        self, ids: Sequence[str], source: ArticleIdKind
    ) -> list[ArticleIdConversionRecord]: ...

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]: ...

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]: ...

    async def find_related_articles(
        self, pmids: Sequence[str], mode: RelatedArticleMode, limit: int
    ) -> list[RelatedArticleRecord]: ...


class NcbiDiscoveryClient:
    def __init__(
        self,
        *,
        base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        timeout_seconds: int = 20,
        retry_policy: RetryPolicy | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retry_policy = retry_policy or RetryPolicy()
        self._owned_client = http_client is None
        self._client = http_client or httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, str]) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        response, _metadata = await call_with_retries(
            lambda: self._client.get(url, params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        return response

    async def convert_article_ids(
        self, ids: Sequence[str], source: ArticleIdKind
    ) -> list[ArticleIdConversionRecord]:
        raise NotImplementedError("Task 3 implements NCBI ID conversion parsing")

    async def lookup_mesh(self, query: str, limit: int, exact: bool) -> list[MeshDescriptor]:
        raise NotImplementedError("Task 4 implements MeSH lookup parsing")

    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        raise NotImplementedError("Task 5 implements ECitMatch parsing")

    async def find_related_articles(
        self, pmids: Sequence[str], mode: RelatedArticleMode, limit: int
    ) -> list[RelatedArticleRecord]:
        raise NotImplementedError("Task 6 implements related article parsing")


class DiscoveryService:
    def __init__(self, client: NcbiDiscoveryClientProtocol) -> None:
        self.client = client

    async def convert_article_ids(
        self, *, ids: Sequence[str], source: ArticleIdKind = "auto"
    ) -> ArticleIdConversionResponse:
        records = await self.client.convert_article_ids(ids, source)
        candidate_pmids = _dedupe(record.pmid for record in records if record.pmid)
        unresolved = [record.input_id for record in records if record.status != "resolved"]
        return ArticleIdConversionResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            meta=_candidate_meta(candidate_pmids),
        )

    async def lookup_mesh(self, *, query: str, limit: int = 10, exact: bool = False) -> MeshLookupResponse:
        descriptors = await self.client.lookup_mesh(query, limit, exact)
        return MeshLookupResponse(
            query=query,
            descriptors=descriptors,
            meta=DiscoveryMeta(
                source_urls=["https://www.ncbi.nlm.nih.gov/mesh/"],
                next_commands=[
                    {
                        "tool": "pubtator.search_literature",
                        "arguments": {"text": descriptor.search_terms[0] if descriptor.search_terms else descriptor.name},
                    }
                    for descriptor in descriptors[:3]
                ],
            ),
        )

    async def lookup_citation(self, *, citations: Sequence[str]) -> CitationLookupResponse:
        records = await self.client.lookup_citations(citations)
        candidate_pmids = _dedupe(record.pmid for record in records if record.pmid)
        return CitationLookupResponse(
            records=records,
            candidate_pmids=candidate_pmids,
            meta=_candidate_meta(candidate_pmids),
        )

    async def find_related_articles(
        self, *, pmids: Sequence[str], mode: RelatedArticleMode = "similar", limit: int = 20
    ) -> RelatedArticlesResponse:
        related = await self.client.find_related_articles(pmids, mode, limit)
        candidate_pmids = _dedupe(record.pmid for record in related)
        unresolved = [pmid for pmid in pmids if pmid not in {record.source_pmid for record in related}]
        return RelatedArticlesResponse(
            source_pmids=list(pmids),
            mode=mode,
            related_articles=related,
            candidate_pmids=candidate_pmids,
            unresolved=unresolved,
            meta=_candidate_meta(candidate_pmids),
        )


def _dedupe(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _candidate_meta(candidate_pmids: list[str]) -> DiscoveryMeta:
    commands: list[dict[str, object]] = []
    if candidate_pmids:
        commands.extend(
            [
                {
                    "tool": "pubtator.stage_research_session",
                    "arguments": {"candidate_pmids": candidate_pmids},
                },
                {
                    "tool": "pubtator.index_review_evidence",
                    "arguments": {"pmids": candidate_pmids, "prepare_mode": "selected"},
                },
            ]
        )
    return DiscoveryMeta(
        source_urls=["https://www.ncbi.nlm.nih.gov/books/NBK25501/"],
        next_commands=commands,
    )
```

- [ ] **Step 4: Run service tests**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: add discovery service"
```

---

### Task 3: Implement Article ID Conversion Parsing

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Add client parsing test**

Append to `tests/unit/test_ncbi_discovery_service.py`:

```python
import httpx

from pubtator_link.services.ncbi_discovery import NcbiDiscoveryClient


class MockTransport:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, request=request)


async def test_ncbi_client_parses_id_conversion_json() -> None:
    transport = MockTransport(
        {
            "records": [
                {"pmid": "123", "pmcid": "PMC123", "doi": "10.1000/example"},
                {"requested-id": "bad", "status": "error"},
            ]
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.convert_article_ids(["PMC123", "bad"], "auto")

    assert records[0].status == "resolved"
    assert records[0].pmid == "123"
    assert records[1].status == "unresolved"
    await client.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_id_conversion_json -q
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement conversion method**

Replace `NcbiDiscoveryClient.convert_article_ids`:

```python
    async def convert_article_ids(
        self, ids: Sequence[str], source: ArticleIdKind
    ) -> list[ArticleIdConversionRecord]:
        response = await self._get(
            "idconv/v1.0/",
            {
                "ids": ",".join(ids),
                "format": "json",
                "tool": "pubtator-link",
            },
        )
        payload = response.json()
        records_by_requested: dict[str, ArticleIdConversionRecord] = {}
        for item in payload.get("records", []):
            requested = str(item.get("requested-id") or item.get("pmcid") or item.get("pmid") or item.get("doi") or "")
            pmid = item.get("pmid")
            pmcid = item.get("pmcid")
            doi = item.get("doi")
            status = "resolved" if pmid or pmcid or doi else "unresolved"
            record = ArticleIdConversionRecord(
                input_id=requested,
                input_kind=source,
                status=status,
                pmid=str(pmid) if pmid else None,
                pmcid=str(pmcid) if pmcid else None,
                doi=str(doi) if doi else None,
                reason=None if status == "resolved" else "not_found",
            )
            records_by_requested[requested] = record

        results: list[ArticleIdConversionRecord] = []
        for requested in ids:
            results.append(
                records_by_requested.get(
                    requested,
                    ArticleIdConversionRecord(
                        input_id=requested,
                        input_kind=source,
                        status="unresolved",
                        reason="not_found",
                    ),
                )
            )
        return results
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: parse NCBI article ID conversion"
```

---

### Task 4: Implement MeSH Lookup Parsing

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Add MeSH client test**

Append:

```python
async def test_ncbi_client_parses_mesh_lookup_json() -> None:
    transport = MockTransport(
        {
            "esearchresult": {
                "idlist": ["68050505"],
            },
            "result": {
                "68050505": {
                    "uid": "68050505",
                    "ds_meshterms": ["Familial Mediterranean Fever"],
                    "ds_scopenote": "An autoinflammatory disease.",
                    "ds_idxlinks": ["FMF"],
                    "ds_meshui": "D005505",
                    "ds_tree": ["C16.320.565"],
                }
            },
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    descriptors = await client.lookup_mesh("FMF", limit=5, exact=False)

    assert descriptors[0].name == "Familial Mediterranean Fever"
    assert descriptors[0].search_terms == ["Familial Mediterranean Fever[MeSH Terms]"]
    await client.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_mesh_lookup_json -q
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement MeSH lookup**

Implement `lookup_mesh` using `esearch.fcgi` and `esummary.fcgi` JSON. If test
transport returns a combined payload, accept it for parser unit tests:

```python
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
        idlist = search_payload.get("esearchresult", {}).get("idlist", [])
        if not idlist:
            return []

        if "result" in search_payload:
            summary_payload = search_payload
        else:
            summary_response = await self._get(
                "esummary.fcgi",
                {
                    "db": "mesh",
                    "id": ",".join(idlist),
                    "retmode": "json",
                    "tool": "pubtator-link",
                },
            )
            summary_payload = summary_response.json()

        result = summary_payload.get("result", {})
        descriptors: list[MeshDescriptor] = []
        for uid in idlist:
            item = result.get(uid, {})
            names = item.get("ds_meshterms") or []
            name = names[0] if names else item.get("title") or uid
            descriptors.append(
                MeshDescriptor(
                    ui=str(item.get("ds_meshui") or uid),
                    name=str(name),
                    scope_note=item.get("ds_scopenote"),
                    entry_terms=[str(value) for value in item.get("ds_idxlinks", [])],
                    tree_numbers=[str(value) for value in item.get("ds_tree", [])],
                    search_terms=[f"{name}[MeSH Terms]"],
                )
            )
        return descriptors
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: add MeSH vocabulary lookup"
```

---

### Task 5: Implement Citation Lookup Parsing

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Add citation client test**

Append:

```python
async def test_ncbi_client_parses_ecitmatch_lines() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        text = (
            "Ann Rheum Dis|2024|83|1|Author|Title|39596913|\n"
            "Unknown||||||NOT_FOUND|\n"
        )
        return httpx.Response(200, text=text, request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.lookup_citations(["known", "unknown"])

    assert records[0].status == "matched"
    assert records[0].pmid == "39596913"
    assert records[1].status == "not_found"
    await client.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_ecitmatch_lines -q
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement ECitMatch lookup**

Implement `lookup_citations`:

```python
    async def lookup_citations(self, citations: Sequence[str]) -> list[CitationLookupRecord]:
        response = await self._get(
            "ecitmatch.cgi",
            {
                "db": "pubmed",
                "retmode": "text",
                "bdata": "\n".join(citations),
                "tool": "pubtator-link",
            },
        )
        lines = [line for line in response.text.splitlines() if line.strip()]
        records: list[CitationLookupRecord] = []
        for index, citation in enumerate(citations):
            line = lines[index] if index < len(lines) else ""
            fields = line.split("|") if line else []
            pmid = fields[-2].strip() if len(fields) >= 2 else ""
            if pmid and pmid != "NOT_FOUND":
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
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: add citation to PMID lookup"
```

---

### Task 6: Implement Related Article Expansion

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Add related article client test**

Append:

```python
async def test_ncbi_client_parses_related_article_links() -> None:
    payload = {
        "linksets": [
            {
                "ids": ["123"],
                "linksetdbs": [
                    {
                        "linkname": "pubmed_pubmed",
                        "links": ["456", "789"],
                    }
                ],
            }
        ]
    }
    transport = MockTransport(payload)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_articles(["123"], "similar", 10)

    assert [record.pmid for record in records] == ["456", "789"]
    assert all(record.source_pmid == "123" for record in records)
    await client.close()
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_related_article_links -q
```

Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement related article method**

Implement `find_related_articles`:

```python
    async def find_related_articles(
        self, pmids: Sequence[str], mode: RelatedArticleMode, limit: int
    ) -> list[RelatedArticleRecord]:
        linkname = {
            "similar": "pubmed_pubmed",
            "cited_by": "pubmed_pubmed_citedin",
            "references": "pubmed_pubmed_refs",
        }[mode]
        response = await self._get(
            "elink.fcgi",
            {
                "dbfrom": "pubmed",
                "db": "pubmed",
                "id": ",".join(pmids),
                "linkname": linkname,
                "retmode": "json",
                "tool": "pubtator-link",
            },
        )
        payload = response.json()
        records: list[RelatedArticleRecord] = []
        for linkset in payload.get("linksets", []):
            source_ids = linkset.get("ids") or []
            source_pmid = str(source_ids[0]) if source_ids else ""
            for linksetdb in linkset.get("linksetdbs", []):
                for linked_pmid in linksetdb.get("links", [])[:limit]:
                    records.append(
                        RelatedArticleRecord(
                            source_pmid=source_pmid,
                            pmid=str(linked_pmid),
                            relation=mode,
                        )
                    )
        return records
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: add related article expansion"
```

---

### Task 7: Wire App Dependencies And REST Routes

**Files:**
- Create: `pubtator_link/api/routes/discovery.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/test_routes/test_discovery.py`

- [ ] **Step 1: Write route tests**

Create `tests/test_routes/test_discovery.py` using the repo's existing test
client dependency override style. Cover:

```python
async def test_convert_article_ids_route_returns_candidates(test_client):
    response = test_client.post(
        "/api/discovery/convert-article-ids",
        json={"ids": ["PMC123"], "source": "auto"},
    )
    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["123"]


async def test_mesh_route_returns_descriptors(test_client):
    response = test_client.get("/api/discovery/mesh", params={"query": "FMF", "limit": 5})
    assert response.status_code == 200
    assert response.json()["descriptors"][0]["name"] == "Familial Mediterranean Fever"


async def test_lookup_citations_route_returns_matched_status(test_client):
    response = test_client.post(
        "/api/discovery/lookup-citations",
        json={"citations": ["Ann Rheum Dis. 2024;83:1-2."]},
    )
    assert response.status_code == 200
    assert response.json()["records"][0]["status"] == "matched"


async def test_related_articles_route_returns_candidate_pmids(test_client):
    response = test_client.post(
        "/api/discovery/related-articles",
        json={"pmids": ["123"], "mode": "similar", "limit": 20},
    )
    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["456"]
```

Use a fake `DiscoveryService` dependency rather than real network calls.

- [ ] **Step 2: Run route tests to verify failure**

Run:

```bash
uv run pytest tests/test_routes/test_discovery.py -q
```

Expected: FAIL because routes and dependency do not exist.

- [ ] **Step 3: Add dependency construction**

In `pubtator_link/api/routes/dependencies.py`:

```python
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient

_ncbi_discovery_client: NcbiDiscoveryClient | None = None
_discovery_service: DiscoveryService | None = None
```

Add fields to `AppResources`:

```python
    ncbi_discovery_client: NcbiDiscoveryClient | None = None
    discovery_service: DiscoveryService | None = None
```

Construct in `create_app_resources`:

```python
        ncbi_discovery_client = NcbiDiscoveryClient()
        discovery_service = DiscoveryService(ncbi_discovery_client)
```

Return them in `AppResources(...)`, close the client in `close_app_resources`,
and add:

```python
async def get_discovery_service() -> DiscoveryService:
    global _ncbi_discovery_client, _discovery_service
    resources = current_app_resources()
    if resources is not None and resources.discovery_service is not None:
        return resources.discovery_service
    if _discovery_service is None:
        _ncbi_discovery_client = NcbiDiscoveryClient()
        _discovery_service = DiscoveryService(_ncbi_discovery_client)
    return _discovery_service
```

- [ ] **Step 4: Add discovery router**

Create `pubtator_link/api/routes/discovery.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from pubtator_link.api.routes.dependencies import get_discovery_service
from pubtator_link.models.discovery import (
    ArticleIdConversionRequest,
    ArticleIdConversionResponse,
    CitationLookupRequest,
    CitationLookupResponse,
    MeshLookupResponse,
    RelatedArticlesRequest,
    RelatedArticlesResponse,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService

router = APIRouter(prefix="/api/discovery", tags=["discovery"])


@router.post("/convert-article-ids", response_model=ArticleIdConversionResponse)
async def convert_article_ids(
    request: ArticleIdConversionRequest,
    service: DiscoveryService = Depends(get_discovery_service),
) -> ArticleIdConversionResponse:
    return await service.convert_article_ids(ids=request.ids, source=request.source)


@router.get("/mesh", response_model=MeshLookupResponse)
async def lookup_mesh(
    query: str,
    limit: int = 10,
    exact: bool = False,
    service: DiscoveryService = Depends(get_discovery_service),
) -> MeshLookupResponse:
    return await service.lookup_mesh(query=query, limit=limit, exact=exact)


@router.post("/lookup-citations", response_model=CitationLookupResponse)
async def lookup_citations(
    request: CitationLookupRequest,
    service: DiscoveryService = Depends(get_discovery_service),
) -> CitationLookupResponse:
    return await service.lookup_citation(citations=request.citations)


@router.post("/related-articles", response_model=RelatedArticlesResponse)
async def find_related_articles(
    request: RelatedArticlesRequest,
    service: DiscoveryService = Depends(get_discovery_service),
) -> RelatedArticlesResponse:
    return await service.find_related_articles(
        pmids=request.pmids,
        mode=request.mode,
        limit=request.limit,
    )
```

Register the router in `pubtator_link/server_manager.py`:

```python
from pubtator_link.api.routes.discovery import router as discovery_router
```

Then include it beside the other route modules:

```python
        app.include_router(discovery_router)
```

- [ ] **Step 5: Run route tests**

Run:

```bash
uv run pytest tests/test_routes/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/discovery.py pubtator_link/server_manager.py tests/test_routes/test_discovery.py
git commit -m "feat: expose discovery REST routes"
```

---

### Task 8: Add MCP Discovery Tools

**Files:**
- Create: `pubtator_link/mcp/tools/discovery.py`
- Modify: `pubtator_link/mcp/facade.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write MCP inventory/schema tests**

Add assertions in `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_discovery_tools_are_registered_with_specific_schemas() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    for name in [
        "pubtator.convert_article_ids",
        "pubtator.lookup_mesh",
        "pubtator.lookup_citation",
        "pubtator.find_related_articles",
    ]:
        assert name in tools
        assert "Research use only" in tools[name].description
        assert tools[name].output_schema
        assert tools[name].output_schema.get("properties")
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_discovery_tools_are_registered_with_specific_schemas -q
```

Expected: FAIL because tools are not registered.

- [ ] **Step 3: Implement MCP tool module**

Create `pubtator_link/mcp/tools/discovery.py`:

```python
from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.models.discovery import (
    ArticleIdConversionResponse,
    CitationLookupResponse,
    MeshLookupResponse,
    RelatedArticleMode,
    RelatedArticlesResponse,
)
from pubtator_link.services.ncbi_discovery import DiscoveryService, NcbiDiscoveryClient


def register_discovery_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.convert_article_ids",
        title="Convert PubMed Article Identifiers",
        output_schema=ArticleIdConversionResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def convert_article_ids(ids: list[str], source: str = "auto") -> dict:
        """Use this to convert PMID, PMCID, and DOI identifiers into candidate PMIDs for review staging or indexing. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with _discovery_service() as service:
            response = await service.convert_article_ids(ids=ids, source=source)  # type: ignore[arg-type]
            return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.lookup_mesh",
        title="Lookup MeSH Vocabulary",
        output_schema=MeshLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_mesh(
        query: Annotated[str, Field(min_length=1)],
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        exact: bool = False,
    ) -> dict:
        """Use this to find MeSH descriptors and search terms before PubTator literature search. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with _discovery_service() as service:
            response = await service.lookup_mesh(query=query, limit=limit, exact=exact)
            return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.lookup_citation",
        title="Resolve Citation To PMID",
        output_schema=CitationLookupResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def lookup_citation(citations: list[str]) -> dict:
        """Use this to resolve known article citations into candidate PMIDs for review staging or indexing. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with _discovery_service() as service:
            response = await service.lookup_citation(citations=citations)
            return response.model_dump(by_alias=True)

    @mcp.tool(
        name="pubtator.find_related_articles",
        title="Find Related PubMed Articles",
        output_schema=RelatedArticlesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_articles(
        pmids: list[str],
        mode: RelatedArticleMode = "similar",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict:
        """Use this to expand a review corpus from seed PMIDs using similar, cited-by, or reference links. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with _discovery_service() as service:
            response = await service.find_related_articles(pmids=pmids, mode=mode, limit=limit)
            return response.model_dump(by_alias=True)


class _discovery_service:
    def __init__(self) -> None:
        self.client = NcbiDiscoveryClient()
        self.service = DiscoveryService(self.client)

    async def __aenter__(self) -> DiscoveryService:
        return self.service

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.client.close()
```

- [ ] **Step 4: Register tools in facade**

Modify `pubtator_link/mcp/facade.py`:

```python
from pubtator_link.mcp.tools.discovery import register_discovery_tools
```

Call `register_discovery_tools(mcp)` after `register_literature_tools(mcp)`.

- [ ] **Step 5: Run MCP tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/tools/discovery.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: expose discovery MCP tools"
```

---

### Task 9: Update Resources And Docs

**Files:**
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `README.md`
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`

- [ ] **Step 1: Update MCP resources**

Add discovery guidance to `pubtator_link/mcp/resources.py` near the literature
workflow text:

```python
"discovery_workflow": [
    "Use pubtator.lookup_mesh to normalize biomedical vocabulary before search.",
    "Use pubtator.lookup_citation when a user provides formatted references.",
    "Use pubtator.find_related_articles to expand from seed PMIDs.",
    "Pass candidate_pmids to pubtator.stage_research_session before indexing large corpora.",
],
```

- [ ] **Step 2: Update README tool table**

Add rows for:

- `pubtator.convert_article_ids`
- `pubtator.lookup_mesh`
- `pubtator.lookup_citation`
- `pubtator.find_related_articles`

Each row should say the tools are read-only, research-use scoped, and return
candidate PMIDs for staging/indexing where applicable.

- [ ] **Step 3: Update roadmap status**

In
`docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`,
add a planned/completed line for review-feeding discovery tools depending on
implementation state.

- [ ] **Step 4: Run docs/resource tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md pubtator_link/mcp/resources.py docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md
git commit -m "docs: document discovery workflow"
```

---

### Task 10: Final Verification

**Files:**
- All files modified in Tasks 1-9.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
uv run pytest \
  tests/unit/test_discovery_models.py \
  tests/unit/test_ncbi_discovery_service.py \
  tests/test_routes/test_discovery.py \
  tests/unit/mcp/test_mcp_facade.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run full local CI**

Run:

```bash
make ci-local
```

Expected: Ruff format check, Ruff lint, mypy if included by the Makefile target,
and tests all pass. PostgreSQL integration tests may skip when
`PUBTATOR_LINK_TEST_DATABASE_URL` is not set.

- [ ] **Step 3: Inspect git status**

Run:

```bash
git status --short
```

Expected: clean working tree after all task commits.

---

## Self-Review Notes

- Spec coverage: Tasks cover models, service/client, four public tools, REST,
  MCP schemas, docs, and verification.
- Scope check: This plan stays within NCBI review-feeding discovery. It does not
  add citation formatting, bibliometrics, scraping, or non-NCBI source graphs.
- Type consistency: Public names use `convert_article_ids`, `lookup_mesh`,
  `lookup_citation`, and `find_related_articles` consistently across models,
  routes, MCP tools, and tests.
