# Literature Map Epic Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build article citation graphs, ELink-backed related evidence candidates, and bounded topic literature maps for PubTator-Link REST and MCP users.

**Architecture:** Add graph-specific Pydantic models, small provider clients, and three service layers: `CitationGraphService`, `RelatedEvidenceService`, and `TopicLiteratureMapService`. Wire the services through existing FastAPI dependency injection and flat MCP publication tools, then regenerate the runtime MCP catalog.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, httpx, FastMCP, Ruff, mypy, pytest, mocked provider fixtures only.

---

## Source Spec

- Design: `docs/superpowers/specs/2026-05-03-literature-map-epic-design.md`
- Related issues: #2 citation graph, #3 related evidence, #4 topic literature map

## File Structure

Create:

- `pubtator_link/models/literature_graph.py`
  - Request/response models and shared graph node, edge, paper, author, entity, availability, provenance, warning, and summary types.
- `pubtator_link/services/literature_providers.py`
  - Crossref, Europe PMC literature, OpenAlex, and Unpaywall HTTP clients plus parsing helpers.
- `pubtator_link/services/citation_graph.py`
  - Citation graph normalization and provider degradation.
- `pubtator_link/services/related_evidence.py`
  - ELink-centered candidate merging, filtering, and lexicographic ranking.
- `pubtator_link/services/topic_literature_map.py`
  - Seed collection, bounded graph construction, centrality ranking, summary, and retrieval hints.
- `tests/fixtures/literature_graph.py`
  - Mocked provider payloads for the specific acceptance criteria identifiers.
- `tests/unit/test_literature_graph_models.py`
- `tests/unit/test_literature_providers.py`
- `tests/unit/test_citation_graph_service.py`
- `tests/unit/test_related_evidence_service.py`
- `tests/unit/test_topic_literature_map_service.py`
- `tests/test_routes/test_publication_literature_graph.py`

Modify:

- `pubtator_link/config.py`
  - Add polite-pool and Unpaywall settings: `crossref_mailto`, `openalex_mailto`, `unpaywall_email`.
- `pubtator_link/services/ncbi_discovery.py`
  - Add ELink neighbor-score method and typed record without breaking existing `find_related_articles`.
- `pubtator_link/api/routes/dependencies.py`
  - Add lifecycle, dependency getters, and cleanup for literature graph services and provider clients. Keep the existing `EuropePmcClient` for review full-text fallback and add a separate `EuropePmcLiteratureClient` for citation/search metadata.
- `pubtator_link/api/routes/publications.py`
  - Add three POST endpoints.
- `pubtator_link/mcp/tools/publications.py`
  - Add three flat MCP tools.
- `pubtator_link/mcp/service_adapters.py`
  - Add adapter functions that construct request models and dump responses.
- `pubtator_link/mcp/profiles.py`
  - Add citation graph and related evidence to `LEAN_TOOLS`; topic map to `FULL_ONLY_TOOLS`; readonly profile includes the read-only tools automatically unless excluded.
- `pubtator_link/mcp/catalog.py`
  - Add catalog supplements for the three tools.
- `docs/mcp-tool-catalog.md`
  - Regenerate from runtime registration.
- `tests/unit/mcp/test_mcp_facade.py`
- `tests/unit/mcp/test_mcp_profiles.py`
- `tests/unit/mcp/test_mcp_tool_catalog.py`
- `README.md`
  - Add concise entries in the MCP tool table after catalog generation is passing.

## Shared Constants

Use these provider names consistently in models, services, and tests:

```python
CROSSREF_PROVIDER = "crossref"
EUROPE_PMC_PROVIDER = "europe_pmc"
OPENALEX_PROVIDER = "openalex"
UNPAYWALL_PROVIDER = "unpaywall"
NCBI_ELINK_PROVIDER = "ncbi_elink"
PUBTATOR_PROVIDER = "pubtator"
```

Use these warning codes consistently:

```python
PROVIDER_FAILED = "provider_failed"
PROVIDER_DISABLED = "provider_disabled"
PARTIAL_IDENTIFIER_RESOLUTION = "partial_identifier_resolution"
SOURCE_NOT_FOUND = "source_not_found"
```

---

### Task 1: Shared Literature Graph Models

**Files:**
- Create: `pubtator_link/models/literature_graph.py`
- Create: `tests/unit/test_literature_graph_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/unit/test_literature_graph_models.py`:

```python
from pydantic import ValidationError

from pubtator_link.models.literature_graph import (
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteraturePaper,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidatesRequest,
    TopicLiteratureMapRequest,
    dedupe_edges,
    dedupe_papers,
)


def test_citation_graph_request_requires_exactly_one_identifier() -> None:
    assert PublicationCitationGraphRequest(pmid="40562663").pmid == "40562663"
    assert PublicationCitationGraphRequest(doi="10.1016/j.ard.2025.05.020").doi == "10.1016/j.ard.2025.05.020"

    for payload in ({}, {"pmid": "40562663", "doi": "10.1016/j.ard.2025.05.020"}):
        try:
            PublicationCitationGraphRequest(**payload)
        except ValidationError as exc:
            assert "exactly one of pmid or doi is required" in str(exc)
        else:
            raise AssertionError("expected validation error")


def test_related_evidence_request_normalizes_numeric_pmid_string() -> None:
    request = RelatedEvidenceCandidatesRequest(pmid=" PMID:40562663 ", max_results=25)

    assert request.pmid == "40562663"


def test_topic_map_request_requires_query_or_pmids() -> None:
    assert TopicLiteratureMapRequest(query="familial mediterranean fever").query == "familial mediterranean fever"
    assert TopicLiteratureMapRequest(pmids=["40562663", "39596913"]).pmids == ["40562663", "39596913"]

    try:
        TopicLiteratureMapRequest()
    except ValidationError as exc:
        assert "at least one of query or pmids is required" in str(exc)
    else:
        raise AssertionError("expected validation error")


def test_dedupe_papers_prefers_pmid_then_doi_then_pmcid_then_openalex_id() -> None:
    papers = [
        LiteraturePaper(pmid="1", doi="10.1/ABC", title="PMID paper"),
        LiteraturePaper(pmid="1", doi="10.1/abc", title="Duplicate PMID paper"),
        LiteraturePaper(doi="10.2/XYZ", title="DOI paper"),
        LiteraturePaper(doi="10.2/xyz", title="Duplicate DOI paper"),
        LiteraturePaper(pmcid="PMC3", title="PMCID paper"),
        LiteraturePaper(openalex_id="https://openalex.org/W4", title="OpenAlex paper"),
    ]

    deduped = dedupe_papers(papers)

    assert [paper.title for paper in deduped] == [
        "PMID paper",
        "DOI paper",
        "PMCID paper",
        "OpenAlex paper",
    ]


def test_dedupe_edges_merges_provider_provenance_on_conceptual_edge() -> None:
    first = LiteratureGraphEdge(
        source="paper:1",
        target="paper:2",
        edge_type="cites",
        reasons=["crossref_reference"],
        provenance=[LiteratureGraphProvenance(provider="crossref", source_id="10.1/source")],
    )
    second = LiteratureGraphEdge(
        source="paper:1",
        target="paper:2",
        edge_type="cites",
        reasons=["openalex_referenced_work"],
        provenance=[LiteratureGraphProvenance(provider="openalex", source_id="W1")],
    )

    deduped = dedupe_edges([first, second])

    assert len(deduped) == 1
    assert deduped[0].reasons == ["crossref_reference", "openalex_referenced_work"]
    assert [item.provider for item in deduped[0].provenance] == ["crossref", "openalex"]


def test_graph_node_keys_are_stable() -> None:
    node = LiteratureGraphNode(node_type="paper", paper=LiteraturePaper(pmid="40562663"))

    assert node.key == "paper:pmid:40562663"
```

- [ ] **Step 2: Run model tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.models.literature_graph'`.

- [ ] **Step 3: Add model implementation**

Create `pubtator_link/models/literature_graph.py` with these public names and behavior:

```python
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

CitationGraphDirection = Literal["references", "cited_by", "both"]
LiteratureNodeType = Literal["paper", "author", "entity"]
LiteratureEdgeType = Literal[
    "cites",
    "cited_by",
    "authored_by",
    "mentions_entity",
    "related_by_elink",
    "related_by_pubtator_search",
]
LiteraturePaperStatus = Literal[
    "resolved_full_text_candidate",
    "resolved_metadata_only",
    "unresolved_reference",
    "publisher_entitlement_required",
]


def normalize_pmid(value: str) -> str:
    clean = value.strip()
    if clean.upper().startswith("PMID:"):
        clean = clean[5:].strip()
    if not clean or not clean.isdigit():
        raise ValueError("PMID must be numeric")
    return clean


def normalize_doi(value: str) -> str:
    clean = value.strip()
    if clean.lower().startswith("doi:"):
        clean = clean[4:].strip()
    if not clean:
        raise ValueError("DOI is required")
    return clean.lower()


class LiteratureGraphProvenance(BaseModel):
    provider: str
    source_id: str | None = None
    source_url: str | None = None
    raw_status: str | None = None


class LiteratureAvailability(BaseModel):
    has_pmc_full_text: bool = False
    is_open_access: bool = False
    has_pdf: bool = False
    full_text_url: str | None = None
    oa_status: str | None = None
    license_or_access_hint: str | None = None


class LiteratureAuthor(BaseModel):
    name: str
    orcid: str | None = None
    openalex_id: str | None = None
    affiliations: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        if self.openalex_id:
            return f"author:openalex:{self.openalex_id}"
        if self.orcid:
            return f"author:orcid:{self.orcid}"
        return f"author:name:{self.name.casefold()}"


class LiteratureEntity(BaseModel):
    entity_id: str
    entity_type: str
    name: str
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        return f"entity:{self.entity_id}"


class LiteraturePaper(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    authors: list[LiteratureAuthor] = Field(default_factory=list)
    availability: LiteratureAvailability = Field(default_factory=LiteratureAvailability)
    status: LiteraturePaperStatus = "resolved_metadata_only"
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)

    @field_validator("pmid")
    @classmethod
    def validate_pmid(cls, value: str | None) -> str | None:
        return normalize_pmid(value) if value is not None else None

    @field_validator("doi")
    @classmethod
    def validate_doi(cls, value: str | None) -> str | None:
        return normalize_doi(value) if value is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        if self.pmid:
            return f"paper:pmid:{self.pmid}"
        if self.doi:
            return f"paper:doi:{self.doi}"
        if self.pmcid:
            return f"paper:pmcid:{self.pmcid}"
        if self.openalex_id:
            return f"paper:openalex:{self.openalex_id}"
        title = self.title or "unresolved"
        return f"paper:title:{title.casefold()}"


class LiteratureGraphNode(BaseModel):
    node_type: LiteratureNodeType
    paper: LiteraturePaper | None = None
    author: LiteratureAuthor | None = None
    entity: LiteratureEntity | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        if self.node_type == "paper" and self.paper is not None:
            return self.paper.key
        if self.node_type == "author" and self.author is not None:
            return self.author.key
        if self.node_type == "entity" and self.entity is not None:
            return self.entity.key
        return f"{self.node_type}:missing"


class LiteratureGraphEdge(BaseModel):
    source: str
    target: str
    edge_type: LiteratureEdgeType
    weight: float = 1.0
    reasons: list[str] = Field(default_factory=list)
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)


class ProviderWarning(BaseModel):
    provider: str
    status: str
    retryable: bool = False
    message: str


class LiteratureResponseMeta(BaseModel):
    research_use_only: bool = True
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Graph relatedness is not evidence quality.",
            "Relatedness does not imply support for a biomedical claim.",
            "Passage-level review is required for claim grounding.",
        ]
    )
    warnings: list[ProviderWarning] = Field(default_factory=list)
    next_commands: list[dict[str, Any]] = Field(default_factory=list)


class PublicationCitationGraphRequest(BaseModel):
    pmid: str | None = None
    doi: str | None = None
    direction: CitationGraphDirection = "both"
    resolve_metadata: bool = True
    include_open_access_status: bool = True
    max_results: int = Field(default=50, ge=1, le=100)

    @field_validator("pmid")
    @classmethod
    def normalize_optional_pmid(cls, value: str | None) -> str | None:
        return normalize_pmid(value) if value is not None else None

    @field_validator("doi")
    @classmethod
    def normalize_optional_doi(cls, value: str | None) -> str | None:
        return normalize_doi(value) if value is not None else None

    @model_validator(mode="after")
    def require_exactly_one_identifier(self) -> "PublicationCitationGraphRequest":
        if (self.pmid is None) == (self.doi is None):
            raise ValueError("exactly one of pmid or doi is required")
        return self


class PublicationCitationGraphResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    source: LiteraturePaper
    references: list[LiteraturePaper] = Field(default_factory=list)
    cited_by: list[LiteraturePaper] = Field(default_factory=list)
    candidate_pmids: list[str] = Field(default_factory=list)
    metadata_only: list[LiteraturePaper] = Field(default_factory=list)
    meta: LiteratureResponseMeta = Field(default_factory=LiteratureResponseMeta, alias="_meta")


class RelatedEvidenceCandidatesRequest(BaseModel):
    pmid: str
    max_results: int = Field(default=25, ge=1, le=100)
    prefer_full_text: bool = True
    include_pubtator_search: bool = True
    include_citation_neighbors: bool = True
    publication_types: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None

    @field_validator("pmid")
    @classmethod
    def normalize_required_pmid(cls, value: str) -> str:
        return normalize_pmid(value)


class RelatedEvidenceCandidate(BaseModel):
    paper: LiteraturePaper
    score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    pubmed_neighbor_score: int | None = None


class RelatedEvidenceCandidatesResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    source: LiteraturePaper
    candidates: list[RelatedEvidenceCandidate] = Field(default_factory=list)
    candidate_pmids: list[str] = Field(default_factory=list)
    caution: str = "Related candidates are not substitutes and require passage-level review before use as evidence."
    meta: LiteratureResponseMeta = Field(default_factory=LiteratureResponseMeta, alias="_meta")


class TopicLiteratureMapRequest(BaseModel):
    query: str | None = Field(default=None, min_length=1, max_length=1000)
    pmids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    max_seed_papers: int = Field(default=25, ge=1, le=50)
    max_neighbors_per_paper: int = Field(default=10, ge=1, le=20)
    include_authors: bool = True
    include_citations: bool = True
    include_pubtator_entities: bool = True
    include_related_candidates: bool = True
    year_min: int | None = None
    year_max: int | None = None
    prefer_full_text: bool = True

    @field_validator("pmids")
    @classmethod
    def normalize_optional_pmids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for pmid in value:
            clean = normalize_pmid(pmid)
            if clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized

    @model_validator(mode="after")
    def require_query_or_pmids(self) -> "TopicLiteratureMapRequest":
        if not self.query and not self.pmids:
            raise ValueError("at least one of query or pmids is required")
        return self


class TopicLiteratureMapSummary(BaseModel):
    central_papers: list[LiteraturePaper] = Field(default_factory=list)
    recent_connected_papers: list[LiteraturePaper] = Field(default_factory=list)
    bridge_papers: list[LiteraturePaper] = Field(default_factory=list)
    dominant_author_groups: list[str] = Field(default_factory=list)
    accessible_full_text_candidates: list[LiteraturePaper] = Field(default_factory=list)
    closed_central_sources: list[LiteraturePaper] = Field(default_factory=list)
    recommended_next_pmids: list[str] = Field(default_factory=list)


class TopicLiteratureMapResponse(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    query: str | None = None
    seed_pmids: list[str] = Field(default_factory=list)
    summary: TopicLiteratureMapSummary = Field(default_factory=TopicLiteratureMapSummary)
    nodes: list[LiteratureGraphNode] = Field(default_factory=list)
    edges: list[LiteratureGraphEdge] = Field(default_factory=list)
    candidate_retrieval_hints: list[dict[str, Any]] = Field(default_factory=list)
    meta: LiteratureResponseMeta = Field(default_factory=LiteratureResponseMeta, alias="_meta")


def _paper_dedupe_key(paper: LiteraturePaper) -> str:
    if paper.pmid:
        return f"pmid:{paper.pmid}"
    if paper.doi:
        return f"doi:{paper.doi}"
    if paper.pmcid:
        return f"pmcid:{paper.pmcid}"
    if paper.openalex_id:
        return f"openalex:{paper.openalex_id}"
    return paper.key


def dedupe_papers(papers: list[LiteraturePaper]) -> list[LiteraturePaper]:
    seen: set[str] = set()
    deduped: list[LiteraturePaper] = []
    for paper in papers:
        key = _paper_dedupe_key(paper)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def dedupe_edges(edges: list[LiteratureGraphEdge]) -> list[LiteratureGraphEdge]:
    merged: dict[tuple[str, str, str], LiteratureGraphEdge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.edge_type)
        if key not in merged:
            merged[key] = edge.model_copy(deep=True)
            continue
        existing = merged[key]
        existing.reasons = list(dict.fromkeys([*existing.reasons, *edge.reasons]))
        existing.provenance = [*existing.provenance, *edge.provenance]
        existing.weight = max(existing.weight, edge.weight)
    return list(merged.values())
```

- [ ] **Step 4: Run model tests**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit models**

```bash
git add pubtator_link/models/literature_graph.py tests/unit/test_literature_graph_models.py
git commit -m "feat: add literature graph models"
```

---

### Task 2: Provider Clients And ELink Neighbor Scores

**Files:**
- Create: `pubtator_link/services/literature_providers.py`
- Create: `tests/fixtures/literature_graph.py`
- Create: `tests/unit/test_literature_providers.py`
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Add mocked provider fixtures**

Create `tests/fixtures/literature_graph.py`:

```python
CROSSREF_WORK_ARD_2025 = {
    "message": {
        "DOI": "10.1016/j.ard.2025.05.020",
        "title": ["A closed review article"],
        "container-title": ["Annals of the Rheumatic Diseases"],
        "published-print": {"date-parts": [[2025, 5]]},
        "reference": [
            {
                "DOI": "10.1000/primary-study",
                "article-title": "Primary trial of colchicine",
                "journal-title": "Example Journal",
                "year": "2021",
            },
            {
                "article-title": "Unresolved guideline reference",
                "journal-title": "Guideline Journal",
                "year": "2019",
            },
        ],
    }
}

EUROPE_PMC_CITATIONS_40562663 = {
    "resultList": {
        "result": [
            {
                "id": "40600001",
                "pmid": "40600001",
                "doi": "10.1000/citing-study",
                "title": "Citing accessible study",
                "journalTitle": "Open Journal",
                "pubYear": "2026",
                "pmcid": "PMC40600001",
                "isOpenAccess": "Y",
                "inPMC": "Y",
                "hasPDF": "Y",
            }
        ]
    }
}

OPENALEX_WORK = {
    "id": "https://openalex.org/W123",
    "doi": "https://doi.org/10.1000/primary-study",
    "pmid": "https://pubmed.ncbi.nlm.nih.gov/39596913",
    "title": "Primary trial of colchicine",
    "publication_year": 2021,
    "primary_location": {"source": {"display_name": "Example Journal"}},
    "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://example.org/fulltext"},
    "referenced_works": ["https://openalex.org/W999"],
    "related_works": ["https://openalex.org/W888"],
    "cited_by_api_url": "https://api.openalex.org/works?filter=cites:W123",
    "authorships": [
        {
            "author": {
                "id": "https://openalex.org/A1",
                "display_name": "Ada Example",
                "orcid": "https://orcid.org/0000-0001-0000-0000",
            },
            "institutions": [{"display_name": "Example University"}],
        }
    ],
}

UNPAYWALL_WORK = {
    "doi": "10.1000/primary-study",
    "oa_status": "green",
    "is_oa": True,
    "best_oa_location": {"url": "https://example.org/fulltext", "license": "cc-by"},
}

NCBI_ELINK_NEIGHBOR_SCORE = {
    "linksets": [
        {
            "ids": ["40562663"],
            "linksetdbs": [
                {
                    "linkname": "pubmed_pubmed",
                    "links": [
                        {"id": "39596913", "score": 1220},
                        {"id": "40600001", "score": 900},
                    ],
                }
            ],
        }
    ]
}
```

- [ ] **Step 2: Write provider parsing tests**

Create `tests/unit/test_literature_providers.py`:

```python
import httpx
import pytest

from tests.fixtures.literature_graph import (
    CROSSREF_WORK_ARD_2025,
    EUROPE_PMC_CITATIONS_40562663,
    OPENALEX_WORK,
    UNPAYWALL_WORK,
)

from pubtator_link.models.literature_graph import ProviderWarning
from pubtator_link.services.literature_providers import (
    CrossrefClient,
    EuropePmcLiteratureClient,
    OpenAlexClient,
    UnpaywallClient,
)


@pytest.mark.asyncio
async def test_crossref_client_extracts_references_and_uses_mailto() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=CROSSREF_WORK_ARD_2025, request=request)

    client = CrossrefClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        mailto="dev@example.org",
    )

    work = await client.get_work("10.1016/j.ard.2025.05.020")
    references = client.references_from_work(work)

    assert requests[0].url.path.endswith("/works/10.1016%2Fj.ard.2025.05.020")
    assert requests[0].url.params["mailto"] == "dev@example.org"
    assert references[0].doi == "10.1000/primary-study"
    assert references[0].title == "Primary trial of colchicine"
    assert references[1].status == "unresolved_reference"


@pytest.mark.asyncio
async def test_europe_pmc_client_extracts_citations_and_availability() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=EUROPE_PMC_CITATIONS_40562663, request=request)

    client = EuropePmcLiteratureClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        base_url="https://www.ebi.ac.uk/europepmc/webservices/rest",
    )

    citations = await client.get_citations("40562663", limit=25)

    assert citations[0].pmid == "40600001"
    assert citations[0].availability.has_pmc_full_text is True
    assert citations[0].availability.is_open_access is True
    assert citations[0].availability.has_pdf is True


@pytest.mark.asyncio
async def test_openalex_client_extracts_authors_oa_and_related_links() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=OPENALEX_WORK, request=request)

    client = OpenAlexClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        mailto="dev@example.org",
    )

    paper = await client.get_work_by_doi("10.1000/primary-study")

    assert requests[0].url.params["mailto"] == "dev@example.org"
    assert paper.pmid == "39596913"
    assert paper.authors[0].name == "Ada Example"
    assert paper.availability.is_open_access is True
    assert paper.availability.oa_status == "green"


@pytest.mark.asyncio
async def test_unpaywall_disabled_without_email_returns_warning() -> None:
    client = UnpaywallClient(http_client=httpx.AsyncClient(), email=None)

    result = await client.get_oa_status("10.1000/primary-study")

    assert isinstance(result, ProviderWarning)
    assert result.status == "provider_disabled"


@pytest.mark.asyncio
async def test_unpaywall_client_extracts_best_oa_location() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=UNPAYWALL_WORK, request=request)

    client = UnpaywallClient(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        email="dev@example.org",
    )

    availability = await client.get_oa_status("10.1000/primary-study")

    assert availability.is_open_access is True
    assert availability.oa_status == "green"
    assert availability.full_text_url == "https://example.org/fulltext"
```

