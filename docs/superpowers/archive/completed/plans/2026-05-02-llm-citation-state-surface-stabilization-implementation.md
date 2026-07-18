# LLM Citation State Surface Stabilization Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the LLM-consumer gaps documented in `docs/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md` and specified in `docs/superpowers/specs/2026-05-02-llm-citation-state-surface-stabilization-design.md`: publication metadata, honest async state, accurate preflight labeling, useful index samples, snapshot provenance, workflow guidance, and corpus suggestions.

**Architecture:** Add small typed model modules for metadata, workflow help, and corpus suggestions. Keep NCBI access behind service classes. Keep REST routes thin. Keep MCP tools as adapters over the same services. Add focused review-state helpers rather than embedding polling and snapshot logic in tool adapters.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, httpx, asyncpg, pytest, respx, Ruff, mypy, uv, Makefile.

---

## Requirements Map

This plan covers the approved option `2` from the spec discussion.

| Requirement | Implemented By |
| --- | --- |
| `pubtator.get_publication_metadata(pmids=["33454820"])` with authors, citation fields, publication type, and MeSH headings | Tasks 1-4 |
| REST equivalent for metadata retrieval | Task 3 |
| Search results can include metadata with `metadata="none" | "basic" | "full"` | Task 5 |
| `coverage_hint` labels pessimistic results as pre-resolution best guesses | Task 6 |
| `retry_after_ms` is absent for terminal review preparation states | Task 7 |
| `index_snapshot_date` appears on index, inspect, retrieve, and audit responses | Task 7 |
| Inspect samples skip trivial headings and expose sample warnings | Task 8 |
| `pubtator.workflow_help()` gives canonical LLM workflow guidance | Task 9 |
| `pubtator.suggest_corpus(question, max_pmids)` returns a small candidate corpus with roles and handoff metadata | Tasks 10-11 |
| Public tools remain research-use scoped and non-destructive | Tasks 4, 9, 11 |
| Docs and capability resources updated | Task 12 |
| Focused tests and `make ci-local` pass | Every task, final verification |

## Existing Boundaries To Preserve

- Keep `pubtator_link/mcp/service_adapters.py` as an adapter layer only. Move reusable decisions into services or helpers.
- Keep route handlers thin and use dependency functions from `pubtator_link/api/routes/dependencies.py`.
- Reuse `pubtator_link/services/provenance.py` for snapshot and cache-key utilities.
- Reuse `pubtator_link/services/source_preflight.py` for coverage hints.
- Reuse `pubtator_link/services/ncbi_discovery.py` constants and retry patterns for NCBI calls.
- Keep public MCP tools read-only and research-use scoped.
- Do not rename existing tools in this plan. Name shortening is a breaking API change and needs a separate compatibility plan.

## File Structure

New focused files:

- `pubtator_link/models/publication_metadata.py`: Pydantic request, response, author, citation, and publication metadata models.
- `pubtator_link/services/publication_metadata.py`: NCBI ESummary and EFetch metadata retrieval plus citation formatting.
- `pubtator_link/services/review_state.py`: Shared polling hint and index snapshot date helpers.
- `pubtator_link/models/workflow_help.py`: Typed workflow help response models.
- `pubtator_link/services/workflow_help.py`: Small static workflow guidance service.
- `pubtator_link/models/corpus_suggestion.py`: Typed corpus suggestion request, candidate, trace, and response models.
- `pubtator_link/services/corpus_suggestion.py`: Deterministic search composition, deduplication, metadata enrichment, coverage hinting, role assignment, and handoff commands.
- `tests/unit/test_publication_metadata_models.py`: Metadata model tests.
- `tests/unit/test_publication_metadata_service.py`: NCBI metadata parsing and partial-failure tests.
- `tests/unit/test_review_state.py`: Polling hint and snapshot helper tests.
- `tests/unit/test_workflow_help.py`: Workflow guidance tests.
- `tests/unit/test_corpus_suggestion_service.py`: Corpus suggestion model and service tests.

Existing files to modify:

- `pubtator_link/api/routes/dependencies.py`: Add metadata and corpus suggestion dependencies; wire source preflight ID conversion.
- `pubtator_link/api/routes/publications.py`: Add `POST /api/publications/metadata`.
- `pubtator_link/api/routes/search.py`: Add `metadata` query parameter and metadata enrichment.
- `pubtator_link/api/routes/discovery.py`: Add `POST /api/discovery/suggest-corpus`.
- `pubtator_link/api/routes/reviews.py`: Pass new inspect sampling fields and snapshot fields through review responses.
- `pubtator_link/models/review_rerag.py`: Add coverage reason, sampling fields, sample warning, and index snapshot fields.
- `pubtator_link/repositories/review_rerag.py`: Improve inspect sample ranking and warning generation.
- `pubtator_link/services/search_shaping.py`: Add search metadata mode and merge metadata into shaped results.
- `pubtator_link/services/source_preflight.py`: Mark unresolved PMCID checks as pre-resolution best guesses.
- `pubtator_link/services/review_context_service.py`: Add index snapshot dates and pass sample selection options.
- `pubtator_link/mcp/service_adapters.py`: Add metadata and corpus adapters; centralize retry hints.
- `pubtator_link/mcp/tools/publications.py`: Register `pubtator.get_publication_metadata`.
- `pubtator_link/mcp/tools/literature.py`: Add search metadata argument.
- `pubtator_link/mcp/tools/reviews.py`: Add inspect sample arguments.
- `pubtator_link/mcp/tools/discovery.py`: Register `pubtator.suggest_corpus`.
- `pubtator_link/mcp/metadata.py`: Register `pubtator.workflow_help`.
- `pubtator_link/mcp/resources.py`: Update capabilities and workflow resource payloads.
- `tests/test_routes/test_publications.py`: Metadata route coverage.
- `tests/test_routes/test_search.py`: Search metadata route coverage.
- `tests/test_routes/test_discovery.py`: Corpus suggestion route coverage.
- `tests/test_routes/test_reviews.py`: Snapshot and sample argument route coverage.
- `tests/unit/mcp/test_mcp_facade.py`: Public tool catalog coverage.
- `tests/unit/mcp/test_mcp_service_adapters.py`: MCP adapter behavior coverage.
- `tests/unit/test_search_shaping.py`: Search metadata merge tests.
- `tests/unit/test_source_preflight.py`: ID resolution honesty tests.
- `tests/unit/test_review_context_service.py`: Snapshot and sample option tests.
- `tests/unit/test_review_rerag_repository.py`: Useful sample selection tests.
- `README.md`: Public tool and workflow documentation.
- `docs/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md`: Implementation status update.

## Task 1: Add Typed Publication Metadata Models

**Purpose:** Define the metadata contract before writing clients or routes.

**Files:**

- Add `pubtator_link/models/publication_metadata.py`
- Add `tests/unit/test_publication_metadata_models.py`

**TDD Steps:**

- [ ] Create the model tests first.

```python
# tests/unit/test_publication_metadata_models.py
from pubtator_link.models.publication_metadata import (
    PublicationAuthor,
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)


def test_publication_metadata_accepts_complete_citation_fields() -> None:
    metadata = PublicationMetadata(
        pmid="33454820",
        title="Adherence to best practice consensus guidelines for familial Mediterranean fever",
        journal="Rheumatology International",
        pub_year=2022,
        pub_date="2022 Jan",
        volume="42",
        issue="1",
        pages="87-94",
        doi="10.1007/s00296-020-04776-1",
        pmcid="PMC7811395",
        authors=[
            PublicationAuthor(
                last_name="Kavrul Kayaalp",
                fore_name="Gul",
                initials="GK",
                collective_name=None,
            )
        ],
        publication_types=["Journal Article"],
        mesh_headings=["Familial Mediterranean Fever"],
        nlm_citation="Kavrul Kayaalp G. Rheumatol Int. 2022;42(1):87-94.",
        bibtex="@article{pmid33454820,title={Adherence to best practice consensus guidelines for familial Mediterranean fever}}",
        coverage="full_text",
        coverage_reason="pmc_oa_bioc",
    )

    assert metadata.authors[0].display_name == "Kavrul Kayaalp G"
    assert metadata.vancouver_author_string == "Kavrul Kayaalp G"
    assert metadata.citation_key == "PMID:33454820"


def test_publication_metadata_request_normalizes_pmids() -> None:
    request = PublicationMetadataRequest(pmids=[" PMID:33454820 ", "33726481"], include_mesh=True)

    assert request.pmids == ["33454820", "33726481"]
    assert request.include_mesh is True


def test_publication_metadata_response_preserves_failed_pmids() -> None:
    response = PublicationMetadataResponse(
        success=True,
        metadata=[],
        failed_pmids={"0": "invalid PMID"},
        _meta={"next_commands": []},
    )

    assert response.failed_pmids == {"0": "invalid PMID"}
```

- [ ] Run the failing model tests.

```bash
uv run pytest tests/unit/test_publication_metadata_models.py -q
```

Expected output:

```text
ModuleNotFoundError: No module named 'pubtator_link.models.publication_metadata'
```

- [ ] Add `pubtator_link/models/publication_metadata.py`.

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from pubtator_link.models.review_rerag import CoverageReason, CoverageTier


class PublicationAuthor(BaseModel):
    """Structured publication author metadata."""

    last_name: str | None = None
    fore_name: str | None = None
    initials: str | None = None
    collective_name: str | None = None

    @computed_field
    @property
    def display_name(self) -> str:
        if self.collective_name:
            return self.collective_name
        parts: list[str] = []
        if self.last_name:
            parts.append(self.last_name)
        if self.initials:
            parts.append(self.initials)
        if not parts and self.fore_name:
            parts.append(self.fore_name)
        return " ".join(parts)


class PublicationMetadata(BaseModel):
    """Citation-grade publication metadata keyed by PMID."""

    model_config = ConfigDict(populate_by_name=True)

    pmid: str
    title: str | None = None
    journal: str | None = None
    pub_year: int | None = None
    pub_date: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    authors: list[PublicationAuthor] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    mesh_headings: list[str] = Field(default_factory=list)
    nlm_citation: str | None = None
    bibtex: str | None = None
    coverage: CoverageTier | None = None
    coverage_reason: CoverageReason | None = None

    @computed_field
    @property
    def citation_key(self) -> str:
        return f"PMID:{self.pmid}"

    @computed_field
    @property
    def vancouver_author_string(self) -> str:
        names = [author.display_name for author in self.authors if author.display_name]
        if len(names) > 6:
            return ", ".join(names[:6]) + ", et al"
        return ", ".join(names)


class PublicationMetadataRequest(BaseModel):
    """Request publication metadata for known PMIDs."""

    pmids: list[str] = Field(min_length=1, max_length=100)
    include_mesh: bool = True
    include_publication_types: bool = True
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both"
    include_coverage: bool = True

    @field_validator("pmids")
    @classmethod
    def normalize_pmids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for pmid in value:
            cleaned = pmid.strip().removeprefix("PMID:").strip()
            if cleaned:
                normalized.append(cleaned)
        return list(dict.fromkeys(normalized))


class PublicationMetadataResponse(BaseModel):
    """Metadata response with partial-failure details."""

    success: bool = True
    metadata: list[PublicationMetadata] = Field(default_factory=list)
    failed_pmids: dict[str, str] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
```

- [ ] Run the model tests again.

```bash
uv run pytest tests/unit/test_publication_metadata_models.py -q
```

Expected output:

```text
3 passed
```

- [ ] Commit Task 1.

```bash
git add pubtator_link/models/publication_metadata.py tests/unit/test_publication_metadata_models.py
git commit -m "feat: add publication metadata models"
```

## Task 2: Add NCBI Publication Metadata Client And Service

**Purpose:** Retrieve citation-grade metadata without forcing LLMs to infer authors or citation fields from abstracts.

**Files:**

- Add `pubtator_link/services/publication_metadata.py`
- Add `tests/unit/test_publication_metadata_service.py`

**Design Notes:**

- Use NCBI ESummary for authors, journal, year, volume, issue, pages, DOI, PMC ID, and publication types.
- Use NCBI EFetch only when `include_mesh=True`, because MeSH headings are not reliable in ESummary.
- Keep malformed or missing PMIDs in `failed_pmids`.
- Preserve input PMID order in output.
- Use the same retry wrapper pattern as `NcbiDiscoveryClient`.

**TDD Steps:**

- [ ] Create service tests first.

```python
# tests/unit/test_publication_metadata_service.py
import httpx
import pytest

from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.publication_metadata import NcbiPublicationMetadataClient, PublicationMetadataService


@pytest.mark.asyncio
async def test_publication_metadata_service_parses_esummary_and_mesh() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "esummary.fcgi" in url:
            return httpx.Response(
                200,
                json={
                    "result": {
                        "uids": ["33454820"],
                        "33454820": {
                            "uid": "33454820",
                            "title": "Adherence to best practice consensus guidelines for familial Mediterranean fever",
                            "fulljournalname": "Rheumatology International",
                            "pubdate": "2022 Jan",
                            "epubdate": "",
                            "sortpubdate": "2022/01/01 00:00",
                            "volume": "42",
                            "issue": "1",
                            "pages": "87-94",
                            "articleids": [
                                {"idtype": "doi", "value": "10.1007/s00296-020-04776-1"},
                                {"idtype": "pmc", "value": "PMC7811395"},
                            ],
                            "authors": [
                                {
                                    "name": "Kavrul Kayaalp G",
                                    "authtype": "Author",
                                    "clusterid": "",
                                }
                            ],
                            "pubtype": ["Journal Article"],
                        },
                    }
                },
            )
        if "efetch.fcgi" in url:
            return httpx.Response(
                200,
                text=(
                    "<PubmedArticleSet><PubmedArticle><MedlineCitation>"
                    "<MeshHeadingList><MeshHeading><DescriptorName>"
                    "Familial Mediterranean Fever"
                    "</DescriptorName></MeshHeading></MeshHeadingList>"
                    "</MedlineCitation></PubmedArticle></PubmedArticleSet>"
                ),
            )
        return httpx.Response(404)

    client = NcbiPublicationMetadataClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    service = PublicationMetadataService(client=client)

    response = await service.get_metadata(
        PublicationMetadataRequest(pmids=["33454820"], include_mesh=True, include_citations="both")
    )

    assert response.success is True
    assert response.failed_pmids == {}
    assert response.metadata[0].authors[0].display_name == "Kavrul Kayaalp G"
    assert response.metadata[0].journal == "Rheumatology International"
    assert response.metadata[0].volume == "42"
    assert response.metadata[0].issue == "1"
    assert response.metadata[0].pages == "87-94"
    assert response.metadata[0].doi == "10.1007/s00296-020-04776-1"
    assert response.metadata[0].pmcid == "PMC7811395"
    assert response.metadata[0].mesh_headings == ["Familial Mediterranean Fever"]
    assert response.metadata[0].nlm_citation is not None
    assert response.metadata[0].bibtex is not None


@pytest.mark.asyncio
async def test_publication_metadata_service_reports_missing_pmids() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": {"uids": []}})

    client = NcbiPublicationMetadataClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    service = PublicationMetadataService(client=client)

    response = await service.get_metadata(PublicationMetadataRequest(pmids=["999999999"], include_mesh=False))

    assert response.success is True
    assert response.metadata == []
    assert response.failed_pmids == {"999999999": "metadata_not_found"}
```

- [ ] Run the failing service tests.

```bash
uv run pytest tests/unit/test_publication_metadata_service.py -q
```

Expected output:

```text
ModuleNotFoundError: No module named 'pubtator_link.services.publication_metadata'
```

- [ ] Add `pubtator_link/services/publication_metadata.py`.

Implementation constraints:

- Define `NcbiPublicationMetadataClient`.
- Define `PublicationMetadataService`.
- Use `NCBI_EUTILS_BASE_URL` from `pubtator_link.services.ncbi_discovery`.
- Add private helpers:
  - `_parse_pub_year(pubdate: str | None, sortpubdate: str | None) -> int | None`
  - `_extract_article_id(articleids: list[dict[str, str]], idtype: str) -> str | None`
  - `_parse_author(name: str) -> PublicationAuthor`
  - `_parse_mesh_xml(xml_text: str) -> dict[str, list[str]]`
  - `_build_nlm_citation(metadata: PublicationMetadata) -> str`
  - `_build_bibtex(metadata: PublicationMetadata) -> str`

The client should expose:

```python
class NcbiPublicationMetadataClient:
    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        *,
        timeout: float = 20.0,
        tool_name: str = "publication_metadata",
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout
        self._tool_name = tool_name

    async def fetch_esummary(self, pmids: list[str]) -> dict[str, dict[str, Any]]:
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json",
        }
        data = await self._get_json("esummary.fcgi", params=params)
        result = data.get("result", {})
        return {
            pmid: result[pmid]
            for pmid in result.get("uids", [])
            if isinstance(result.get(pmid), dict)
        }

    async def fetch_mesh_headings(self, pmids: list[str]) -> dict[str, list[str]]:
        params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
        }
        text = await self._get_text("efetch.fcgi", params=params)
        return _parse_mesh_xml(text)