- [ ] **Step 3: Write ELink neighbor-score tests**

Append to `tests/unit/test_ncbi_discovery_service.py`:

```python
@pytest.mark.asyncio
async def test_ncbi_client_parses_elink_neighbor_scores() -> None:
    from tests.fixtures.literature_graph import NCBI_ELINK_NEIGHBOR_SCORE

    transport = MockTransport(NCBI_ELINK_NEIGHBOR_SCORE)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    records = await client.find_related_article_scores(["40562663"], limit=10)

    assert records[0].source_pmid == "40562663"
    assert records[0].pmid == "39596913"
    assert records[0].neighbor_score == 1220
    assert records[1].pmid == "40600001"
    assert transport.requests[0].url.params["cmd"] == "neighbor_score"
    await client.close()
```

- [ ] **Step 4: Run provider tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_literature_providers.py tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_elink_neighbor_scores -q
```

Expected: FAIL because provider clients and `find_related_article_scores` do not exist.

- [ ] **Step 5: Add config settings**

In `pubtator_link/config.py`, add these fields to `ServerSettings` near the Europe PMC settings:

```python
    crossref_mailto: str | None = Field(default=None, description="Optional Crossref polite-pool mailto")
    openalex_mailto: str | None = Field(default=None, description="Optional OpenAlex polite-pool mailto")
    unpaywall_email: str | None = Field(default=None, description="Required email for optional Unpaywall API use")
```

- [ ] **Step 6: Add provider clients**

Create `pubtator_link/services/literature_providers.py` with:

```python
from __future__ import annotations

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
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.crossref.org",
        mailto: str | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto
        self.retry_policy = retry_policy or RetryPolicy()

    async def close(self) -> None:
        await self.http_client.aclose()

    async def get_work(self, doi: str) -> dict[str, Any]:
        params = {"mailto": self.mailto} if self.mailto else None
        encoded = quote(doi, safe="")
        response, _metadata = await call_with_retries(
            lambda: self.http_client.get(f"{self.base_url}/works/{encoded}", params=params),
            policy=self.retry_policy,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message", {}) if isinstance(payload, dict) else {}
        return message if isinstance(message, dict) else {}

    def references_from_work(self, work: dict[str, Any]) -> list[LiteraturePaper]:
        references = work.get("reference", [])
        if not isinstance(references, list):
            return []
        papers: list[LiteraturePaper] = []
        for item in references:
            if not isinstance(item, dict):
                continue
            doi = _optional_str(item.get("DOI"))
            title = _optional_str(item.get("article-title"))
            journal = _optional_str(item.get("journal-title"))
            year = _optional_int(item.get("year"))
            status = "resolved_metadata_only" if doi else "unresolved_reference"
            papers.append(
                LiteraturePaper(
                    doi=doi,
                    title=title,
                    journal=journal,
                    year=year,
                    status=status,
                    provenance=[
                        LiteratureGraphProvenance(
                            provider=CROSSREF_PROVIDER,
                            source_id=_optional_str(work.get("DOI")),
                        )
                    ],
                )
            )
        return papers


class EuropePmcLiteratureClient:
    def __init__(self, *, http_client: httpx.AsyncClient, base_url: str) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")

    async def close(self) -> None:
        await self.http_client.aclose()

    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        response = await self.http_client.get(
            f"{self.base_url}/search",
            params={
                "query": f"CITES:{pmid}",
                "format": "json",
                "resultType": "core",
                "pageSize": str(limit),
            },
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("resultList", {}).get("result", []) if isinstance(payload, dict) else []
        return [_paper_from_europe_pmc_record(record) for record in records if isinstance(record, dict)]


class OpenAlexClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        base_url: str = "https://api.openalex.org",
        mailto: str | None = None,
    ) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")
        self.mailto = mailto

    async def close(self) -> None:
        await self.http_client.aclose()

    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        params = {"mailto": self.mailto} if self.mailto else None
        response = await self.http_client.get(f"{self.base_url}/works/https://doi.org/{doi}", params=params)
        response.raise_for_status()
        payload = response.json()
        return _paper_from_openalex_work(payload if isinstance(payload, dict) else {})


class UnpaywallClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient,
        email: str | None,
        base_url: str = "https://api.unpaywall.org/v2",
    ) -> None:
        self.http_client = http_client
        self.email = email
        self.base_url = base_url.rstrip("/")

    async def close(self) -> None:
        await self.http_client.aclose()

    async def get_oa_status(self, doi: str) -> LiteratureAvailability | ProviderWarning:
        if not self.email:
            return ProviderWarning(
                provider=UNPAYWALL_PROVIDER,
                status=PROVIDER_DISABLED,
                retryable=False,
                message="UNPAYWALL_EMAIL is not configured.",
            )
        response = await self.http_client.get(f"{self.base_url}/{doi}", params={"email": self.email})
        response.raise_for_status()
        payload = response.json()
        best = payload.get("best_oa_location", {}) if isinstance(payload, dict) else {}
        best = best if isinstance(best, dict) else {}
        return LiteratureAvailability(
            is_open_access=bool(payload.get("is_oa")) if isinstance(payload, dict) else False,
            oa_status=_optional_str(payload.get("oa_status")) if isinstance(payload, dict) else None,
            full_text_url=_optional_str(best.get("url")),
            license_or_access_hint=_optional_str(best.get("license")),
        )


def _paper_from_europe_pmc_record(record: dict[str, Any]) -> LiteraturePaper:
    is_oa = str(record.get("isOpenAccess", "")).upper() == "Y"
    in_pmc = str(record.get("inPMC", "")).upper() == "Y"
    has_pdf = str(record.get("hasPDF", "")).upper() == "Y"
    return LiteraturePaper(
        pmid=_optional_str(record.get("pmid") or record.get("id")),
        doi=_optional_str(record.get("doi")),
        pmcid=_optional_str(record.get("pmcid")),
        title=_optional_str(record.get("title")),
        journal=_optional_str(record.get("journalTitle")),
        year=_optional_int(record.get("pubYear")),
        availability=LiteratureAvailability(
            has_pmc_full_text=in_pmc,
            is_open_access=is_oa,
            has_pdf=has_pdf,
        ),
        status="resolved_full_text_candidate" if in_pmc or is_oa else "resolved_metadata_only",
        provenance=[LiteratureGraphProvenance(provider=EUROPE_PMC_PROVIDER, source_id=_optional_str(record.get("id")))],
    )


def _paper_from_openalex_work(work: dict[str, Any]) -> LiteraturePaper:
    oa = work.get("open_access", {})
    oa = oa if isinstance(oa, dict) else {}
    location = work.get("primary_location", {})
    location = location if isinstance(location, dict) else {}
    source = location.get("source", {})
    source = source if isinstance(source, dict) else {}
    return LiteraturePaper(
        pmid=_extract_openalex_pmid(_optional_str(work.get("pmid"))),
        doi=_extract_openalex_doi(_optional_str(work.get("doi"))),
        openalex_id=_optional_str(work.get("id")),
        title=_optional_str(work.get("title")),
        journal=_optional_str(source.get("display_name")),
        year=_optional_int(work.get("publication_year")),
        authors=_openalex_authors(work.get("authorships")),
        availability=LiteratureAvailability(
            is_open_access=bool(oa.get("is_oa")),
            oa_status=_optional_str(oa.get("oa_status")),
            full_text_url=_optional_str(oa.get("oa_url")),
        ),
        status="resolved_full_text_candidate" if bool(oa.get("is_oa")) else "resolved_metadata_only",
        provenance=[LiteratureGraphProvenance(provider=OPENALEX_PROVIDER, source_id=_optional_str(work.get("id")))],
    )


def _openalex_authors(value: object) -> list[LiteratureAuthor]:
    if not isinstance(value, list):
        return []
    authors: list[LiteratureAuthor] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        author = item.get("author", {})
        author = author if isinstance(author, dict) else {}
        institutions = item.get("institutions", [])
        affiliations = [
            str(inst.get("display_name"))
            for inst in institutions
            if isinstance(inst, dict) and inst.get("display_name")
        ] if isinstance(institutions, list) else []
        name = _optional_str(author.get("display_name"))
        if name:
            authors.append(
                LiteratureAuthor(
                    name=name,
                    openalex_id=_optional_str(author.get("id")),
                    orcid=_optional_str(author.get("orcid")),
                    affiliations=affiliations,
                )
            )
    return authors


def _extract_openalex_doi(value: str | None) -> str | None:
    if value is None:
        return None
    return value.removeprefix("https://doi.org/")


def _extract_openalex_pmid(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 7: Add NCBI neighbor-score model and client method**

In `pubtator_link/models/discovery.py`, add:

```python
class RelatedArticleScoreRecord(BaseModel):
    """One PubMed related article result with neighbor score."""

    source_pmid: str
    pmid: str
    neighbor_score: int
```

In `pubtator_link/services/ncbi_discovery.py`, import `RelatedArticleScoreRecord` and add this method to `NcbiDiscoveryClientProtocol`:

```python
    async def find_related_article_scores(
        self,
        pmids: Sequence[str],
        limit: int,
    ) -> list[RelatedArticleScoreRecord]:
        """Find related PubMed articles with ELink neighbor scores."""
```

Add this method to `NcbiDiscoveryClient`:

```python
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
            emitted = 0
            linksetdbs = linkset.get("linksetdbs", [])
            if not isinstance(linksetdbs, list | tuple):
                continue
            for linksetdb in linksetdbs:
                if emitted >= limit or not isinstance(linksetdb, dict):
                    break
                links = linksetdb.get("links", [])
                if not isinstance(links, list | tuple):
                    continue
                for link in links:
                    if emitted >= limit:
                        break
                    if isinstance(link, dict):
                        linked_pmid = _optional_str(link.get("id"))
                        score = int(link.get("score") or 0)
                    else:
                        linked_pmid = _optional_str(link)
                        score = 0
                    if linked_pmid is None or linked_pmid == source_pmid:
                        continue
                    records.append(
                        RelatedArticleScoreRecord(
                            source_pmid=source_pmid,
                            pmid=linked_pmid,
                            neighbor_score=score,
                        )
                    )
                    emitted += 1
        return records
```

- [ ] **Step 8: Run provider tests**

Run:

```bash
uv run pytest tests/unit/test_literature_providers.py tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_parses_elink_neighbor_scores -q
```

Expected: PASS.

- [ ] **Step 9: Commit providers**

```bash
git add pubtator_link/config.py pubtator_link/models/discovery.py pubtator_link/services/literature_providers.py pubtator_link/services/ncbi_discovery.py tests/fixtures/literature_graph.py tests/unit/test_literature_providers.py tests/unit/test_ncbi_discovery_service.py
git commit -m "feat: add literature metadata providers"
```

---

### Task 3: Citation Graph Service

**Files:**
- Create: `pubtator_link/services/citation_graph.py`
- Create: `tests/unit/test_citation_graph_service.py`

- [ ] **Step 1: Write citation graph service tests**

Create `tests/unit/test_citation_graph_service.py`:

```python
import pytest

from pubtator_link.models.literature_graph import (
    LiteratureGraphProvenance,
    LiteraturePaper,
    ProviderWarning,
    PublicationCitationGraphRequest,
)
from pubtator_link.services.citation_graph import CitationGraphService


class FakeCrossref:
    async def get_work(self, doi: str) -> dict[str, object]:
        assert doi == "10.1016/j.ard.2025.05.020"
        return {"DOI": doi}

    def references_from_work(self, work: dict[str, object]) -> list[LiteraturePaper]:
        return [
            LiteraturePaper(
                doi="10.1000/primary-study",
                title="Primary trial",
                provenance=[LiteratureGraphProvenance(provider="crossref", source_id=str(work["DOI"]))],
            )
        ]


class FakeEuropePmc:
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        assert pmid == "40562663"
        return [
            LiteraturePaper(
                pmid="40600001",
                doi="10.1000/citing-study",
                title="Citing study",
                status="resolved_full_text_candidate",
                provenance=[LiteratureGraphProvenance(provider="europe_pmc", source_id="40600001")],
            )
        ]


class FailingEuropePmc:
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        raise RuntimeError("europe pmc unavailable")


class FakeDiscovery:
    async def convert_article_ids(self, ids, source="auto"):
        class Response:
            records = []
        return Response()


class FakeMetadata:
    async def get_metadata(self, request):
        class Response:
            metadata = []
            failed_pmids = {}
        return Response()


@pytest.mark.asyncio
async def test_citation_graph_returns_crossref_references_for_doi() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(doi="10.1016/j.ard.2025.05.020", direction="references")
    )

    assert response.source.doi == "10.1016/j.ard.2025.05.020"
    assert response.references[0].doi == "10.1000/primary-study"
    assert response.references[0].provenance[0].provider == "crossref"
    assert response.candidate_pmids == []


@pytest.mark.asyncio
async def test_citation_graph_returns_cited_by_results_for_pmid() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(pmid="40562663", direction="cited_by")
    )

    assert response.source.pmid == "40562663"
    assert response.cited_by[0].pmid == "40600001"
    assert response.candidate_pmids == ["40600001"]


@pytest.mark.asyncio
async def test_citation_graph_degrades_when_one_provider_fails() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FailingEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(doi="10.1016/j.ard.2025.05.020", direction="both")
    )

    assert response.references[0].doi == "10.1000/primary-study"
    assert response.meta.warnings[0].provider == "europe_pmc"
    assert response.meta.warnings[0].status == "provider_failed"


@pytest.mark.asyncio
async def test_citation_graph_reports_doi_only_partial_identifier_resolution() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(doi="10.1016/j.ard.2025.05.020", direction="both")
    )

    statuses = {warning.status for warning in response.meta.warnings}
    assert "partial_identifier_resolution" in statuses
```

- [ ] **Step 2: Run citation graph tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.services.citation_graph'`.

- [ ] **Step 3: Implement citation graph service**

Create `pubtator_link/services/citation_graph.py`:

```python
from __future__ import annotations

from typing import Protocol

from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    LiteratureResponseMeta,
    ProviderWarning,
    PublicationCitationGraphRequest,
    PublicationCitationGraphResponse,
    dedupe_papers,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.services.literature_providers import CROSSREF_PROVIDER, EUROPE_PMC_PROVIDER


class CrossrefProvider(Protocol):
    async def get_work(self, doi: str) -> dict[str, object]:
        raise NotImplementedError

    def references_from_work(self, work: dict[str, object]) -> list[LiteraturePaper]:
        raise NotImplementedError


class EuropePmcCitationProvider(Protocol):
    async def get_citations(self, pmid: str, *, limit: int) -> list[LiteraturePaper]:
        raise NotImplementedError


class CitationGraphService:
    def __init__(
        self,
        *,
        crossref: CrossrefProvider | None,
        europe_pmc: EuropePmcCitationProvider | None,
        discovery_service: object,
        metadata_service: object,
    ) -> None:
        self.crossref = crossref
        self.europe_pmc = europe_pmc
        self.discovery_service = discovery_service
        self.metadata_service = metadata_service

    async def get_citation_graph(
        self,
        request: PublicationCitationGraphRequest,
    ) -> PublicationCitationGraphResponse:
        source = await self._source_paper(request)
        warnings: list[ProviderWarning] = []
        references: list[LiteraturePaper] = []
        cited_by: list[LiteraturePaper] = []

        if request.doi is not None and source.pmid is None and request.direction in {"both", "cited_by"}:
            warnings.append(
                ProviderWarning(
                    provider="identifier_resolution",
                    status="partial_identifier_resolution",
                    retryable=False,
                    message="DOI source did not resolve to a PMID; PMID-only cited-by providers were skipped.",
                )
            )

        if request.direction in {"both", "references"} and source.doi and self.crossref is not None:
            try:
                work = await self.crossref.get_work(source.doi)
                references.extend(self.crossref.references_from_work(work))
            except Exception as exc:
                warnings.append(_provider_warning(CROSSREF_PROVIDER, exc))

        if request.direction in {"both", "cited_by"} and source.pmid and self.europe_pmc is not None:
            try:
                cited_by.extend(await self.europe_pmc.get_citations(source.pmid, limit=request.max_results))
            except Exception as exc:
                warnings.append(_provider_warning(EUROPE_PMC_PROVIDER, exc))

        references = dedupe_papers(references)[: request.max_results]
        cited_by = dedupe_papers(cited_by)[: request.max_results]
        candidate_pmids = _candidate_pmids([*references, *cited_by])
        metadata_only = [
            paper
            for paper in [*references, *cited_by]
            if paper.status in {"resolved_metadata_only", "unresolved_reference", "publisher_entitlement_required"}
        ]
        return PublicationCitationGraphResponse(
            source=source,
            references=references,
            cited_by=cited_by,
            candidate_pmids=candidate_pmids,
            metadata_only=metadata_only,
            _meta=LiteratureResponseMeta(warnings=warnings, next_commands=_next_commands(candidate_pmids)),
        )

    async def _source_paper(self, request: PublicationCitationGraphRequest) -> LiteraturePaper:
        if request.pmid is not None:
            paper = await self._metadata_source(request.pmid)
            return paper or LiteraturePaper(pmid=request.pmid)
        return LiteraturePaper(doi=request.doi)

    async def _metadata_source(self, pmid: str) -> LiteraturePaper | None:
        try:
            response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=[pmid],
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
        except Exception:
            return None
        metadata = response.metadata[0] if getattr(response, "metadata", []) else None
        if metadata is None:
            return None
        return LiteraturePaper(
            pmid=metadata.pmid,
            doi=metadata.doi,
            pmcid=metadata.pmcid,
            title=metadata.title,
            journal=metadata.journal,
            year=metadata.pub_year,
            publication_types=metadata.publication_types,
        )


def _provider_warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(
        provider=provider,
        status="provider_failed",
        retryable=True,
        message=exc.__class__.__name__,
    )


def _candidate_pmids(papers: list[LiteraturePaper]) -> list[str]:
    return list(dict.fromkeys([paper.pmid for paper in papers if paper.pmid is not None]))


def _next_commands(pmids: list[str]) -> list[dict[str, object]]:
    if not pmids:
        return []
    return [
        {"tool": "pubtator.get_publication_passages", "arguments": {"pmids": pmids}},
        {"tool": "pubtator.index_review_evidence", "arguments": {"pmids": pmids, "prepare_mode": "selected"}},
    ]
```

- [ ] **Step 4: Run citation graph tests**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit citation graph service**

```bash
git add pubtator_link/services/citation_graph.py tests/unit/test_citation_graph_service.py
git commit -m "feat: add citation graph service"
```

---

### Task 4: Citation Graph REST And MCP Surface

**Files:**
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/publications.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/profiles.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Modify: `tests/test_routes/test_publication_literature_graph.py`
- Modify: `tests/unit/mcp/test_mcp_profiles.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Regenerate: `docs/mcp-tool-catalog.md`

- [ ] **Step 1: Write citation graph route tests**

Create `tests/test_routes/test_publication_literature_graph.py`:

```python
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_citation_graph_service
from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    PublicationCitationGraphResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


@pytest.mark.asyncio
async def test_citation_graph_route_validates_exactly_one_identifier() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    app.dependency_overrides[get_citation_graph_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/publications/citation-graph",
            json={"pmid": "40562663", "doi": "10.1016/j.ard.2025.05.020"},
        )

    assert response.status_code == 422
    service.get_citation_graph.assert_not_called()


@pytest.mark.asyncio
async def test_citation_graph_route_returns_response() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_citation_graph.return_value = PublicationCitationGraphResponse(
        source=LiteraturePaper(pmid="40562663"),
        cited_by=[LiteraturePaper(pmid="40600001", title="Citing study")],
        candidate_pmids=["40600001"],
    )
    app.dependency_overrides[get_citation_graph_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/publications/citation-graph",
            json={"pmid": "40562663", "direction": "cited_by"},
        )

    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["40600001"]
    request = service.get_citation_graph.await_args.args[0]
    assert request.pmid == "40562663"
```

- [ ] **Step 2: Write citation graph MCP tests**

Append to `tests/unit/mcp/test_mcp_profiles.py`:

```python
def test_citation_graph_is_lean_full_and_readonly() -> None:
    for profile in ("lean", "full", "readonly"):
        assert "pubtator.get_publication_citation_graph" in _tool_names(profile)
```

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_citation_graph_tool_schema_is_flat() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp(profile="full")._tool_manager._tools[
        "pubtator.get_publication_citation_graph"
    ]
    properties = tool.parameters["properties"]

    assert "pmid" in properties
    assert "doi" in properties
    assert "request" not in properties
    assert tool.output_schema["title"] == "PublicationCitationGraphResponse"
```

- [ ] **Step 3: Run surface tests to verify they fail**

Run:

```bash
uv run pytest tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py::test_citation_graph_is_lean_full_and_readonly tests/unit/mcp/test_mcp_facade.py::test_citation_graph_tool_schema_is_flat -q
```

Expected: FAIL because dependencies, route, and MCP tool do not exist.

- [ ] **Step 4: Wire dependency injection**

In `pubtator_link/api/routes/dependencies.py`:

- Import `CrossrefClient`, `EuropePmcLiteratureClient`, and `CitationGraphService`.
- Add globals:

```python
_crossref_client: CrossrefClient | None = None
_europe_pmc_literature_client: EuropePmcLiteratureClient | None = None
_citation_graph_service: CitationGraphService | None = None
```

- Add fields to `AppResources`:

```python
crossref_client: CrossrefClient | None = None
europe_pmc_literature_client: EuropePmcLiteratureClient | None = None
citation_graph_service: CitationGraphService | None = None
```

- In `create_app_resources`, instantiate both provider clients and pass them to `AppResources`:

```python
crossref_client = CrossrefClient(
    http_client=httpx.AsyncClient(),
    mailto=settings.crossref_mailto,
)
europe_pmc_literature_client = EuropePmcLiteratureClient(
    http_client=httpx.AsyncClient(),
    base_url=review_rerag_config.europe_pmc_base_url,
)
```

- In `close_app_resources`, close both provider clients by calling `await resources.crossref_client.close()` and `await resources.europe_pmc_literature_client.close()` when present. Add a `close()` method to each provider client in `pubtator_link/services/literature_providers.py` that closes the owned `httpx.AsyncClient`.
- In `cleanup_dependencies`, add `_crossref_client`, `_europe_pmc_literature_client`, and `_citation_graph_service` to the global list. Close and clear `_crossref_client` and `_europe_pmc_literature_client`, then set `_citation_graph_service = None`.
- Add:

```python
async def get_citation_graph_service() -> CitationGraphService:
    """Get publication citation graph service."""
    global _crossref_client, _europe_pmc_literature_client, _citation_graph_service
    resources = current_app_resources()
    if resources is not None:
        if resources.citation_graph_service is None:
            if resources.crossref_client is None:
                resources.crossref_client = CrossrefClient(
                    http_client=httpx.AsyncClient(),
                    mailto=settings.crossref_mailto,
                )
            if resources.europe_pmc_literature_client is None:
                resources.europe_pmc_literature_client = EuropePmcLiteratureClient(
                    http_client=httpx.AsyncClient(),
                    base_url=review_rerag_config.europe_pmc_base_url,
                )
            resources.citation_graph_service = CitationGraphService(
                crossref=resources.crossref_client,
                europe_pmc=resources.europe_pmc_literature_client,
                discovery_service=await get_discovery_service(),
                metadata_service=await get_publication_metadata_service(),
            )
        return resources.citation_graph_service
    if _citation_graph_service is None:
        if _crossref_client is None:
            _crossref_client = CrossrefClient(
                http_client=httpx.AsyncClient(),
                mailto=settings.crossref_mailto,
            )
        if _europe_pmc_literature_client is None:
            _europe_pmc_literature_client = EuropePmcLiteratureClient(
                http_client=httpx.AsyncClient(),
                base_url=review_rerag_config.europe_pmc_base_url,
            )
        _citation_graph_service = CitationGraphService(
            crossref=_crossref_client,
            europe_pmc=_europe_pmc_literature_client,
            discovery_service=await get_discovery_service(),
            metadata_service=await get_publication_metadata_service(),
        )
    return _citation_graph_service
```

Add this type alias near existing route dependency aliases if the file uses them:

```python
CitationGraphServiceDep = Annotated[CitationGraphService, Depends(get_citation_graph_service)]
```

- [ ] **Step 5: Add REST route**

In `pubtator_link/api/routes/publications.py`, import `PublicationCitationGraphRequest`, `PublicationCitationGraphResponse`, and `CitationGraphServiceDep`. Add:

```python
@router.post(
    "/citation-graph",
    response_model=PublicationCitationGraphResponse,
    operation_id="get_publication_citation_graph",
    summary="Get publication citation graph",
)
@handle_api_errors
async def get_publication_citation_graph(
    request: PublicationCitationGraphRequest,
    service: CitationGraphServiceDep,
) -> PublicationCitationGraphResponse:
    """Return metadata-first references and cited-by records for a source article."""
    return await service.get_citation_graph(request)
```

- [ ] **Step 6: Add MCP adapter and tool**

In `pubtator_link/mcp/service_adapters.py`, import `PublicationCitationGraphRequest` and add:

```python
async def get_publication_citation_graph_impl(
    *,
    service: Any,
    pmid: str | None = None,
    doi: str | None = None,
    direction: Literal["references", "cited_by", "both"] = "both",
    resolve_metadata: bool = True,
    include_open_access_status: bool = True,
    max_results: int = 50,
) -> dict[str, Any]:
    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid=pmid,
            doi=doi,
            direction=direction,
            resolve_metadata=resolve_metadata,
            include_open_access_status=include_open_access_status,
            max_results=max_results,
        )
    )
    return response.model_dump(by_alias=True)
```

In `pubtator_link/mcp/tools/publications.py`, import `get_citation_graph_service`, `PublicationCitationGraphResponse`, and the adapter. Add inside `register_publication_tools`:

```python
    @mcp.tool(
        name="pubtator.get_publication_citation_graph",
        title="Get Publication Citation Graph",
        output_schema=PublicationCitationGraphResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_citation_graph(
        pmid: Annotated[str | None, Field(default=None, description="Numeric PMID string")] = None,
        doi: Annotated[str | None, Field(default=None, description="DOI string")] = None,
        direction: Literal["references", "cited_by", "both"] = "both",
        resolve_metadata: bool = True,
        include_open_access_status: bool = True,
        max_results: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        """Use this when a user needs reference or cited-by neighbors for one publication before deciding which sources to inspect next."""

        async def call() -> dict[str, Any]:
            service = await get_citation_graph_service()
            return await get_publication_citation_graph_impl(
                service=service,
                pmid=pmid,
                doi=doi,
                direction=direction,
                resolve_metadata=resolve_metadata,
                include_open_access_status=include_open_access_status,
                max_results=max_results,
            )

        return await run_mcp_tool("pubtator.get_publication_citation_graph", call, pmids=[pmid] if pmid else None)
```

- [ ] **Step 7: Update MCP profiles and catalog supplement**

In `pubtator_link/mcp/profiles.py`, add `"pubtator.get_publication_citation_graph"` to `LEAN_TOOLS`.

In `pubtator_link/mcp/catalog.py`, add:

```python
    "pubtator.get_publication_citation_graph": ToolCatalogSupplement(
        category="publication",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("claim-level evidence support", "publisher full-text retrieval"),
        example='{"pmid":"40562663","direction":"both","max_results":50}',
        next_tools=("pubtator.find_related_evidence_candidates", "pubtator.get_publication_passages"),
    ),
```

- [ ] **Step 8: Run citation graph surface tests**

Run:

```bash
uv run pytest tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py::test_citation_graph_is_lean_full_and_readonly tests/unit/mcp/test_mcp_facade.py::test_citation_graph_tool_schema_is_flat -q
```

Expected: PASS.

- [ ] **Step 9: Regenerate MCP catalog and run catalog test**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: PASS and `docs/mcp-tool-catalog.md` contains `pubtator.get_publication_citation_graph`.

- [ ] **Step 10: Commit citation graph surface**

```bash
git add pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/publications.py pubtator_link/mcp/tools/publications.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/profiles.py pubtator_link/mcp/catalog.py docs/mcp-tool-catalog.md tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py
git commit -m "feat: expose publication citation graph"
```

---

### Task 5: Related Evidence Service And Surface

**Files:**
- Create: `pubtator_link/services/related_evidence.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/publications.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/profiles.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Modify: `tests/test_routes/test_publication_literature_graph.py`
- Create: `tests/unit/test_related_evidence_service.py`
- Modify: `tests/unit/mcp/test_mcp_profiles.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Regenerate: `docs/mcp-tool-catalog.md`

- [ ] **Step 1: Write related evidence service tests**

Create `tests/unit/test_related_evidence_service.py`:

```python
import pytest

from pubtator_link.models.discovery import RelatedArticleScoreRecord
from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteraturePaper,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidatesRequest,
)
from pubtator_link.services.related_evidence import RelatedEvidenceService


class FakeDiscovery:
    async def find_related_article_scores(self, pmids, limit):
        return [
            RelatedArticleScoreRecord(source_pmid="40562663", pmid="111", neighbor_score=900),
            RelatedArticleScoreRecord(source_pmid="40562663", pmid="222", neighbor_score=900),
            RelatedArticleScoreRecord(source_pmid="40562663", pmid="333", neighbor_score=700),
        ]


class FakeMetadata:
    async def get_metadata(self, request):
        class Metadata:
            def __init__(self, pmid, title, pub_year, publication_types, coverage):
                self.pmid = pmid
                self.title = title
                self.pub_year = pub_year
                self.publication_types = publication_types
                self.coverage = coverage
                self.coverage_reason = None
                self.doi = None
                self.pmcid = f"PMC{pmid}" if pmid == "222" else None
                self.journal = "Journal"
                self.authors = []

        class Response:
            metadata = [
                Metadata("111", "Abstract only", 2024, ["Review"], "abstract"),
                Metadata("222", "Full text paper", 2023, ["Review"], "full_text"),
                Metadata("333", "Older paper", 2020, ["Case Reports"], "abstract"),
            ]
            failed_pmids = {}

        return Response()


class FakeCitationGraph:
    async def get_citation_graph(self, request):
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid="222", title="Full text paper")],
            candidate_pmids=["222"],
        )


@pytest.mark.asyncio
async def test_related_evidence_ranks_full_text_ahead_when_scores_tie() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(RelatedEvidenceCandidatesRequest(pmid="40562663"))

    assert [candidate.paper.pmid for candidate in response.candidates[:2]] == ["222", "111"]
    assert "full_text_available" in response.candidates[0].match_reasons
    assert response.candidates[0].pubmed_neighbor_score == 900


@pytest.mark.asyncio
async def test_related_evidence_filters_publication_type_and_year() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="40562663",
            publication_types=["Review"],
            year_min=2024,
            include_citation_neighbors=False,
        )
    )

    assert [candidate.paper.pmid for candidate in response.candidates] == ["111"]


@pytest.mark.asyncio
async def test_related_evidence_reports_elink_failure() -> None:
    class FailingDiscovery:
        async def find_related_article_scores(self, pmids, limit):
            raise RuntimeError("elink unavailable")

    service = RelatedEvidenceService(
        discovery_service=FailingDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(RelatedEvidenceCandidatesRequest(pmid="40562663"))

    assert response.candidates
    assert response.meta.warnings[0].provider == "ncbi_elink"
    assert response.meta.warnings[0].status == "provider_failed"
```

- [ ] **Step 2: Run related evidence service tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.services.related_evidence'`.

- [ ] **Step 3: Implement related evidence service**

Create `pubtator_link/services/related_evidence.py`:

```python
from __future__ import annotations

from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteraturePaper,
    LiteratureResponseMeta,
    ProviderWarning,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesRequest,
    RelatedEvidenceCandidatesResponse,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest


class RelatedEvidenceService:
    def __init__(
        self,
        *,
        discovery_service: object,
        metadata_service: object,
        citation_graph_service: object,
    ) -> None:
        self.discovery_service = discovery_service
        self.metadata_service = metadata_service
        self.citation_graph_service = citation_graph_service

    async def find_candidates(
        self,
        request: RelatedEvidenceCandidatesRequest,
    ) -> RelatedEvidenceCandidatesResponse:
        warnings: list[ProviderWarning] = []
        neighbor_scores: dict[str, int] = {}
        candidate_pmids: list[str] = []

        try:
            records = await self.discovery_service.find_related_article_scores([request.pmid], request.max_results)
            for record in records:
                neighbor_scores[record.pmid] = record.neighbor_score
                candidate_pmids.append(record.pmid)
        except Exception as exc:
            warnings.append(_warning("ncbi_elink", exc))

        if request.include_citation_neighbors:
            try:
                graph = await self.citation_graph_service.get_citation_graph(
                    PublicationCitationGraphRequest(pmid=request.pmid, direction="both", max_results=request.max_results)
                )
                candidate_pmids.extend(graph.candidate_pmids)
                warnings.extend(graph.meta.warnings)
            except Exception as exc:
                warnings.append(_warning("citation_graph", exc))

        candidate_pmids = list(dict.fromkeys([pmid for pmid in candidate_pmids if pmid != request.pmid]))
        papers = await self._metadata_papers(candidate_pmids)
        candidates = [
            self._candidate_from_paper(paper, neighbor_scores.get(paper.pmid or "", 0), request)
            for paper in papers
            if self._passes_filters(paper, request)
        ]
        candidates.sort(key=lambda candidate: _ranking_key(candidate, request))
        candidates = candidates[: request.max_results]
        output_pmids = [candidate.paper.pmid for candidate in candidates if candidate.paper.pmid]
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=candidates,
            candidate_pmids=output_pmids,
            _meta=LiteratureResponseMeta(warnings=warnings, next_commands=_next_commands(output_pmids)),
        )

    async def _metadata_papers(self, pmids: list[str]) -> list[LiteraturePaper]:
        if not pmids:
            return []
        response = await self.metadata_service.get_metadata(
            PublicationMetadataRequest(
                pmids=pmids,
                include_mesh=False,
                include_publication_types=True,
                include_citations="none",
                include_coverage=True,
            )
        )
        papers: list[LiteraturePaper] = []
        for item in response.metadata:
            full_text = getattr(item, "coverage", None) == "full_text" or bool(item.pmcid)
            papers.append(
                LiteraturePaper(
                    pmid=item.pmid,
                    doi=item.doi,
                    pmcid=item.pmcid,
                    title=item.title,
                    journal=item.journal,
                    year=item.pub_year,
                    publication_types=item.publication_types,
                    availability=LiteratureAvailability(has_pmc_full_text=full_text, is_open_access=full_text),
                    status="resolved_full_text_candidate" if full_text else "resolved_metadata_only",
                )
            )
        return papers

    def _candidate_from_paper(
        self,
        paper: LiteraturePaper,
        neighbor_score: int,
        request: RelatedEvidenceCandidatesRequest,
    ) -> RelatedEvidenceCandidate:
        reasons = ["pubmed_neighbor_score"] if neighbor_score else ["citation_neighbor"]
        if paper.availability.has_pmc_full_text or paper.availability.is_open_access:
            reasons.append("full_text_available")
        if request.publication_types and set(request.publication_types) & set(paper.publication_types):
            reasons.append("requested_publication_type")
        return RelatedEvidenceCandidate(
            paper=paper,
            score=float(neighbor_score),
            pubmed_neighbor_score=neighbor_score or None,
            match_reasons=reasons,
        )

    def _passes_filters(
        self,
        paper: LiteraturePaper,
        request: RelatedEvidenceCandidatesRequest,
    ) -> bool:
        if request.year_min is not None and (paper.year is None or paper.year < request.year_min):
            return False
        if request.year_max is not None and (paper.year is None or paper.year > request.year_max):
            return False
        if request.publication_types and not (set(request.publication_types) & set(paper.publication_types)):
            return False
        return True


def _ranking_key(
    candidate: RelatedEvidenceCandidate,
    request: RelatedEvidenceCandidatesRequest,
) -> tuple[int, int, int, int, int, str]:
    paper = candidate.paper
    full_text_rank = 1 if request.prefer_full_text and (paper.availability.has_pmc_full_text or paper.availability.is_open_access) else 0
    publication_type_rank = 1 if request.publication_types and set(request.publication_types) & set(paper.publication_types) else 0
    return (
        -(candidate.pubmed_neighbor_score or 0),
        -full_text_rank,
        0,
        -publication_type_rank,
        -(paper.year or 0),
        paper.pmid or paper.key,
    )


def _warning(provider: str, exc: Exception) -> ProviderWarning:
    return ProviderWarning(provider=provider, status="provider_failed", retryable=True, message=exc.__class__.__name__)


def _next_commands(pmids: list[str]) -> list[dict[str, object]]:
    if not pmids:
        return []
    return [{"tool": "pubtator.get_publication_passages", "arguments": {"pmids": pmids}}]
```

- [ ] **Step 4: Run related evidence service tests**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Add REST route and dependency**

In `pubtator_link/api/routes/dependencies.py`, add a global `_related_evidence_service`, an `AppResources.related_evidence_service` field, a getter `get_related_evidence_service()`, and alias:

```python
RelatedEvidenceServiceDep = Annotated[RelatedEvidenceService, Depends(get_related_evidence_service)]
```

The getter constructs `RelatedEvidenceService` with `get_discovery_service()`, `get_publication_metadata_service()`, and `get_citation_graph_service()`.

Also add `_related_evidence_service` to `cleanup_dependencies` globals and set it to `None` during cleanup.

In `pubtator_link/api/routes/publications.py`, add:

```python
@router.post(
    "/related-evidence",
    response_model=RelatedEvidenceCandidatesResponse,
    operation_id="find_related_evidence_candidates",
    summary="Find related evidence candidates",
)
@handle_api_errors
async def find_related_evidence_candidates(
    request: RelatedEvidenceCandidatesRequest,
    service: RelatedEvidenceServiceDep,
) -> RelatedEvidenceCandidatesResponse:
    """Return conservative related evidence candidates for a source PMID."""
    return await service.find_candidates(request)
```

- [ ] **Step 6: Add route tests**

Append to `tests/test_routes/test_publication_literature_graph.py`:

```python
from pubtator_link.api.routes.dependencies import get_related_evidence_service
from pubtator_link.models.literature_graph import (
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesResponse,
)


@pytest.mark.asyncio
async def test_related_evidence_route_returns_candidates() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.find_candidates.return_value = RelatedEvidenceCandidatesResponse(
        source=LiteraturePaper(pmid="40562663"),
        candidates=[RelatedEvidenceCandidate(paper=LiteraturePaper(pmid="222", title="Candidate"))],
        candidate_pmids=["222"],
    )
    app.dependency_overrides[get_related_evidence_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/publications/related-evidence",
            json={"pmid": "40562663", "max_results": 25},
        )

    assert response.status_code == 200
    assert response.json()["candidate_pmids"] == ["222"]


@pytest.mark.asyncio
async def test_related_evidence_route_rejects_non_numeric_pmid() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    app.dependency_overrides[get_related_evidence_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/publications/related-evidence", json={"pmid": "abc"})

    assert response.status_code == 422
    service.find_candidates.assert_not_called()
```

- [ ] **Step 7: Add MCP adapter and tool**

In `pubtator_link/mcp/service_adapters.py`, add:

```python
async def find_related_evidence_candidates_impl(
    *,
    service: Any,
    pmid: str,
    max_results: int = 25,
    prefer_full_text: bool = True,
    include_pubtator_search: bool = True,
    include_citation_neighbors: bool = True,
    publication_types: list[str] | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> dict[str, Any]:
    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid=pmid,
            max_results=max_results,
            prefer_full_text=prefer_full_text,
            include_pubtator_search=include_pubtator_search,
            include_citation_neighbors=include_citation_neighbors,
            publication_types=publication_types,
            year_min=year_min,
            year_max=year_max,
        )
    )
    return response.model_dump(by_alias=True)
```

In `pubtator_link/mcp/tools/publications.py`, add:

```python
    @mcp.tool(
        name="pubtator.find_related_evidence_candidates",
        title="Find Related Evidence Candidates",
        output_schema=RelatedEvidenceCandidatesResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_related_evidence_candidates(
        pmid: Annotated[str, Field(min_length=1, max_length=20)],
        max_results: Annotated[int, Field(ge=1, le=100)] = 25,
        prefer_full_text: bool = True,
        include_pubtator_search: bool = True,
        include_citation_neighbors: bool = True,
        publication_types: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
    ) -> dict[str, Any]:
        """Use this when a user has one seed PMID and needs transparent nearby evidence candidates to inspect next."""

        async def call() -> dict[str, Any]:
            service = await get_related_evidence_service()
            return await find_related_evidence_candidates_impl(
                service=service,
                pmid=pmid,
                max_results=max_results,
                prefer_full_text=prefer_full_text,
                include_pubtator_search=include_pubtator_search,
                include_citation_neighbors=include_citation_neighbors,
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
            )

        return await run_mcp_tool("pubtator.find_related_evidence_candidates", call, pmids=[pmid])
```

- [ ] **Step 8: Update MCP profile and catalog tests**

Append to `tests/unit/mcp/test_mcp_profiles.py`:

```python
def test_related_evidence_is_lean_full_and_readonly() -> None:
    for profile in ("lean", "full", "readonly"):
        assert "pubtator.find_related_evidence_candidates" in _tool_names(profile)
```

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_related_evidence_tool_schema_is_flat() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp(profile="full")._tool_manager._tools[
        "pubtator.find_related_evidence_candidates"
    ]

    assert "pmid" in tool.parameters["properties"]
    assert "request" not in tool.parameters["properties"]
    assert tool.output_schema["title"] == "RelatedEvidenceCandidatesResponse"
```

In `pubtator_link/mcp/profiles.py`, add `"pubtator.find_related_evidence_candidates"` to `LEAN_TOOLS`.

In `pubtator_link/mcp/catalog.py`, add:

```python
    "pubtator.find_related_evidence_candidates": ToolCatalogSupplement(
        category="publication",
        profiles=("lean", "full", "readonly"),
        stability="lean",
        do_not_use_for=("claim substitution", "clinical decision support"),
        example='{"pmid":"40562663","max_results":25,"prefer_full_text":true}',
        next_tools=("pubtator.get_publication_passages", "pubtator.index_review_evidence"),
    ),
```

- [ ] **Step 9: Run related evidence surface tests**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py::test_related_evidence_is_lean_full_and_readonly tests/unit/mcp/test_mcp_facade.py::test_related_evidence_tool_schema_is_flat -q
```

Expected: PASS.

- [ ] **Step 10: Regenerate catalog and commit**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: PASS and `docs/mcp-tool-catalog.md` contains `pubtator.find_related_evidence_candidates`.

Commit:

```bash
git add pubtator_link/services/related_evidence.py pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/publications.py pubtator_link/mcp/tools/publications.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/profiles.py pubtator_link/mcp/catalog.py docs/mcp-tool-catalog.md tests/unit/test_related_evidence_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add related evidence candidates"
```

---

### Task 6: Topic Literature Map Service And Surface

**Files:**
- Create: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/api/routes/publications.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/profiles.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Modify: `tests/test_routes/test_publication_literature_graph.py`
- Create: `tests/unit/test_topic_literature_map_service.py`
- Modify: `tests/unit/mcp/test_mcp_profiles.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Regenerate: `docs/mcp-tool-catalog.md`

- [ ] **Step 1: Write topic map service tests**

Create `tests/unit/test_topic_literature_map_service.py`:

```python
import pytest

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteraturePaper,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesResponse,
    TopicLiteratureMapRequest,
)
from pubtator_link.services.topic_literature_map import TopicLiteratureMapService