```

The service should expose:

```python
class PublicationMetadataService:
    def __init__(
        self,
        client: NcbiPublicationMetadataClient,
        *,
        coverage_provider: Callable[[list[str]], Awaitable[dict[str, tuple[CoverageTier, CoverageReason]]]] | None = None,
    ) -> None:
        self._client = client
        self._coverage_provider = coverage_provider

    async def get_metadata(self, request: PublicationMetadataRequest) -> PublicationMetadataResponse:
        esummary = await self._client.fetch_esummary(request.pmids)
        mesh_by_pmid = await self._client.fetch_mesh_headings(request.pmids) if request.include_mesh else {}
        coverage_by_pmid = await self._coverage_provider(request.pmids) if request.include_coverage and self._coverage_provider else {}

        metadata: list[PublicationMetadata] = []
        failed_pmids: dict[str, str] = {}
        for pmid in request.pmids:
            payload = esummary.get(pmid)
            if payload is None:
                failed_pmids[pmid] = "metadata_not_found"
                continue
            item = self._from_esummary(
                pmid,
                payload,
                mesh_by_pmid.get(pmid, []),
                coverage_by_pmid.get(pmid),
                request.include_publication_types,
            )
            if request.include_citations in {"nlm", "both"}:
                item.nlm_citation = _build_nlm_citation(item)
            if request.include_citations in {"bibtex", "both"}:
                item.bibtex = _build_bibtex(item)
            metadata.append(item)

        return PublicationMetadataResponse(
            success=True,
            metadata=metadata,
            failed_pmids=failed_pmids,
            _meta={
                "source": "NCBI ESummary and EFetch",
                "next_commands": [
                    "Use pubtator.get_publication_passages for citable passage text.",
                    "Use pubtator.index_review_evidence after selecting the final PMID corpus.",
                ],
            },
        )
```

- [ ] Run the service tests.

```bash
uv run pytest tests/unit/test_publication_metadata_service.py tests/unit/test_publication_metadata_models.py -q
```

Expected output:

```text
5 passed
```

- [ ] Commit Task 2.

```bash
git add pubtator_link/services/publication_metadata.py tests/unit/test_publication_metadata_service.py
git commit -m "feat: fetch publication metadata from NCBI"
```

## Task 3: Add REST Metadata Route And Dependency

**Purpose:** Give non-MCP clients the same metadata contract.

**Files:**

- Update `pubtator_link/api/routes/dependencies.py`
- Update `pubtator_link/api/routes/publications.py`
- Update `tests/test_routes/test_publications.py`

**TDD Steps:**

- [ ] Add a route test first.

```python
from fastapi.testclient import TestClient

from pubtator_link.api.routes.dependencies import get_publication_metadata_service
from pubtator_link.models.publication_metadata import PublicationAuthor, PublicationMetadata, PublicationMetadataResponse
from pubtator_link.server_manager import UnifiedServerManager


class FakePublicationMetadataService:
    async def get_metadata(self, request):
        assert request.pmids == ["33454820"]
        return PublicationMetadataResponse(
            success=True,
            metadata=[
                PublicationMetadata(
                    pmid="33454820",
                    title="Adherence to best practice consensus guidelines for familial Mediterranean fever",
                    journal="Rheumatology International",
                    pub_year=2022,
                    volume="42",
                    issue="1",
                    pages="87-94",
                    authors=[PublicationAuthor(last_name="Kavrul Kayaalp", initials="GK")],
                    publication_types=["Journal Article"],
                    mesh_headings=["Familial Mediterranean Fever"],
                )
            ],
            failed_pmids={},
            _meta={"next_commands": []},
        )