class FakeSearchClient:
    async def search_publications(self, text, page=1, sort=None):
        return {"results": [{"pmid": "111"}, {"pmid": "222"}]}


class FakeMetadata:
    async def get_metadata(self, request):
        class Metadata:
            def __init__(self, pmid, year, authors, pmcid=None):
                self.pmid = pmid
                self.title = f"Paper {pmid}"
                self.doi = None
                self.pmcid = pmcid
                self.journal = "Journal"
                self.pub_year = year
                self.publication_types = ["Review"]
                self.authors = authors

        class Author:
            def __init__(self, display_name):
                self.display_name = display_name

        class Response:
            metadata = [
                Metadata("111", 2024, [Author("Ada Example")], "PMC111"),
                Metadata("222", 2023, [Author("Ada Example")]),
                Metadata("333", 2022, [Author("Bea Example")], "PMC333"),
            ]
            failed_pmids = {}

        return Response()


class FakeCitationGraph:
    async def get_citation_graph(self, request):
        return PublicationCitationGraphResponse(
            source=LiteraturePaper(pmid=request.pmid),
            references=[LiteraturePaper(pmid="333", title="Paper 333")],
            candidate_pmids=["333"],
        )


class FakeRelatedEvidence:
    async def find_candidates(self, request):
        return RelatedEvidenceCandidatesResponse(
            source=LiteraturePaper(pmid=request.pmid),
            candidates=[
                RelatedEvidenceCandidate(
                    paper=LiteraturePaper(
                        pmid="333",
                        title="Paper 333",
                        year=2022,
                        availability=LiteratureAvailability(has_pmc_full_text=True),
                    ),
                    pubmed_neighbor_score=800,
                    match_reasons=["pubmed_neighbor_score"],
                )
            ],
            candidate_pmids=["333"],
        )