def test_publication_metadata_route():
    manager = UnifiedServerManager()
    app = manager.create_app()
    service = FakePublicationMetadataService()
    app.dependency_overrides[get_publication_metadata_service] = lambda: service

    with TestClient(app) as client:
        response = client.post(
            "/api/publications/metadata",
            json={"pmids": ["33454820"], "include_mesh": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["metadata"][0]["pmid"] == "33454820"
    assert payload["metadata"][0]["authors"][0]["display_name"] == "Kavrul Kayaalp GK"
```

- [ ] Run the failing route test.

```bash
uv run pytest tests/test_routes/test_publications.py -q
```

Expected output:

```text
ImportError: cannot import name 'get_publication_metadata_service'
```

- [ ] Add the dependency in `pubtator_link/api/routes/dependencies.py`.

```python
_publication_metadata_service: PublicationMetadataService | None = None


def get_publication_metadata_service() -> PublicationMetadataService:
    global _publication_metadata_service
    if _publication_metadata_service is None:
        _publication_metadata_service = PublicationMetadataService(
            client=NcbiPublicationMetadataClient(),
            coverage_provider=_publication_metadata_coverage_provider,
        )
    return _publication_metadata_service


async def _publication_metadata_coverage_provider(
    pmids: list[str],
) -> dict[str, tuple[CoverageTier, CoverageReason]]:
    preflight = get_source_preflight_service()
    response = await preflight.preflight_pmids(pmids)
    return {
        item.pmid: (item.expected_coverage, item.coverage_reason)
        for item in response.items
    }
```

- [ ] Add the route in `pubtator_link/api/routes/publications.py`.

```python
@router.post("/metadata", response_model=PublicationMetadataResponse)
async def get_publication_metadata(
    request: PublicationMetadataRequest,
    service: PublicationMetadataService = Depends(dependencies.get_publication_metadata_service),
) -> PublicationMetadataResponse:
    """Return citation-grade metadata for known PMIDs."""

    return await service.get_metadata(request)
```

- [ ] Run route and metadata tests.

```bash
uv run pytest tests/test_routes/test_publications.py tests/unit/test_publication_metadata_service.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 3.

```bash
git add pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/publications.py tests/test_routes/test_publications.py
git commit -m "feat: add publication metadata route"
```

## Task 4: Add MCP Publication Metadata Tool

**Purpose:** Expose citation metadata to LLM consumers as `pubtator.get_publication_metadata`.

**Files:**

- Update `pubtator_link/mcp/tools/publications.py`
- Update `pubtator_link/mcp/service_adapters.py`
- Update `tests/unit/mcp/test_mcp_facade.py`
- Update `tests/unit/mcp/test_mcp_service_adapters.py`

**TDD Steps:**

- [ ] Add `pubtator.get_publication_metadata` to `EXPECTED_PUBLIC_TOOL_NAMES` in `tests/unit/mcp/test_mcp_facade.py`.

```python
"pubtator.get_publication_metadata",
```

- [ ] Add an adapter test.

```python
async def test_get_publication_metadata_impl_returns_typed_payload(monkeypatch):
    from pubtator_link.mcp import service_adapters
    from pubtator_link.models.publication_metadata import PublicationMetadataResponse

    class FakeService:
        async def get_metadata(self, request):
            assert request.pmids == ["33454820"]
            return PublicationMetadataResponse(success=True, metadata=[], failed_pmids={}, _meta={"next_commands": []})

    result = await service_adapters.get_publication_metadata_impl(
        service=FakeService(),
        pmids=["33454820"],
        include_mesh=True,
        include_publication_types=True,
        include_citations="both",
        include_coverage=True,
    )

    assert result["success"] is True
    assert result["metadata"] == []
```

- [ ] Run the failing MCP tests.

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
AssertionError
```

- [ ] Add `get_publication_metadata_impl` to `pubtator_link/mcp/service_adapters.py`.

```python
async def get_publication_metadata_impl(
    *,
    service: PublicationMetadataService,
    pmids: list[str],
    include_mesh: bool = True,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both",
    include_coverage: bool = True,
) -> dict[str, Any]:
    request = PublicationMetadataRequest(
        pmids=pmids,
        include_mesh=include_mesh,
        include_publication_types=include_publication_types,
        include_citations=include_citations,
        include_coverage=include_coverage,
    )
    response = await service.get_metadata(request)
    return response.model_dump(by_alias=True)
```

- [ ] Register the tool in `pubtator_link/mcp/tools/publications.py`.

```python
@mcp.tool(
    name="pubtator.get_publication_metadata",
    description=(
        "Return citation-grade metadata for known PMIDs, including authors, journal, year, "
        "volume, issue, pages, DOI, publication types, and MeSH headings. Use this before "
        "writing Vancouver-style or NLM-style citations. Research use only; not for diagnosis, "
        "treatment, triage, patient management, or clinical decision support."
    ),
)
async def get_publication_metadata(
    pmids: Annotated[list[str], Field(min_length=1, max_length=100)],
    include_mesh: bool = True,
    include_publication_types: bool = True,
    include_citations: Literal["none", "nlm", "bibtex", "both"] = "both",
    include_coverage: bool = True,
) -> dict[str, Any]:
    return await service_adapters.get_publication_metadata_impl(
        service=dependencies.get_publication_metadata_service(),
        pmids=pmids,
        include_mesh=include_mesh,
        include_publication_types=include_publication_types,
        include_citations=include_citations,
        include_coverage=include_coverage,
    )
```

- [ ] Run MCP tests.

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 4.

```bash
git add pubtator_link/mcp/tools/publications.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: expose publication metadata MCP tool"
```

## Task 5: Add Optional Metadata Enrichment To Search Results

**Purpose:** Let LLMs choose a final corpus with author and citation fields without paying a second tool call when they need metadata inline.

**Files:**

- Update `pubtator_link/services/search_shaping.py`
- Update `pubtator_link/api/routes/search.py`
- Update `pubtator_link/mcp/tools/literature.py`
- Update `tests/unit/test_search_shaping.py`
- Update `tests/test_routes/test_search.py`
- Update `tests/unit/mcp/test_mcp_service_adapters.py`

**Contract:**

```python
SearchMetadataMode = Literal["none", "basic", "full"]
```

- `none`: existing compact default for MCP.
  - `basic`: add authors, pub_year, journal, volume, issue, pages, doi, pmcid, publication_types.
- `full`: add all `basic` fields plus MeSH headings and citation strings according to `include_citations`.

**TDD Steps:**

- [ ] Add shaping tests first.

```python
def test_shaped_search_response_can_merge_basic_metadata():
    raw = {
        "query": "MEFV",
        "total": 1,
        "results": [{"pmid": "33454820", "title": "Title from search", "authors": []}],
    }
    metadata_by_pmid = {
        "33454820": {
            "pmid": "33454820",
            "authors": [{"last_name": "Kavrul Kayaalp", "initials": "GK", "display_name": "Kavrul Kayaalp GK"}],
            "journal": "Rheumatology International",
            "pub_year": 2022,
            "doi": "10.1007/s00296-020-04776-1",
            "pmcid": "PMC7811395",
            "publication_types": ["Journal Article"],
        }
    }

    shaped = shaped_search_response(raw, response_mode="compact", metadata="basic", metadata_by_pmid=metadata_by_pmid)

    assert shaped["results"][0]["authors"][0]["display_name"] == "Kavrul Kayaalp GK"
    assert shaped["results"][0]["journal"] == "Rheumatology International"
    assert shaped["results"][0]["volume"] is None
```

- [ ] Run the failing shaping test.

```bash
uv run pytest tests/unit/test_search_shaping.py -q
```

Expected output:

```text
TypeError
```

- [ ] Update `search_shaping.py`.

Add:

```python
SearchMetadataMode = Literal["none", "basic", "full"]
```

Update `shaped_search_response` signature:

```python
def shaped_search_response(
    raw_response: Mapping[str, Any],
    *,
    response_mode: SearchResponseMode,
    include_citations: IncludeCitations = "none",
    text_hl_format: TextHighlightFormat = "plain",
    coverage: SearchCoverageMode = "none",
    coverage_by_pmid: Mapping[str, Mapping[str, Any]] | None = None,
    metadata: SearchMetadataMode = "none",
    metadata_by_pmid: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
```

Add helper:

```python
def _merge_metadata_fields(
    shaped: dict[str, Any],
    metadata: SearchMetadataMode,
    metadata_item: Mapping[str, Any] | None,
) -> None:
    if metadata == "none" or metadata_item is None:
        return

    basic_fields = ("authors", "journal", "pub_year", "volume", "issue", "pages", "doi", "pmcid", "publication_types")
    full_fields = basic_fields + ("mesh_headings", "nlm_citation", "bibtex")
    fields = full_fields if metadata == "full" else basic_fields
    for field_name in fields:
        shaped[field_name] = metadata_item.get(field_name)
```

Call `_merge_metadata_fields` at the end of `shaped_search_result`.

- [ ] Update route and MCP tool signatures:

REST default:

```python
metadata: SearchMetadataMode = Query(default="none")
```

MCP default:

```python
metadata: SearchMetadataMode = "none"
```

When `metadata != "none"`, call `PublicationMetadataService.get_metadata()` for returned PMIDs and pass a dict keyed by PMID into `shaped_search_response`.

- [ ] Use request settings:

```python
metadata_request = PublicationMetadataRequest(
    pmids=pmids,
    include_mesh=metadata == "full",
    include_publication_types=True,
    include_citations=include_citations if metadata == "full" else "none",
    include_coverage=False,
)
```

- [ ] Add a route test that stubs `get_publication_metadata_service` and calls:

```text
GET /api/search/?q=MEFV&metadata=basic&response_mode=compact
```

Assert `results[0].authors` is populated.

- [ ] Add an adapter test named `test_search_literature_impl_enriches_basic_metadata` that passes `metadata="basic"` and a fake metadata service returning one author for PMID `33454820`. Assert `result["results"][0]["authors"][0]["display_name"] == "Kavrul Kayaalp GK"`.

- [ ] Run focused tests.

```bash
uv run pytest tests/unit/test_search_shaping.py tests/test_routes/test_search.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 5.

```bash
git add pubtator_link/services/search_shaping.py pubtator_link/api/routes/search.py pubtator_link/mcp/tools/literature.py tests/unit/test_search_shaping.py tests/test_routes/test_search.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: enrich search results with optional metadata"
```

## Task 6: Make Source Preflight ID Resolution Honest

**Purpose:** Avoid misleading `coverage_reason="no_pmcid"` when a PMID has not been resolved through the NCBI ID converter.

**Files:**

- Update `pubtator_link/models/review_rerag.py`
- Update `pubtator_link/api/routes/dependencies.py`
- Update `pubtator_link/services/source_preflight.py`
- Update `tests/unit/test_source_preflight.py`

**Contract:**

- Add `pre_resolution_best_guess` to `CoverageReason`.
- `coverage_hint` can still be pessimistic, but it must say the paper was not fully resolved.
- The default API dependency must wire real ID conversion through `NcbiDiscoveryClient.convert_article_ids`.

**TDD Steps:**

- [ ] Add tests first.

```python
@pytest.mark.asyncio
async def test_preflight_labels_no_pmcid_after_failed_id_resolution_as_best_guess():
    async def id_converter(pmids):
        raise RuntimeError("NCBI unavailable")

    async def abstract_available(pmid):
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pubtator_abstract_available=abstract_available,
    )

    response = await service.preflight_pmids(["33454820"])

    assert response.items[0].expected_coverage == "abstract_only"
    assert response.items[0].coverage_reason == "pre_resolution_best_guess"
    assert response.items[0].notes


@pytest.mark.asyncio
async def test_preflight_uses_resolved_pmcid_before_calling_coverage_unknown():
    async def id_converter(pmids):
        return {"33454820": "PMC7811395"}

    async def pmc_bioc_available(pmcid):
        assert pmcid == "PMC7811395"
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pmc_bioc_available=pmc_bioc_available,
    )

    response = await service.preflight_pmids(["33454820"])

    assert response.items[0].pmcid == "PMC7811395"
    assert response.items[0].expected_coverage == "full_text"
    assert response.items[0].coverage_reason == "pmc_oa_bioc"
```

- [ ] Run the failing tests.

```bash
uv run pytest tests/unit/test_source_preflight.py -q
```

Expected output:

```text
AssertionError
```

- [ ] Add the enum literal in `review_rerag.py`.

```python
CoverageReason = Literal[
    "pmc_oa_bioc",
    "pubtator_abstract",
    "pubmed_metadata",
    "no_pmcid",
    "pre_resolution_best_guess",
    "fetch_failed",
    "not_found",
]
```

- [ ] Update `SourcePreflightService._preflight_one_pmid`.

Implementation rule:

- Track `id_resolution_attempted: bool`.
- Track `id_resolution_failed: bool`.
- If ID conversion failed and no PMCID was found, emit `coverage_reason="pre_resolution_best_guess"` instead of `no_pmcid`.
- Include a note string: `"PMCID conversion failed before coverage resolution; coverage is a pre-resolution best guess."`

- [ ] Wire the dependency in `api/routes/dependencies.py`.

```python
async def _ncbi_pmid_to_pmcid(pmids: list[str]) -> dict[str, str | None]:
    discovery = get_discovery_service()
    converted = await discovery.convert_article_ids(pmids, source="auto")
    return {record.pmid: record.pmcid for record in converted.records if record.pmid is not None}
```

Pass `id_converter=_ncbi_pmid_to_pmcid` into `SourcePreflightService`.

- [ ] Run source preflight tests.

```bash
uv run pytest tests/unit/test_source_preflight.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 6.

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/api/routes/dependencies.py pubtator_link/services/source_preflight.py tests/unit/test_source_preflight.py
git commit -m "fix: label unresolved preflight coverage honestly"
```

## Task 7: Centralize Review State Hints And Add Index Snapshot Dates

**Purpose:** Stop returning stale fixed polling delays and stamp review-index responses with provenance dates.

**Files:**

- Add `pubtator_link/services/review_state.py`
- Update `pubtator_link/services/provenance.py`
- Update `pubtator_link/models/review_rerag.py`
- Update `pubtator_link/services/review_context_service.py`
- Update `pubtator_link/mcp/service_adapters.py`
- Update `pubtator_link/api/routes/reviews.py`
- Update `tests/unit/test_review_state.py`
- Update `tests/unit/test_review_context_service.py`
- Update `tests/unit/mcp/test_mcp_service_adapters.py`
- Update `tests/test_routes/test_reviews.py`

**Contract:**

- `retry_after_ms` is `None` when no items are queued or running.
- `retry_after_ms` is state aware:
  - queued plus running equals 0: `None`
  - 1 to 3 active jobs: 3000
  - 4 to 10 active jobs: 5000
  - more than 10 active jobs: 10000
- `index_snapshot_date` appears on:
  - `IndexReviewEvidenceResponse`
  - `InspectReviewIndexResponse`
  - `RetrieveReviewContextResponse`
  - `RetrieveReviewContextBatchResponse`
  - `ReviewAuditBundle`

**TDD Steps:**

- [ ] Add helper tests first.

```python
# tests/unit/test_review_state.py
from pubtator_link.models.review_rerag import ReviewPreparationStatus
from pubtator_link.services.review_state import index_snapshot_date, retry_after_ms_for_status


def test_retry_after_ms_is_none_for_terminal_status() -> None:
    status = ReviewPreparationStatus(total=2, completed=2, failed=0, queued=0, running=0)

    assert retry_after_ms_for_status(status) is None


def test_retry_after_ms_is_short_for_small_active_sets() -> None:
    status = ReviewPreparationStatus(total=3, completed=1, failed=0, queued=1, running=1)

    assert retry_after_ms_for_status(status) == 3000


def test_retry_after_ms_is_medium_for_moderate_active_sets() -> None:
    status = ReviewPreparationStatus(total=8, completed=0, failed=0, queued=6, running=2)

    assert retry_after_ms_for_status(status) == 5000


def test_retry_after_ms_scales_large_active_sets() -> None:
    status = ReviewPreparationStatus(total=30, completed=0, failed=0, queued=29, running=1)

    assert retry_after_ms_for_status(status) == 10000


def test_index_snapshot_date_is_iso_date() -> None:
    value = index_snapshot_date()

    assert len(value) == 10
    assert value.count("-") == 2
```

- [ ] Run the failing helper tests.

```bash
uv run pytest tests/unit/test_review_state.py -q
```

Expected output:

```text
ModuleNotFoundError
```

- [ ] Add `pubtator_link/services/review_state.py`.

```python
from datetime import UTC, datetime

from pubtator_link.models.review_rerag import ReviewPreparationStatus


def retry_after_ms_for_status(status: ReviewPreparationStatus) -> int | None:
    """Return an honest polling hint for non-terminal review preparation."""

    active = status.queued + status.running
    if active == 0:
        return None
    if active <= 3:
        return 3000
    if active <= 10:
        return 5000
    if active > 10:
        return 10000
    return None


def index_snapshot_date() -> str:
    """Return the date used to label review-index preparation provenance."""

    return datetime.now(UTC).date().isoformat()
```

- [ ] Add `index_snapshot_date: str | None = None` to the response models listed in the contract.

- [ ] Update `ReviewContextService.inspect_review_index`, `retrieve_context`, `retrieve_context_batch`, and `build_audit_bundle` to set `index_snapshot_date=index_snapshot_date()`.

- [ ] Update `index_review_evidence_impl` in `mcp/service_adapters.py`.

```python
retry_after_ms = retry_after_ms_for_status(status)
return {
    "success": True,
    "review_id": review_id,
    "accepted_pmids": accepted_pmids,
    "failed_pmids": failed_pmids,
    "status": status.model_dump(),
    "retry_after_ms": retry_after_ms,
    "index_snapshot_date": index_snapshot_date(),
    "_meta": meta,
}
```

- [ ] Update route-level index responses in `api/routes/reviews.py` if they construct `IndexReviewEvidenceResponse` directly.

- [ ] Update existing tests that expect `retry_after_ms == 5000` for terminal states to expect `None`.

- [ ] Add tests asserting snapshot fields are present on inspect and retrieve batch responses.

- [ ] Run focused review tests.

```bash
uv run pytest tests/unit/test_review_state.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 7.

```bash
git add pubtator_link/services/review_state.py pubtator_link/services/provenance.py pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/mcp/service_adapters.py pubtator_link/api/routes/reviews.py tests/unit/test_review_state.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py
git commit -m "fix: centralize review polling and snapshot state"
```

## Task 8: Improve Inspect Review Sample Passages

**Purpose:** Make `inspect_review_index` samples useful for LLM and human QA by avoiding section headings and stub text.

**Files:**

- Update `pubtator_link/models/review_rerag.py`
- Update `pubtator_link/repositories/review_rerag.py`
- Update `pubtator_link/services/review_context_service.py`
- Update `pubtator_link/mcp/service_adapters.py`
- Update `pubtator_link/mcp/tools/reviews.py`
- Update `tests/unit/test_review_rerag_repository.py`
- Update `tests/unit/test_review_context_service.py`
- Update `tests/unit/mcp/test_mcp_service_adapters.py`

**Contract:**

- `InspectReviewIndexRequest` adds:
  - `min_sample_chars: int = 80`
  - `sample_section_policy: Literal["evidence_first", "original_order"] = "evidence_first"`
- `ReviewSourceSummary` adds:
  - `sample_warning: str | None = None`
- Default sampling excludes passages shorter than `min_sample_chars` when longer passages exist for the same PMID.
- Informative sections are preferred before administrative sections.
- If no passage meets `min_sample_chars`, return the best available sample and set `sample_warning`.

**TDD Steps:**

- [ ] Add repository test first.

```python
async def test_list_review_sources_prefers_informative_non_stub_samples(repository):
    await repository.upsert_review("review-samples")
    await repository.insert_passages(
        review_id="review-samples",
        passages=[
            {
                "pmid": "33454820",
                "source_id": "PMID:33454820",
                "section": "Background",
                "passage_id": "PMID:33454820:background:0",
                "text": "Background",
                "embedding": [0.1, 0.2, 0.3],
            },
            {
                "pmid": "33454820",
                "source_id": "PMID:33454820",
                "section": "abstract",
                "passage_id": "PMID:33454820:abstract:0",
                "text": "Familial Mediterranean fever is a clinically diagnosed autoinflammatory disease with MEFV-associated genetic findings.",
                "embedding": [0.1, 0.2, 0.3],
            },
        ],
    )

    sources = await repository.list_review_sources(
        "review-samples",
        include_passage_samples=True,
        sample_per_pmid=1,
        min_sample_chars=80,
        sample_section_policy="evidence_first",
    )

    assert sources[0].sample_passages[0].passage_id == "PMID:33454820:abstract:0"
    assert sources[0].sample_warning is None
```

- [ ] Add fallback warning test.

```python
async def test_list_review_sources_warns_when_only_stub_samples_exist(repository):
    await repository.upsert_review("review-stub-samples")
    await repository.insert_passages(
        review_id="review-stub-samples",
        passages=[
            {
                "pmid": "33454820",
                "source_id": "PMID:33454820",
                "section": "Background",
                "passage_id": "PMID:33454820:background:0",
                "text": "Background",
                "embedding": [0.1, 0.2, 0.3],
            }
        ],
    )

    sources = await repository.list_review_sources(
        "review-stub-samples",
        include_passage_samples=True,
        sample_per_pmid=1,
        min_sample_chars=80,
        sample_section_policy="evidence_first",
    )

    assert sources[0].sample_passages[0].text == "Background"
    assert sources[0].sample_warning == "Only short sample passages were available for this PMID."
```

- [ ] Run the failing repository tests.

```bash
uv run pytest tests/unit/test_review_rerag_repository.py -q
```

Expected output:

```text
TypeError
```

- [ ] Update models:

```python
SampleSectionPolicy = Literal["evidence_first", "original_order"]


class InspectReviewIndexRequest(BaseModel):
    review_id: str
    pmids: list[str] | None = None
    include_passage_samples: bool = True
    sample_per_pmid: int = Field(default=2, ge=0, le=10)
    min_sample_chars: int = Field(default=80, ge=0, le=1000)
    sample_section_policy: SampleSectionPolicy = "evidence_first"
```

Add `sample_warning` to `ReviewSourceSummary`.

- [ ] Update repository SQL ranking.

Ranking rule:

```sql
case
  when char_length(text) >= $min_sample_chars then 0
  else 1
end,
case
  when lower(section) in ('abstract', 'results', 'discussion', 'methods', 'introduction') then 0
  when lower(section) in ('background', 'conclusion') then 1
  else 2
end,
section,
passage_id
```

When `sample_section_policy == "original_order"`, preserve existing section and passage order.

- [ ] Add `sample_warning` in repository aggregation when all selected samples are shorter than `min_sample_chars`.

- [ ] Pass new request fields through service, route, MCP tool, and adapter.

- [ ] Run focused tests.

```bash
uv run pytest tests/unit/test_review_rerag_repository.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 8.

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories/review_rerag.py pubtator_link/services/review_context_service.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/reviews.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "fix: prefer useful review index samples"
```

## Task 9: Add Workflow Help Models And MCP Tool

**Purpose:** Give fresh-context LLMs a one-call canonical workflow without relying only on server instructions.

**Files:**

- Add `pubtator_link/models/workflow_help.py`
- Add `pubtator_link/services/workflow_help.py`
- Update `pubtator_link/mcp/metadata.py`
- Update `pubtator_link/mcp/resources.py`
- Update `tests/unit/test_workflow_help.py`
- Update `tests/unit/mcp/test_mcp_facade.py`

**Contract:**

- Tool name: `pubtator.workflow_help`
- Args:
  - `task: Literal["clinical_genetics_review", "literature_review", "citation_audit", "entity_discovery"] = "clinical_genetics_review"`
- Response:
  - `task`
  - `steps`
  - `fallbacks`
  - `tool_sequence`
  - `_meta.next_commands`

**TDD Steps:**

- [ ] Add service tests first.

```python
# tests/unit/test_workflow_help.py
from pubtator_link.services.workflow_help import WorkflowHelpService


def test_workflow_help_includes_metadata_and_review_index_steps() -> None:
    service = WorkflowHelpService()

    response = service.get_help("clinical_genetics_review")

    names = [step.tool_name for step in response.steps]
    assert "pubtator.search_biomedical_entities" in names
    assert "pubtator.search_literature" in names
    assert "pubtator.get_publication_metadata" in names
    assert "pubtator.index_review_evidence" in names
    assert "pubtator.retrieve_review_context_batch" in names
    assert response.meta["next_commands"]
```

- [ ] Run the failing test.

```bash
uv run pytest tests/unit/test_workflow_help.py -q
```

Expected output:

```text
ModuleNotFoundError
```

- [ ] Add `models/workflow_help.py`.

```python
from typing import Any, Literal

from pydantic import BaseModel, Field


WorkflowTask = Literal["clinical_genetics_review", "literature_review", "citation_audit", "entity_discovery"]


class WorkflowStep(BaseModel):
    order: int
    tool_name: str
    purpose: str
    required: bool = True
    key_args: dict[str, Any] = Field(default_factory=dict)


class WorkflowFallback(BaseModel):
    condition: str
    tool_name: str
    action: str


class WorkflowHelpResponse(BaseModel):
    task: WorkflowTask
    steps: list[WorkflowStep]
    fallbacks: list[WorkflowFallback]
    tool_sequence: list[str]
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
```

- [ ] Add `services/workflow_help.py` returning fixed typed responses.

```python
from pubtator_link.models.workflow_help import WorkflowFallback, WorkflowHelpResponse, WorkflowStep, WorkflowTask


class WorkflowHelpService:
    """Return compact in-band workflow guidance for LLM consumers."""

    def get_help(self, task: WorkflowTask) -> WorkflowHelpResponse:
        if task == "entity_discovery":
            return self._entity_discovery()
        if task == "citation_audit":
            return self._citation_audit()
        return self._clinical_or_literature_review(task)

    def _clinical_or_literature_review(self, task: WorkflowTask) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(order=1, tool_name="pubtator.search_biomedical_entities", purpose="Resolve canonical entity IDs for genes, diseases, chemicals, and variants."),
            WorkflowStep(order=2, tool_name="pubtator.search_literature", purpose="Find candidate PMIDs with compact results and optional metadata."),
            WorkflowStep(order=3, tool_name="pubtator.get_publication_metadata", purpose="Fetch citation-grade author and journal metadata for selected PMIDs."),
            WorkflowStep(order=4, tool_name="pubtator.index_review_evidence", purpose="Prepare the selected corpus for review-scoped retrieval."),
            WorkflowStep(order=5, tool_name="pubtator.inspect_review_index", purpose="Verify indexed coverage, source status, and sample passages."),
            WorkflowStep(order=6, tool_name="pubtator.retrieve_review_context_batch", purpose="Retrieve citable passages for final claims."),
        ]
        fallbacks = [
            WorkflowFallback(condition="review indexing is unavailable", tool_name="pubtator.get_publication_passages", action="Fetch direct passages for the same selected PMIDs."),
            WorkflowFallback(condition="search results lack authors", tool_name="pubtator.get_publication_metadata", action="Fetch citation metadata before drafting references."),
        ]
        return WorkflowHelpResponse(
            task=task,
            steps=steps,
            fallbacks=fallbacks,
            tool_sequence=[step.tool_name for step in steps],
            _meta={"next_commands": [step.tool_name for step in steps[:3]]},
        )
```

- [ ] Register `pubtator.workflow_help` in `mcp/metadata.py`.

```python
@mcp.tool(
    name="pubtator.workflow_help",
    description=(
        "Return the canonical PubTator-Link workflow for common LLM research tasks. "
        "Use this when a fresh context needs the recommended tool sequence. Research use only; "
        "not for diagnosis, treatment, triage, patient management, or clinical decision support."
    ),
)
def workflow_help(
    task: WorkflowTask = "clinical_genetics_review",
) -> dict[str, Any]:
    return WorkflowHelpService().get_help(task).model_dump(by_alias=True)
```

- [ ] Add `get_workflow_help_resource()` in `resources.py` with the same six-step clinical review workflow and include it in the existing capabilities resource payload under `workflow_help`.

- [ ] Add `pubtator.workflow_help` to `EXPECTED_PUBLIC_TOOL_NAMES`.

- [ ] Run focused tests.

```bash
uv run pytest tests/unit/test_workflow_help.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 9.

```bash
git add pubtator_link/models/workflow_help.py pubtator_link/services/workflow_help.py pubtator_link/mcp/metadata.py pubtator_link/mcp/resources.py tests/unit/test_workflow_help.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add workflow help tool"
```

## Task 10: Add Corpus Suggestion Models, Service, And REST Route

**Purpose:** Compress repeated multi-search LLM discovery into a deterministic candidate corpus suggestion service.

**Files:**

- Add `pubtator_link/models/corpus_suggestion.py`
- Add `pubtator_link/services/corpus_suggestion.py`
- Update `pubtator_link/api/routes/dependencies.py`
- Update `pubtator_link/api/routes/discovery.py`
- Add `tests/unit/test_corpus_suggestion_service.py`
- Update `tests/test_routes/test_discovery.py`

**Contract:**

- REST route: `POST /api/discovery/suggest-corpus`
- Input:
  - `question: str`
  - `max_pmids: int = 8`
  - `entity_ids: list[str] = []`
  - `must_include_pmids: list[str] = []`
  - `prefer_guidelines: bool = True`
  - `include_metadata: bool = True`
- Output:
  - `candidate_pmids`
  - `candidates` with role, score, metadata, coverage hint, rationale
  - `searches`
  - `_meta.next_commands` for metadata, index, inspect, and retrieve

**TDD Steps:**

- [ ] Add model tests inside `tests/unit/test_corpus_suggestion_service.py`.

```python
from pubtator_link.models.corpus_suggestion import CorpusSuggestionRequest


def test_corpus_suggestion_request_clamps_max_pmids() -> None:
    request = CorpusSuggestionRequest(question="FMF MEFV VUS colchicine", max_pmids=50)

    assert request.max_pmids == 20
```

- [ ] Add service test with fake dependencies.

```python
@pytest.mark.asyncio
async def test_corpus_suggestion_service_deduplicates_and_assigns_roles():
    class FakeSearch:
        async def search(self, query, *, limit, sort):
            return {
                "results": [
                    {"pmid": "26802180", "title": "EULAR recommendations for FMF", "score": 50.0},
                    {"pmid": "33726481", "title": "VUS cohort", "score": 40.0},
                ]
            }

    class FakeMetadata:
        async def get_metadata(self, request):
            from pubtator_link.models.publication_metadata import PublicationMetadata, PublicationMetadataResponse

            return PublicationMetadataResponse(
                success=True,
                metadata=[
                    PublicationMetadata(
                        pmid="26802180",
                        title="EULAR recommendations for FMF",
                        publication_types=["Practice Guideline"],
                    ),
                    PublicationMetadata(
                        pmid="33726481",
                        title="VUS cohort",
                        publication_types=["Journal Article"],
                    ),
                ],
                failed_pmids={},
                _meta={"next_commands": []},
            )

    class FakePreflight:
        async def preflight_pmids(self, pmids):
            from pubtator_link.models.review_rerag import SourcePreflightItem, SourcePreflightResponse

            return SourcePreflightResponse(
                items=[
                    SourcePreflightItem(pmid=pmid, expected_coverage="abstract_only", coverage_reason="pubtator_abstract")
                    for pmid in pmids
                ]
            )

    service = CorpusSuggestionService(
        search_client=FakeSearch(),
        metadata_service=FakeMetadata(),
        source_preflight_service=FakePreflight(),
    )

    response = await service.suggest(CorpusSuggestionRequest(question="FMF MEFV VUS colchicine", max_pmids=2))

    assert response.candidate_pmids == ["26802180", "33726481"]
    assert response.candidates[0].role == "guideline"
    assert response.candidates[1].role == "cohort"
    assert "pubtator.index_review_evidence" in response.meta["next_commands"][0]
```

- [ ] Run failing tests.

```bash
uv run pytest tests/unit/test_corpus_suggestion_service.py -q
```

Expected output:

```text
ModuleNotFoundError
```

- [ ] Add `models/corpus_suggestion.py`.

```python
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from pubtator_link.models.publication_metadata import PublicationMetadata
from pubtator_link.models.review_rerag import SourcePreflightItem


CorpusCandidateRole = Literal["guideline", "systematic_review", "cohort", "mechanism", "treatment", "background", "other"]


class CorpusSuggestionRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    max_pmids: int = Field(default=8, ge=1, le=20)
    entity_ids: list[str] = Field(default_factory=list)
    must_include_pmids: list[str] = Field(default_factory=list)
    prefer_guidelines: bool = True
    include_metadata: bool = True

    @field_validator("max_pmids", mode="before")
    @classmethod
    def clamp_max_pmids(cls, value: int) -> int:
        return min(int(value), 20)


class CorpusSearchTrace(BaseModel):
    query: str
    result_pmids: list[str]


class CorpusCandidate(BaseModel):
    pmid: str
    role: CorpusCandidateRole
    title: str | None = None
    score: float = 0.0
    rationale: str
    metadata: PublicationMetadata | None = None
    coverage_hint: SourcePreflightItem | None = None


class CorpusSuggestionResponse(BaseModel):
    success: bool = True
    candidate_pmids: list[str]
    candidates: list[CorpusCandidate]
    searches: list[CorpusSearchTrace]
    meta: dict[str, Any] = Field(default_factory=dict, alias="_meta")
```

- [ ] Add `services/corpus_suggestion.py`.

```python
from pubtator_link.models.corpus_suggestion import (
    CorpusCandidate,
    CorpusSearchTrace,
    CorpusSuggestionRequest,
    CorpusSuggestionResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest


class CorpusSuggestionService:
    """Suggest a compact, review-feeding PMID corpus for an LLM research question."""

    def __init__(self, *, search_client, metadata_service, source_preflight_service) -> None:
        self._search_client = search_client
        self._metadata_service = metadata_service
        self._source_preflight_service = source_preflight_service

    async def suggest(self, request: CorpusSuggestionRequest) -> CorpusSuggestionResponse:
        searches = await self._run_searches(request)
        candidate_pmids = self._select_pmids(request, searches)
        metadata_response = await self._metadata_service.get_metadata(
            PublicationMetadataRequest(
                pmids=candidate_pmids,
                include_mesh=True,
                include_publication_types=True,
                include_citations="none",
                include_coverage=False,
            )
        )
        preflight_response = await self._source_preflight_service.preflight_pmids(candidate_pmids)
        metadata_by_pmid = {item.pmid: item for item in metadata_response.metadata}
        coverage_by_pmid = {item.pmid: item for item in preflight_response.items}

        candidates = [
            CorpusCandidate(
                pmid=pmid,
                role=self._role_for(metadata_by_pmid.get(pmid)),
                title=metadata_by_pmid.get(pmid).title if metadata_by_pmid.get(pmid) else None,
                score=self._score_for(pmid, searches),
                rationale=self._rationale_for(metadata_by_pmid.get(pmid)),
                metadata=metadata_by_pmid.get(pmid) if request.include_metadata else None,
                coverage_hint=coverage_by_pmid.get(pmid),
            )
            for pmid in candidate_pmids
        ]
        return CorpusSuggestionResponse(
            candidate_pmids=candidate_pmids,
            candidates=candidates,
            searches=searches,
            _meta={
                "next_commands": [
                    f"pubtator.get_publication_metadata(pmids={candidate_pmids!r})",
                    f"pubtator.index_review_evidence(pmids={candidate_pmids!r})",
                    "pubtator.inspect_review_index(review_id='fmf_mefv_vus_colchicine')",
                    "pubtator.retrieve_review_context_batch(review_id='fmf_mefv_vus_colchicine', queries=['MEFV VUS phenotype colchicine'])",
                ]
            },
        )
```

Service behavior:

- Build two to four queries from the question:
  - raw question
  - question plus `guideline consensus recommendation` when `prefer_guidelines=True`
  - question plus `cohort variant outcome`
  - question plus `colchicine treatment response` when the question mentions colchicine
- Execute searches sequentially through the existing literature search client interface used by the API layer.
- Deduplicate PMIDs while preserving first-seen order.
- Force `must_include_pmids` to the front.
- Fetch metadata and preflight for selected PMIDs.
- Assign roles:
  - publication type includes `Practice Guideline`, `Guideline`, `Consensus Development Conference`, or title contains `recommendation`: `guideline`
  - publication type includes `Systematic Review` or title contains `systematic review`: `systematic_review`
  - title contains `cohort`, `registry`, `series`, or metadata publication type includes `Observational Study`: `cohort`
  - title contains `colchicine`, `treatment`, or `therapy`: `treatment`
  - title contains `variant`, `mutation`, `mechanism`, or gene-like entity text: `mechanism`
  - default: `other`

- [ ] Add route in `discovery.py`.

```python
@router.post("/suggest-corpus", response_model=CorpusSuggestionResponse)
async def suggest_corpus(
    request: CorpusSuggestionRequest,
    service: CorpusSuggestionService = Depends(dependencies.get_corpus_suggestion_service),
) -> CorpusSuggestionResponse:
    return await service.suggest(request)
```

- [ ] Add dependency in `dependencies.py`.

```python
_corpus_suggestion_service: CorpusSuggestionService | None = None


def get_corpus_suggestion_service() -> CorpusSuggestionService:
    global _corpus_suggestion_service
    if _corpus_suggestion_service is None:
        _corpus_suggestion_service = CorpusSuggestionService(
            search_client=get_pubtator_client(),
            metadata_service=get_publication_metadata_service(),
            source_preflight_service=get_source_preflight_service(),
        )
    return _corpus_suggestion_service
```

- [ ] Add a route test using `app.dependency_overrides[get_corpus_suggestion_service] = lambda: fake_service`. POST `{"question": "FMF MEFV VUS colchicine", "max_pmids": 2}` to `/api/discovery/suggest-corpus` and assert `candidate_pmids == ["26802180", "33726481"]`.

- [ ] Run focused tests.

```bash
uv run pytest tests/unit/test_corpus_suggestion_service.py tests/test_routes/test_discovery.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 10.

```bash
git add pubtator_link/models/corpus_suggestion.py pubtator_link/services/corpus_suggestion.py pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/discovery.py tests/unit/test_corpus_suggestion_service.py tests/test_routes/test_discovery.py
git commit -m "feat: add corpus suggestion service"
```

## Task 11: Add MCP Corpus Suggestion Tool

**Purpose:** Expose corpus suggestion to LLM consumers with typed schemas and handoff metadata.

**Files:**

- Update `pubtator_link/mcp/tools/discovery.py`
- Update `pubtator_link/mcp/service_adapters.py`
- Update `tests/unit/mcp/test_mcp_facade.py`
- Update `tests/unit/mcp/test_mcp_service_adapters.py`

**TDD Steps:**

- [ ] Add `pubtator.suggest_corpus` to `EXPECTED_PUBLIC_TOOL_NAMES`.

- [ ] Add an adapter test.

```python
async def test_suggest_corpus_impl_returns_candidate_pmids():
    from pubtator_link.models.corpus_suggestion import CorpusSuggestionResponse

    class FakeService:
        async def suggest(self, request):
            assert request.question == "FMF MEFV VUS colchicine"
            return CorpusSuggestionResponse(
                candidate_pmids=["26802180"],
                candidates=[],
                searches=[],
                _meta={"next_commands": ["pubtator.index_review_evidence"]},
            )

    result = await service_adapters.suggest_corpus_impl(
        service=FakeService(),
        question="FMF MEFV VUS colchicine",
        max_pmids=8,
        entity_ids=[],
        must_include_pmids=[],
        prefer_guidelines=True,
        include_metadata=True,
    )

    assert result["candidate_pmids"] == ["26802180"]
    assert result["_meta"]["next_commands"] == ["pubtator.index_review_evidence"]
```

- [ ] Run failing MCP tests.

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
AssertionError
```

- [ ] Add `suggest_corpus_impl` to `service_adapters.py`.

```python
async def suggest_corpus_impl(
    *,
    service: CorpusSuggestionService,
    question: str,
    max_pmids: int = 8,
    entity_ids: list[str] | None = None,
    must_include_pmids: list[str] | None = None,
    prefer_guidelines: bool = True,
    include_metadata: bool = True,
) -> dict[str, Any]:
    request = CorpusSuggestionRequest(
        question=question,
        max_pmids=max_pmids,
        entity_ids=entity_ids or [],
        must_include_pmids=must_include_pmids or [],
        prefer_guidelines=prefer_guidelines,
        include_metadata=include_metadata,
    )
    response = await service.suggest(request)
    return response.model_dump(by_alias=True)
```

- [ ] Register the MCP tool in `mcp/tools/discovery.py`.

```python
@mcp.tool(
    name="pubtator.suggest_corpus",
    description=(
        "Suggest a compact, review-feeding PMID corpus for a research question. Returns candidate_pmids, "
        "roles, coverage hints, citation metadata, and _meta.next_commands for review indexing and retrieval. "
        "Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."
    ),
)
async def suggest_corpus(
    question: Annotated[str, Field(min_length=3, max_length=1000)],
    max_pmids: Annotated[int, Field(ge=1, le=20)] = 8,
    entity_ids: list[str] | None = None,
    must_include_pmids: list[str] | None = None,
    prefer_guidelines: bool = True,
    include_metadata: bool = True,
) -> dict[str, Any]:
    return await service_adapters.suggest_corpus_impl(
        service=dependencies.get_corpus_suggestion_service(),
        question=question,
        max_pmids=max_pmids,
        entity_ids=entity_ids,
        must_include_pmids=must_include_pmids,
        prefer_guidelines=prefer_guidelines,
        include_metadata=include_metadata,
    )
```

- [ ] Run MCP tests.

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected output:

```text
passed
```

- [ ] Commit Task 11.

```bash
git add pubtator_link/mcp/tools/discovery.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: expose corpus suggestion MCP tool"
```

## Task 12: Update Docs, Capability Resources, And Final Verification

**Purpose:** Make the new surface discoverable and prove the whole repo is healthy.

**Files:**

- Update `README.md`
- Update `docs/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md`
- Update `pubtator_link/mcp/resources.py`
- Update `tests/unit/mcp/test_mcp_facade.py`

**Steps:**

- [ ] Update README MCP tool list and workflow examples:
  - `pubtator.get_publication_metadata`
  - `pubtator.workflow_help`
  - `pubtator.suggest_corpus`
  - `search_literature(metadata="basic")`
  - `inspect_review_index(min_sample_chars=80)`

- [ ] Update the consumer evaluation doc with an implementation status section.

Use this exact status wording:

```markdown
## Implementation Status

The LLM citation and state surface stabilization work adds:

- `pubtator.get_publication_metadata` for citation-grade PMID metadata.
- Optional `search_literature(metadata="basic" | "full")` enrichment.
- Honest pre-resolution coverage labeling when PMCID conversion is unavailable.
- State-aware `retry_after_ms` values that are omitted for terminal review preparation.
- `index_snapshot_date` alongside `corpus_snapshot_date` on review-index responses.
- Sample passage filtering for `inspect_review_index`.
- `pubtator.workflow_help` for canonical workflow guidance.
- `pubtator.suggest_corpus` for compact review-feeding PMID selection.

Remaining out of scope for this change:

- Public tool renaming or shortened aliases.
- Full-text coverage expansion beyond available PubTator and PMC OA sources.
- Breaking consolidation of existing discovery verbs.
```

- [ ] Update `mcp/resources.py` capabilities to mention:
  - metadata tool
  - corpus suggestion tool
  - workflow help tool
  - search metadata mode
  - index snapshot dates

- [ ] Run focused tests for all touched domains.

```bash
uv run pytest \
  tests/unit/test_publication_metadata_models.py \
  tests/unit/test_publication_metadata_service.py \
  tests/unit/test_search_shaping.py \
  tests/unit/test_source_preflight.py \
  tests/unit/test_review_state.py \
  tests/unit/test_review_context_service.py \
  tests/unit/test_review_rerag_repository.py \
  tests/unit/test_workflow_help.py \
  tests/unit/test_corpus_suggestion_service.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/test_routes/test_publications.py \
  tests/test_routes/test_search.py \
  tests/test_routes/test_discovery.py \
  tests/test_routes/test_reviews.py \
  -q
```

Expected output:

```text
passed
```

- [ ] Run formatting, linting, type checking, and tests.

```bash
make format
make lint
make typecheck
make test
```

Expected output:

```text
passed
```

- [ ] Run the required final verification.

```bash
make ci-local
```

Expected output:

```text
passed
```

- [ ] Commit Task 12.

```bash
git add README.md docs/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md pubtator_link/mcp/resources.py tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: document LLM metadata and corpus workflows"
```

## Execution Notes

- Use `superpowers:subagent-driven-development` for implementation. Split tasks by disjoint write sets:
  - Metadata service and routes: Tasks 1-4
  - Search and source preflight: Tasks 5-6
  - Review state and samples: Tasks 7-8
  - Workflow and corpus suggestion: Tasks 9-11
  - Docs and final verification: Task 12
- Keep commits task-sized. Do not combine tasks unless a test failure proves they are inseparable.
- Run focused tests before each commit.
- Run `make ci-local` before claiming implementation completion.
- Do not change tool names or remove existing tools in this plan.
- Do not expose destructive cache or admin operations through MCP.
- Do not install dependencies with direct `pip`; use `uv` and Makefile targets.

## Verification Checklist

- [ ] Metadata models serialize authors, citations, publication types, MeSH, and coverage.
- [ ] NCBI metadata service returns ordered partial-success responses.
- [ ] REST metadata route works through dependency injection.
- [ ] MCP metadata tool appears in the public tool catalog.
- [ ] `search_literature(metadata="basic")` returns populated authors when metadata exists.
- [ ] Preflight distinguishes resolved `no_pmcid` from `pre_resolution_best_guess`.
- [ ] Terminal review preparation responses omit `retry_after_ms`.
- [ ] Review index, inspect, retrieve, and audit responses include `index_snapshot_date`.
- [ ] Inspect samples prefer useful passages and warn on stub-only samples.
- [ ] `pubtator.workflow_help` returns canonical workflow steps and fallbacks.
- [ ] `pubtator.suggest_corpus` returns `candidate_pmids` and `_meta.next_commands`.
- [ ] Docs describe the new LLM-facing workflow.
- [ ] `make ci-local` passes.