@pytest.mark.asyncio
async def test_topic_map_builds_nodes_edges_summary_and_hints() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(query="familial mediterranean fever", max_seed_papers=2, max_neighbors_per_paper=2)
    )

    assert response.seed_pmids == ["111", "222"]
    assert {node.node_type for node in response.nodes} >= {"paper", "author"}
    assert {edge.edge_type for edge in response.edges} >= {"authored_by", "cites", "related_by_elink"}
    assert response.summary.central_papers[0].pmid == "111"
    assert response.summary.recommended_next_pmids
    assert response.candidate_retrieval_hints[0]["tool"] == "pubtator.get_publication_passages"


@pytest.mark.asyncio
async def test_topic_map_respects_explicit_seed_pmids_and_bounds() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
        related_evidence_service=FakeRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(pmids=["111", "222", "333"], max_seed_papers=1, max_neighbors_per_paper=1)
    )

    assert response.seed_pmids == ["111"]
    assert len([edge for edge in response.edges if edge.edge_type in {"cites", "related_by_elink"}]) <= 2
```

- [ ] **Step 2: Run topic map tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.services.topic_literature_map'`.

- [ ] **Step 3: Implement topic map service**

Create `pubtator_link/services/topic_literature_map.py`:

```python
from __future__ import annotations

from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteraturePaper,
    PublicationCitationGraphRequest,
    RelatedEvidenceCandidatesRequest,
    TopicLiteratureMapRequest,
    TopicLiteratureMapResponse,
    TopicLiteratureMapSummary,
    dedupe_edges,
    dedupe_papers,
)
from pubtator_link.models.publication_metadata import PublicationMetadataRequest


class TopicLiteratureMapService:
    def __init__(
        self,
        *,
        search_client: object,
        metadata_service: object,
        citation_graph_service: object,
        related_evidence_service: object,
    ) -> None:
        self.search_client = search_client
        self.metadata_service = metadata_service
        self.citation_graph_service = citation_graph_service
        self.related_evidence_service = related_evidence_service

    async def build_map(self, request: TopicLiteratureMapRequest) -> TopicLiteratureMapResponse:
        seed_pmids = await self._seed_pmids(request)
        seed_pmids = seed_pmids[: request.max_seed_papers]
        seed_papers = await self._metadata_papers(seed_pmids)
        all_papers = list(seed_papers)
        edges: list[LiteratureGraphEdge] = []

        if request.include_authors:
            edges.extend(_author_edges(seed_papers))

        for seed in seed_papers:
            neighbor_count = 0
            if request.include_citations and seed.pmid and neighbor_count < request.max_neighbors_per_paper:
                graph = await self.citation_graph_service.get_citation_graph(
                    PublicationCitationGraphRequest(pmid=seed.pmid, direction="both", max_results=request.max_neighbors_per_paper)
                )
                for paper in [*graph.references, *graph.cited_by][: request.max_neighbors_per_paper - neighbor_count]:
                    all_papers.append(paper)
                    edges.append(
                        LiteratureGraphEdge(
                            source=seed.key,
                            target=paper.key,
                            edge_type="cites",
                            reasons=["citation_neighbor"],
                            provenance=[LiteratureGraphProvenance(provider="citation_graph", source_id=seed.pmid)],
                        )
                    )
                    neighbor_count += 1
            if request.include_related_candidates and seed.pmid and neighbor_count < request.max_neighbors_per_paper:
                related = await self.related_evidence_service.find_candidates(
                    RelatedEvidenceCandidatesRequest(
                        pmid=seed.pmid,
                        max_results=request.max_neighbors_per_paper - neighbor_count,
                        prefer_full_text=request.prefer_full_text,
                        include_pubtator_search=False,
                        include_citation_neighbors=False,
                    )
                )
                for candidate in related.candidates:
                    all_papers.append(candidate.paper)
                    edges.append(
                        LiteratureGraphEdge(
                            source=seed.key,
                            target=candidate.paper.key,
                            edge_type="related_by_elink",
                            weight=float(candidate.pubmed_neighbor_score or 1),
                            reasons=candidate.match_reasons,
                            provenance=[LiteratureGraphProvenance(provider="ncbi_elink", source_id=seed.pmid)],
                        )
                    )

        papers = dedupe_papers(all_papers)
        nodes = _nodes_from_papers(papers)
        nodes.extend(_author_nodes(papers) if request.include_authors else [])
        edges = dedupe_edges(edges)
        central = _central_papers(papers, edges)
        recommended = [paper.pmid for paper in papers if paper.pmid and (paper.availability.has_pmc_full_text or paper.availability.is_open_access)]
        summary = TopicLiteratureMapSummary(
            central_papers=central[:5],
            recent_connected_papers=sorted(papers, key=lambda paper: (-(paper.year or 0), paper.key))[:5],
            bridge_papers=central[:5],
            dominant_author_groups=_dominant_authors(papers),
            accessible_full_text_candidates=[paper for paper in papers if paper.availability.has_pmc_full_text or paper.availability.is_open_access][:10],
            closed_central_sources=[paper for paper in central if not (paper.availability.has_pmc_full_text or paper.availability.is_open_access)][:5],
            recommended_next_pmids=recommended[:10],
        )
        return TopicLiteratureMapResponse(
            query=request.query,
            seed_pmids=seed_pmids,
            nodes=nodes,
            edges=edges,
            summary=summary,
            candidate_retrieval_hints=[{"tool": "pubtator.get_publication_passages", "arguments": {"pmids": recommended[:10]}}] if recommended else [],
        )

    async def _seed_pmids(self, request: TopicLiteratureMapRequest) -> list[str]:
        seeds = list(request.pmids or [])
        if request.query:
            raw = await self.search_client.search_publications(text=request.query, page=1, sort=None)
            results = raw.get("results", []) if isinstance(raw, dict) else []
            for item in results:
                if isinstance(item, dict) and item.get("pmid"):
                    seeds.append(str(item["pmid"]))
        return list(dict.fromkeys(seeds))

    async def _metadata_papers(self, pmids: list[str]) -> list[LiteraturePaper]:
        if not pmids:
            return []
        response = await self.metadata_service.get_metadata(
            PublicationMetadataRequest(
                pmids=pmids,
                include_mesh=False,
                include_publication_types=True,
                include_citations="none",
                include_coverage=True,
            )
        )
        papers: list[LiteraturePaper] = []
        for item in response.metadata:
            authors = [LiteratureAuthor(name=author.display_name) for author in item.authors if author.display_name]
            papers.append(
                LiteraturePaper(
                    pmid=item.pmid,
                    doi=item.doi,
                    pmcid=item.pmcid,
                    title=item.title,
                    journal=item.journal,
                    year=item.pub_year,
                    publication_types=item.publication_types,
                    authors=authors,
                )
            )
        return papers


def _nodes_from_papers(papers: list[LiteraturePaper]) -> list[LiteratureGraphNode]:
    return [LiteratureGraphNode(node_type="paper", paper=paper) for paper in papers]


def _author_nodes(papers: list[LiteraturePaper]) -> list[LiteratureGraphNode]:
    authors: dict[str, LiteratureAuthor] = {}
    for paper in papers:
        for author in paper.authors:
            authors.setdefault(author.key, author)
    return [LiteratureGraphNode(node_type="author", author=author) for author in authors.values()]


def _author_edges(papers: list[LiteraturePaper]) -> list[LiteratureGraphEdge]:
    edges: list[LiteratureGraphEdge] = []
    for paper in papers:
        for author in paper.authors:
            edges.append(
                LiteratureGraphEdge(
                    source=paper.key,
                    target=author.key,
                    edge_type="authored_by",
                    reasons=["metadata_author"],
                    provenance=[LiteratureGraphProvenance(provider="pubmed_metadata", source_id=paper.pmid)],
                )
            )
    return edges


def _central_papers(papers: list[LiteraturePaper], edges: list[LiteratureGraphEdge]) -> list[LiteraturePaper]:
    degree: dict[str, int] = {}
    for edge in edges:
        degree[edge.source] = degree.get(edge.source, 0) + 1
        degree[edge.target] = degree.get(edge.target, 0) + 1
    return sorted(papers, key=lambda paper: (-degree.get(paper.key, 0), -(paper.year or 0), paper.key))


def _dominant_authors(papers: list[LiteraturePaper]) -> list[str]:
    counts: dict[str, int] = {}
    for paper in papers:
        for author in paper.authors:
            counts[author.name] = counts.get(author.name, 0) + 1
    return [name for name, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10]]
```

- [ ] **Step 4: Run topic map service tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Add REST dependency and route**

In `pubtator_link/api/routes/dependencies.py`, add `get_topic_literature_map_service()` and alias:

```python
TopicLiteratureMapServiceDep = Annotated[TopicLiteratureMapService, Depends(get_topic_literature_map_service)]
```

Use a search adapter that wraps `resources.api_client.search_publications` or `await get_api_client()`.

Also add `_topic_literature_map_service` to `cleanup_dependencies` globals and set it to `None` during cleanup.

In `pubtator_link/api/routes/publications.py`, add:

```python
@router.post(
    "/topic-literature-map",
    response_model=TopicLiteratureMapResponse,
    operation_id="build_topic_literature_map",
    summary="Build topic literature map",
)
@handle_api_errors
async def build_topic_literature_map(
    request: TopicLiteratureMapRequest,
    service: TopicLiteratureMapServiceDep,
) -> TopicLiteratureMapResponse:
    """Return a bounded metadata-first topic literature graph and summary."""
    return await service.build_map(request)
```

- [ ] **Step 6: Add route tests**

Append to `tests/test_routes/test_publication_literature_graph.py`:

```python
from pubtator_link.api.routes.dependencies import get_topic_literature_map_service
from pubtator_link.models.literature_graph import (
    TopicLiteratureMapResponse,
    TopicLiteratureMapSummary,
)


@pytest.mark.asyncio
async def test_topic_literature_map_route_returns_graph() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.build_map.return_value = TopicLiteratureMapResponse(
        query="FMF",
        seed_pmids=["111"],
        summary=TopicLiteratureMapSummary(recommended_next_pmids=["111"]),
    )
    app.dependency_overrides[get_topic_literature_map_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/publications/topic-literature-map",
            json={"query": "FMF", "max_seed_papers": 10, "max_neighbors_per_paper": 5},
        )

    assert response.status_code == 200
    assert response.json()["seed_pmids"] == ["111"]


@pytest.mark.asyncio
async def test_topic_literature_map_route_requires_query_or_pmids() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    app.dependency_overrides[get_topic_literature_map_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/publications/topic-literature-map", json={})

    assert response.status_code == 422
    service.build_map.assert_not_called()
```

- [ ] **Step 7: Add MCP adapter and tool**

In `pubtator_link/mcp/service_adapters.py`, add:

```python
async def build_topic_literature_map_impl(
    *,
    service: Any,
    query: str | None = None,
    pmids: list[str] | None = None,
    max_seed_papers: int = 25,
    max_neighbors_per_paper: int = 10,
    include_authors: bool = True,
    include_citations: bool = True,
    include_pubtator_entities: bool = True,
    include_related_candidates: bool = True,
    year_min: int | None = None,
    year_max: int | None = None,
    prefer_full_text: bool = True,
) -> dict[str, Any]:
    response = await service.build_map(
        TopicLiteratureMapRequest(
            query=query,
            pmids=pmids,
            max_seed_papers=max_seed_papers,
            max_neighbors_per_paper=max_neighbors_per_paper,
            include_authors=include_authors,
            include_citations=include_citations,
            include_pubtator_entities=include_pubtator_entities,
            include_related_candidates=include_related_candidates,
            year_min=year_min,
            year_max=year_max,
            prefer_full_text=prefer_full_text,
        )
    )
    return response.model_dump(by_alias=True)
```

In `pubtator_link/mcp/tools/publications.py`, add this tool only when `profile == "full"`:

```python
    if profile == "full":

        @mcp.tool(
            name="pubtator.build_topic_literature_map",
            title="Build Topic Literature Map",
            output_schema=TopicLiteratureMapResponse.model_json_schema(),
            annotations=READ_ONLY_OPEN_WORLD,
        )
        async def build_topic_literature_map(
            query: Annotated[str | None, Field(default=None, max_length=1000)] = None,
            pmids: Annotated[list[str] | None, Field(default=None, max_length=100)] = None,
            max_seed_papers: Annotated[int, Field(ge=1, le=50)] = 25,
            max_neighbors_per_paper: Annotated[int, Field(ge=1, le=20)] = 10,
            include_authors: bool = True,
            include_citations: bool = True,
            include_pubtator_entities: bool = True,
            include_related_candidates: bool = True,
            year_min: int | None = None,
            year_max: int | None = None,
            prefer_full_text: bool = True,
        ) -> dict[str, Any]:
            """Use this when a user needs a bounded topic-level literature graph to choose papers for later passage review."""

            async def call() -> dict[str, Any]:
                service = await get_topic_literature_map_service()
                return await build_topic_literature_map_impl(
                    service=service,
                    query=query,
                    pmids=pmids,
                    max_seed_papers=max_seed_papers,
                    max_neighbors_per_paper=max_neighbors_per_paper,
                    include_authors=include_authors,
                    include_citations=include_citations,
                    include_pubtator_entities=include_pubtator_entities,
                    include_related_candidates=include_related_candidates,
                    year_min=year_min,
                    year_max=year_max,
                    prefer_full_text=prefer_full_text,
                )

            return await run_mcp_tool("pubtator.build_topic_literature_map", call, pmids=pmids)
```

- [ ] **Step 8: Add MCP tests and profile/catalog entries**

Append to `tests/unit/mcp/test_mcp_profiles.py`:

```python
def test_topic_literature_map_is_full_only() -> None:
    assert "pubtator.build_topic_literature_map" not in _tool_names("lean")
    assert "pubtator.build_topic_literature_map" in _tool_names("full")
    assert "pubtator.build_topic_literature_map" not in _tool_names("readonly")
```

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_topic_literature_map_tool_schema_is_flat() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp(profile="full")._tool_manager._tools[
        "pubtator.build_topic_literature_map"
    ]

    assert "query" in tool.parameters["properties"]
    assert "pmids" in tool.parameters["properties"]
    assert "request" not in tool.parameters["properties"]
    assert tool.output_schema["title"] == "TopicLiteratureMapResponse"
```

In `pubtator_link/mcp/profiles.py`, add `"pubtator.build_topic_literature_map"` to `FULL_ONLY_TOOLS`.

In `pubtator_link/mcp/catalog.py`, add:

```python
    "pubtator.build_topic_literature_map": ToolCatalogSupplement(
        category="publication",
        profiles=("full",),
        stability="advanced",
        do_not_use_for=("claim-level inference", "large recursive citation crawling"),
        example='{"query":"familial mediterranean fever colchicine","max_seed_papers":25,"max_neighbors_per_paper":10}',
        next_tools=("pubtator.get_publication_passages", "pubtator.index_review_evidence"),
    ),
```

- [ ] **Step 9: Run topic map surface tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py::test_topic_literature_map_is_full_only tests/unit/mcp/test_mcp_facade.py::test_topic_literature_map_tool_schema_is_flat -q
```

Expected: PASS.

- [ ] **Step 10: Regenerate catalog and commit**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: PASS and `docs/mcp-tool-catalog.md` contains `pubtator.build_topic_literature_map`.

Commit:

```bash
git add pubtator_link/services/topic_literature_map.py pubtator_link/api/routes/dependencies.py pubtator_link/api/routes/publications.py pubtator_link/mcp/tools/publications.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/profiles.py pubtator_link/mcp/catalog.py docs/mcp-tool-catalog.md tests/unit/test_topic_literature_map_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add topic literature map"
```

---

### Task 7: Documentation And Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/mcp-tool-catalog.md`
- Test: full repository checks

- [ ] **Step 1: Update README MCP tool table**

In `README.md`, add these rows near the existing publication/discovery MCP tools:

```markdown
| `pubtator.get_publication_citation_graph` | Explore references and cited-by neighbors for one PMID or DOI |
| `pubtator.find_related_evidence_candidates` | Find transparent related evidence candidates for one seed PMID |
| `pubtator.build_topic_literature_map` | Build a bounded topic graph across papers, authors, citations, and entities |
```

Add this caution sentence in the MCP section:

```markdown
Literature graph tools are candidate-discovery aids: graph relatedness does not imply claim support, and passage-level review is still required for grounded biomedical conclusions.
```

- [ ] **Step 2: Regenerate catalog**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
```

Expected: `docs/mcp-tool-catalog.md` is regenerated without errors.

- [ ] **Step 3: Run focused test suite**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py tests/unit/test_literature_providers.py tests/unit/test_citation_graph_service.py tests/unit/test_related_evidence_service.py tests/unit/test_topic_literature_map_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: PASS.

- [ ] **Step 4: Run formatting and linting**

Run:

```bash
make format
make lint
```

Expected: PASS. If Ruff formats files, inspect `git diff` and keep only intended changes.

- [ ] **Step 5: Run full local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

- [ ] **Step 6: Commit docs and verification updates**

```bash
git add README.md docs/mcp-tool-catalog.md
git commit -m "docs: document literature graph tools"
```

If `make format` changed Python files after the previous task commits, include those exact files in the commit with the README and catalog only if they are formatting-only changes from this epic.

---

## Self-Review Checklist

Spec coverage:

- Citation graph primitive: Tasks 1, 2, 3, and 4 cover models, provider parsing, service behavior, REST, MCP, catalog, and tests.
- Related evidence primitive: Tasks 2 and 5 cover ELink neighbor scores, deterministic ranking, provider warnings, route, MCP, catalog, and tests.
- Topic literature map orchestrator: Task 6 covers bounded seed expansion, graph nodes/edges, author edges, centrality, summary, retrieval hints, route, MCP full-only profile, catalog, and tests.
- Provider requirements: Task 2 covers Crossref/OpenAlex polite-pool settings and Unpaywall email gating.
- Testing scope: Tasks use mocked fixtures and explicitly do not require live network or VCR tests.
- Hosted safety: Model bounds in Task 1 and MCP bounds in Tasks 4 through 6 enforce the spec caps.
- Final verification: Task 7 requires focused tests, formatting/linting, and `make ci-local`.

Plan hygiene:

- Every planned file has at least one task that creates or modifies it.
- Every new MCP tool has profile, facade, catalog, and generated docs coverage.

Type consistency:

- Request and response class names match across models, routes, MCP adapters, and tests.
- Service method names are stable: `get_citation_graph`, `find_candidates`, `build_map`.
- Tool names are stable: `pubtator.get_publication_citation_graph`, `pubtator.find_related_evidence_candidates`, `pubtator.build_topic_literature_map`.

## Execution Options

After this plan is approved, use one of:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task and review between tasks.
2. **Inline Execution** - Execute tasks in this session with checkpoints.
