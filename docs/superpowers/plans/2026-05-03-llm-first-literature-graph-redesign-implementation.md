# LLM-First Literature Graph Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `build_topic_literature_map`, `get_publication_citation_graph`, and `find_related_evidence_candidates` compact, ranked, provider-transparent, and directly usable by LLMs.

**Architecture:** Add shared compact graph models and serialization helpers, then migrate citation graph, topic map, and related evidence services in separate TDD slices. Preserve current `full` response shape for REST and legacy clients while adding explicit compact and nodes/edges modes for MCP and LLM use.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, pytest, Ruff, mypy, uv/Makefile.

---

## File Structure

- Modify: `pubtator_link/models/literature_graph.py`
  - Add response-mode literals, provider status, query relevance, candidate summary, compact metadata, and mode-specific response fields.
- Create: `pubtator_link/services/literature_graph_compact.py`
  - Shared helpers for access summaries, response size classes, warning coalescing, deterministic compact budget metadata, candidate summaries, intent parsing, and demotion vocabulary.
- Create: `pubtator_link/services/literature_identifier_resolution.py`
  - Batched DOI-to-PMID resolver with in-memory positive/negative cache and provider status accounting.
- Modify: `pubtator_link/services/citation_graph.py`
  - Add provider statuses, DOI batch resolution, compact/nodes_edges shaping, candidate summaries, and coalesced warnings.
- Modify: `pubtator_link/services/topic_literature_map.py`
  - Add query-aware ranking, demotions, compact response, nodes_edges response, and compact summary.
- Modify: `pubtator_link/services/related_evidence.py`
  - Add response mode passthrough and enriched stable match reasons.
- Modify: `pubtator_link/api/routes/publications.py`
  - Preserve REST default `full` through request model defaults and response models.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Pass response-mode arguments and implement staged MCP default handling when response mode is omitted.
- Modify: `pubtator_link/mcp/tools/publications.py`
  - Expose flat `response_mode`, budget, and ranking arguments; update tool descriptions to warn that `full` is large.
- Modify: `docs/mcp-tool-catalog.md`
  - Regenerate/update catalog after schemas change.
- Test: `tests/unit/test_literature_graph_models.py`
- Test: `tests/unit/test_literature_graph_compact.py`
- Test: `tests/unit/test_literature_identifier_resolution.py`
- Test: `tests/unit/test_citation_graph_service.py`
- Test: `tests/unit/test_topic_literature_map_service.py`
- Test: `tests/unit/test_related_evidence_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Test: `tests/test_routes/test_publication_literature_graph.py`

## Commit Plan

Use these commit messages exactly:

1. `feat: add compact literature graph models`
2. `feat: add citation graph compact mode`
3. `feat: batch resolve citation graph identifiers`
4. `feat: rank topic literature candidates`
5. `feat: add topic map compact mode`
6. `feat: enrich related evidence reasons`
7. `docs: update literature graph tool docs`

Run each task's focused tests before committing that task. Before final completion, run `make ci-local`.

---

### Task 1: Shared Compact Models And Helpers

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Create: `pubtator_link/services/literature_graph_compact.py`
- Test: `tests/unit/test_literature_graph_models.py`
- Test: `tests/unit/test_literature_graph_compact.py`

- [ ] **Step 1: Add failing model tests**

Append these tests to `tests/unit/test_literature_graph_models.py`:

```python
from pubtator_link.models.literature_graph import (
    LiteratureAvailability,
    LiteratureCandidateSummary,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureQueryRelevance,
)


def test_candidate_summary_access_flags_and_source_tool_vocab() -> None:
    candidate = LiteratureCandidateSummary(
        pmid="28386255",
        title="EULAR recommendations for familial Mediterranean fever",
        access="full_text",
        access_flags={
            "has_pmc_full_text": True,
            "is_open_access": True,
            "has_pdf": False,
        },
        relevance_to_query=LiteratureQueryRelevance(
            score=0.9,
            matched_terms=["familial mediterranean fever", "colchicine"],
            matched_intents=["guideline_intent", "treatment_intent"],
            reasons=["title_query_overlap", "guideline_or_consensus_match"],
        ),
        source_tools=["topic_search", "citation_graph"],
    )

    dumped = candidate.model_dump()
    assert dumped["access"] == "full_text"
    assert dumped["access_flags"]["has_pmc_full_text"] is True
    assert dumped["relevance_to_query"]["matched_intents"] == [
        "guideline_intent",
        "treatment_intent",
    ]
    assert dumped["source_tools"] == ["topic_search", "citation_graph"]


def test_provider_status_result_count_defaults_to_zero() -> None:
    status = LiteratureProviderStatus(
        provider="unpaywall",
        operation="open_access",
        status="disabled",
        message="UNPAYWALL_EMAIL is not configured.",
    )

    assert status.result_count == 0


def test_graph_response_meta_tracks_budget_cache_and_ranking() -> None:
    meta = LiteratureGraphResponseMeta(
        response_mode="compact",
        response_size_class="medium",
        truncated=True,
        omitted_counts={"reference_candidates": 3},
        budget_advice="Reduce max_results or request response_mode='full'.",
        cache_key="citation:40562663:compact",
        snapshot_date="2026-05-03",
        source_versions={"ranker": "topic_map_ranker_v1"},
        ranking_version="topic_map_ranker_v1",
    )

    assert meta.response_mode == "compact"
    assert meta.response_size_class == "medium"
    assert meta.omitted_counts == {"reference_candidates": 3}
```

Create `tests/unit/test_literature_graph_compact.py`:

```python
from __future__ import annotations

from pubtator_link.models.literature_graph import LiteratureAvailability, LiteraturePaper, ProviderWarning
from pubtator_link.services.literature_graph_compact import (
    access_flags,
    access_summary,
    coalesced_provider_warnings,
    intent_flags_for_query,
    response_size_class,
)


def test_access_summary_priority_prefers_full_text_over_open_access() -> None:
    paper = LiteraturePaper(
        pmid="1",
        availability=LiteratureAvailability(
            has_pmc_full_text=True,
            is_open_access=True,
            has_pdf=True,
        ),
    )

    assert access_summary(paper) == "full_text"
    assert access_flags(paper) == {
        "has_pmc_full_text": True,
        "is_open_access": True,
        "has_pdf": True,
    }


def test_response_size_class_thresholds() -> None:
    assert response_size_class(4096) == "small"
    assert response_size_class(4097) == "medium"
    assert response_size_class(12288) == "medium"
    assert response_size_class(12289) == "large"


def test_coalesces_repeated_provider_warnings() -> None:
    warnings = [
        ProviderWarning(provider="unpaywall", status="provider_disabled", message="missing email"),
        ProviderWarning(provider="unpaywall", status="provider_disabled", message="missing email"),
        ProviderWarning(provider="crossref", status="provider_failed", message="timeout", retryable=True),
    ]

    coalesced = coalesced_provider_warnings(warnings)

    assert len(coalesced) == 2
    assert coalesced[0].provider == "unpaywall"
    assert coalesced[0].message == "missing email (repeated 2 times)"
    assert coalesced[1].retryable is True


def test_intent_flags_are_normalized_and_plural_aware() -> None:
    flags = intent_flags_for_query(
        "Guidelines for Turkish children with MEFV VUS and colchicine resistance"
    )

    assert flags == {
        "guideline_intent",
        "pediatric_intent",
        "population_intent",
        "variant_intent",
        "treatment_intent",
    }
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py tests/unit/test_literature_graph_compact.py -q
```

Expected: fail with missing `LiteratureCandidateSummary`, `LiteratureGraphResponseMeta`, `LiteratureProviderStatus`, `LiteratureQueryRelevance`, and missing `pubtator_link.services.literature_graph_compact`.

- [ ] **Step 3: Add shared model types**

In `pubtator_link/models/literature_graph.py`, add the shared literals and models near the existing graph literals:

```python
LiteratureGraphResponseMode = Literal["compact", "nodes_edges", "full"]
LiteratureResponseSizeClass = Literal["small", "medium", "large"]
LiteratureCandidateAccess = Literal["full_text", "open_access", "metadata_only", "unresolved"]
LiteratureSourceTool = Literal[
    "topic_search",
    "citation_graph",
    "related_evidence",
    "doi_resolution",
    "metadata_backfill",
]
LiteratureProviderStatusValue = Literal[
    "not_requested",
    "skipped",
    "success",
    "empty",
    "partial",
    "failed",
    "disabled",
]
```

Add these Pydantic models after `ProviderWarning`:

```python
class LiteratureQueryRelevance(BaseModel):
    """Bounded query relevance signals for candidate ranking only."""

    score: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)
    matched_mesh: list[str] = Field(default_factory=list)
    matched_intents: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class LiteratureCandidateSummary(BaseModel):
    """Compact publication summary for LLM candidate triage."""

    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    access: LiteratureCandidateAccess
    access_flags: dict[str, bool] = Field(default_factory=dict)
    score: float | None = None
    relevance_to_query: LiteratureQueryRelevance | None = None
    rank_reasons: list[str] = Field(default_factory=list)
    demotion_reasons: list[str] = Field(default_factory=list)
    source_tools: list[LiteratureSourceTool] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)


class LiteratureProviderStatus(BaseModel):
    """Structured provider status for a graph direction or enrichment operation."""

    provider: str
    operation: str
    status: LiteratureProviderStatusValue
    result_count: int = 0
    retryable: bool = False
    message: str | None = None
```

Replace `LiteratureResponseMeta` with a subclass-compatible graph meta model:

```python
class LiteratureResponseMeta(BaseModel):
    """Transparent metadata for literature graph responses."""

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


class LiteratureGraphResponseMeta(LiteratureResponseMeta):
    """Mode, budget, cache, and ranking metadata for graph responses."""

    response_mode: LiteratureGraphResponseMode = "full"
    response_size_class: LiteratureResponseSizeClass = "small"
    truncated: bool = False
    omitted_counts: dict[str, int] = Field(default_factory=dict)
    budget_advice: str | None = None
    cache_key: str | None = None
    snapshot_date: str | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    ranking_version: str | None = None
    provider_status: list[LiteratureProviderStatus] = Field(default_factory=list)
```

At the bottom of the model file, update graph response `meta` fields to use `LiteratureGraphResponseMeta` while preserving alias `_meta`.

- [ ] **Step 4: Add compact helper module**

Create `pubtator_link/services/literature_graph_compact.py`:

```python
"""Shared compact serialization and ranking helpers for literature graph tools."""

from __future__ import annotations

import json
import unicodedata
from collections import Counter
from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureCandidateAccess,
    LiteratureCandidateSummary,
    LiteratureGraphResponseMode,
    LiteraturePaper,
    LiteratureQueryRelevance,
    LiteratureResponseSizeClass,
    LiteratureSourceTool,
    ProviderWarning,
)

COMPACT_BUDGET_BYTES = 12 * 1024
NODES_EDGES_BUDGET_BYTES = 40 * 1024
TOPIC_RANKING_VERSION = "topic_map_ranker_v1"

_INTENT_TERMS: dict[str, tuple[str, ...]] = {
    "guideline_intent": ("guideline", "recommendation", "consensus", "delphi"),
    "pediatric_intent": ("child", "children", "pediatric", "paediatric"),
    "population_intent": ("turkey", "turkish", "mediterranean", "ancestry"),
    "variant_intent": ("variant", "vus", "genotype", "phenotype", "penetrance"),
    "treatment_intent": ("colchicine", "treatment", "resistance", "management"),
}


def access_flags(paper: LiteraturePaper) -> dict[str, bool]:
    return {
        "has_pmc_full_text": bool(paper.availability.has_pmc_full_text or paper.pmcid),
        "is_open_access": bool(paper.availability.is_open_access),
        "has_pdf": bool(paper.availability.has_pdf),
    }


def access_summary(paper: LiteraturePaper) -> LiteratureCandidateAccess:
    flags = access_flags(paper)
    if flags["has_pmc_full_text"]:
        return "full_text"
    if flags["is_open_access"] or paper.availability.full_text_url:
        return "open_access"
    if paper.pmid or paper.doi or paper.title:
        return "metadata_only"
    return "unresolved"


def response_size_class(num_bytes: int) -> LiteratureResponseSizeClass:
    if num_bytes <= 4 * 1024:
        return "small"
    if num_bytes <= COMPACT_BUDGET_BYTES:
        return "medium"
    return "large"


def json_size_class(payload: dict[str, Any]) -> LiteratureResponseSizeClass:
    return response_size_class(len(json.dumps(payload, separators=(",", ":"), default=str)))


def coalesced_provider_warnings(warnings: Iterable[ProviderWarning]) -> list[ProviderWarning]:
    grouped: dict[tuple[str, str, str, bool], int] = Counter(
        (warning.provider, warning.status, warning.message, warning.retryable)
        for warning in warnings
    )
    return [
        ProviderWarning(
            provider=provider,
            status=status,
            retryable=retryable,
            message=message if count == 1 else f"{message} (repeated {count} times)",
        )
        for (provider, status, message, retryable), count in grouped.items()
    ]


def normalize_query_text(query: str | None) -> str:
    if not query:
        return ""
    return unicodedata.normalize("NFKC", query).casefold()


def intent_flags_for_query(query: str | None) -> set[str]:
    normalized = normalize_query_text(query)
    flags: set[str] = set()
    for flag, terms in _INTENT_TERMS.items():
        if any(term in normalized for term in terms):
            flags.add(flag)
    return flags


def candidate_summary(
    paper: LiteraturePaper,
    *,
    score: float | None = None,
    relevance_to_query: LiteratureQueryRelevance | None = None,
    rank_reasons: list[str] | None = None,
    demotion_reasons: list[str] | None = None,
    source_tools: list[LiteratureSourceTool] | None = None,
) -> LiteratureCandidateSummary:
    return LiteratureCandidateSummary(
        pmid=paper.pmid,
        doi=paper.doi,
        title=paper.title,
        journal=paper.journal,
        year=paper.year,
        publication_types=paper.publication_types,
        access=access_summary(paper),
        access_flags=access_flags(paper),
        score=score,
        relevance_to_query=relevance_to_query,
        rank_reasons=rank_reasons or [],
        demotion_reasons=demotion_reasons or [],
        source_tools=source_tools or [],
        next_actions=(
            [{"tool": "pubtator.get_publication_passages", "arguments": {"pmids": [paper.pmid]}}]
            if paper.pmid
            else []
        ),
    )
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py tests/unit/test_literature_graph_compact.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/literature_graph_compact.py tests/unit/test_literature_graph_models.py tests/unit/test_literature_graph_compact.py
git commit -m "feat: add compact literature graph models"
```

---

### Task 2: Citation Graph Compact Mode And Provider Status

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Test: `tests/unit/test_citation_graph_service.py`

- [ ] **Step 1: Add failing citation graph compact/status tests**

Append to `tests/unit/test_citation_graph_service.py`:

```python
class DisabledUnpaywall:
    async def get_oa_status(self, doi: str):
        from pubtator_link.models.literature_graph import ProviderWarning

        return ProviderWarning(
            provider="unpaywall",
            status="provider_disabled",
            retryable=False,
            message="UNPAYWALL_EMAIL is not configured.",
        )


@pytest.mark.asyncio
async def test_citation_graph_compact_returns_candidates_status_and_no_metadata_duplicates() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        openalex=FakeOpenAlex(),
        unpaywall=DisabledUnpaywall(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
            response_mode="compact",
        )
    )

    assert response.meta.response_mode == "compact"
    assert response.references == []
    assert response.cited_by == []
    assert response.metadata_only == []
    assert response.reference_candidates
    assert response.cited_by_candidates
    assert response.candidate_pmids == ["40600001"]
    assert any(status.operation == "references" for status in response.references_status)
    assert any(status.operation == "cited_by" for status in response.cited_by_status)
    assert len([s for s in response.open_access_status if s.provider == "unpaywall"]) == 1


@pytest.mark.asyncio
async def test_citation_graph_full_preserves_existing_arrays() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        europe_pmc=FakeEuropePmc(),
        discovery_service=ResolvingDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="both",
            response_mode="full",
        )
    )

    assert response.references
    assert response.cited_by
    assert response.meta.response_mode == "full"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py -q
```

Expected: fail because `PublicationCitationGraphRequest.response_mode`, response status fields, and candidate summary fields do not exist.

- [ ] **Step 3: Add citation graph response fields**

In `PublicationCitationGraphRequest`, add:

```python
    response_mode: LiteratureGraphResponseMode = "full"
    resolve_reference_pmids: bool = True
    max_reference_resolution: int = Field(default=20, ge=0, le=100)
    include_provider_status: bool = True
```

In `PublicationCitationGraphResponse`, add:

```python
    response_mode: LiteratureGraphResponseMode = "full"
    reference_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    cited_by_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    references_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    cited_by_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    identifier_resolution_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    open_access_status: list[LiteratureProviderStatus] = Field(default_factory=list)
```

- [ ] **Step 4: Implement provider statuses and compact shaping**

In `pubtator_link/services/citation_graph.py`:

- Import `LiteratureCandidateSummary`, `LiteratureGraphResponseMeta`, `LiteratureProviderStatus`, and `candidate_summary`.
- Track `references_status`, `cited_by_status`, `open_access_status`, and `identifier_resolution_status` lists.
- For a requested provider that returns records, append `status="success"` and `result_count=len(records)`.
- For a requested provider that returns no records, append `status="empty"` and `result_count=0`.
- For an excluded direction, append `status="not_requested"` and `result_count=0`.
- For source DOI without PMID where Europe PMC cited-by cannot run, append `status="skipped"`, `provider="europe_pmc"`, `operation="cited_by"`, `message="PMID required"`.
- When Unpaywall returns disabled warnings repeatedly, put one `LiteratureProviderStatus(provider="unpaywall", operation="open_access", status="disabled", result_count=0, message=...)` in `open_access_status`.
- Build compact candidates with:

```python
reference_candidates = [
    candidate_summary(
        paper,
        rank_reasons=["source_reference", *tuple(["has_pmid"] if paper.pmid else [])],
        demotion_reasons=[] if paper.pmid else ["doi_only_unresolved"],
        source_tools=["citation_graph"],
    )
    for paper in references
]
cited_by_candidates = [
    candidate_summary(
        paper,
        rank_reasons=["source_cited_by", *tuple(["has_pmid"] if paper.pmid else [])],
        demotion_reasons=[] if paper.pmid else ["doi_only_unresolved"],
        source_tools=["citation_graph"],
    )
    for paper in cited_by
]
```

An explicit list construction is also acceptable:

```python
reasons = ["source_reference"]
if paper.pmid:
    reasons.append("has_pmid")
```

For `response_mode == "compact"`:

- Set `references=[]`, `cited_by=[]`, and `metadata_only=[]`.
- Keep `reference_candidates`, `cited_by_candidates`, `candidate_pmids`, status fields, `_meta`, warnings, and next commands.

For `response_mode == "full"`:

- Preserve existing `references`, `cited_by`, and `metadata_only`.
- Add the new fields without removing old arrays.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py tests/unit/test_literature_graph_models.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/citation_graph.py tests/unit/test_citation_graph_service.py
git commit -m "feat: add citation graph compact mode"
```

---

### Task 3: Batched DOI-To-PMID Resolution

**Files:**
- Create: `pubtator_link/services/literature_identifier_resolution.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Test: `tests/unit/test_literature_identifier_resolution.py`
- Test: `tests/unit/test_citation_graph_service.py`

- [ ] **Step 1: Add failing resolver tests**

Create `tests/unit/test_literature_identifier_resolution.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link.models.discovery import ArticleIdConversionRecord
from pubtator_link.services.literature_identifier_resolution import DoiPmidResolver


class RecordingDiscovery:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append((ids, source))
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1000/a",
                        input_kind="doi",
                        status="resolved",
                        pmid="100",
                        doi="10.1000/a",
                    ),
                    ArticleIdConversionRecord(
                        input_id="10.1000/b",
                        input_kind="doi",
                        status="not_found",
                        doi="10.1000/b",
                    ),
                ]
            },
        )()


@pytest.mark.asyncio
async def test_resolver_batches_caches_positive_and_negative_results() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    first = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)
    second = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=20)

    assert first.resolved == {"10.1000/a": "100"}
    assert first.unresolved == {"10.1000/b"}
    assert second.resolved == {"10.1000/a": "100"}
    assert second.cached_count == 2
    assert discovery.calls == [(["10.1000/a", "10.1000/b"], "doi")]


@pytest.mark.asyncio
async def test_resolver_respects_max_ids_and_reports_skipped() -> None:
    discovery = RecordingDiscovery()
    resolver = DoiPmidResolver(discovery_service=discovery)

    result = await resolver.resolve(["10.1000/a", "10.1000/b"], max_ids=1)

    assert discovery.calls == [(["10.1000/a"], "doi")]
    assert result.skipped_count == 1
```

Append to `tests/unit/test_citation_graph_service.py`:

```python
class BatchResolvingDiscovery:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append(ids)
        return type(
            "ArticleIdConversionResponse",
            (),
            {
                "records": [
                    ArticleIdConversionRecord(
                        input_id="10.1000/primary-study",
                        input_kind="doi",
                        status="resolved",
                        pmid="30000001",
                        doi="10.1000/primary-study",
                    )
                ]
            },
        )()


@pytest.mark.asyncio
async def test_citation_graph_batches_reference_doi_resolution() -> None:
    discovery = BatchResolvingDiscovery()
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=discovery,
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
            resolve_reference_pmids=True,
            max_reference_resolution=20,
        )
    )

    assert discovery.calls == [["10.1016/j.ard.2025.05.020"], ["10.1000/primary-study"]]
    assert response.reference_candidates[0].pmid == "30000001"
    assert "resolved_pmid_from_doi" in response.reference_candidates[0].rank_reasons
    assert any(status.operation == "doi_to_pmid" for status in response.identifier_resolution_status)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_literature_identifier_resolution.py tests/unit/test_citation_graph_service.py -q
```

Expected: fail because `DoiPmidResolver` does not exist and citation graph only resolves the source DOI one-at-a-time.

- [ ] **Step 3: Implement resolver**

Create `pubtator_link/services/literature_identifier_resolution.py`:

```python
"""Batched DOI-to-PMID resolution for literature graph providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DoiResolutionResult:
    resolved: dict[str, str] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)
    skipped_count: int = 0
    cached_count: int = 0
    failed_count: int = 0
    timeout_count: int = 0


class DoiPmidResolver:
    """Resolve DOI identifiers to PMIDs using a bounded batched discovery service."""

    def __init__(self, *, discovery_service: Any | None) -> None:
        self.discovery_service = discovery_service
        self._positive_cache: dict[str, str] = {}
        self._negative_cache: set[str] = set()

    async def resolve(self, dois: list[str], *, max_ids: int) -> DoiResolutionResult:
        result = DoiResolutionResult()
        normalized = _dedupe_dois(dois)
        bounded = normalized[:max_ids]
        result.skipped_count = max(0, len(normalized) - len(bounded))

        missing: list[str] = []
        for doi in bounded:
            if doi in self._positive_cache:
                result.resolved[doi] = self._positive_cache[doi]
                result.cached_count += 1
            elif doi in self._negative_cache:
                result.unresolved.add(doi)
                result.cached_count += 1
            else:
                missing.append(doi)

        if not missing or self.discovery_service is None:
            result.unresolved.update(missing)
            return result

        try:
            records = await self.discovery_service.convert_article_ids(missing, source="doi")
        except TimeoutError:
            result.timeout_count += len(missing)
            result.unresolved.update(missing)
            return result
        except Exception:
            result.failed_count += len(missing)
            result.unresolved.update(missing)
            return result

        raw_records = getattr(records, "records", records)
        resolved_inputs: set[str] = set()
        for record in raw_records:
            input_id = str(getattr(record, "input_id", "") or "").casefold()
            pmid = getattr(record, "pmid", None)
            if input_id and pmid:
                result.resolved[input_id] = str(pmid)
                self._positive_cache[input_id] = str(pmid)
                resolved_inputs.add(input_id)

        for doi in missing:
            if doi not in resolved_inputs:
                result.unresolved.add(doi)
                self._negative_cache.add(doi)
        return result


def _dedupe_dois(dois: list[str]) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for doi in dois:
        normalized = doi.strip().removeprefix("doi:").casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            values.append(normalized)
    return values
```

- [ ] **Step 4: Wire resolver into citation graph**

In `CitationGraphService.__init__`, create:

```python
from pubtator_link.services.literature_identifier_resolution import DoiPmidResolver

self.doi_resolver = DoiPmidResolver(discovery_service=discovery_service)
```

After references/cited_by are collected and deduped, before candidate summaries, add:

```python
if request.resolve_reference_pmids and request.max_reference_resolution > 0:
    references, reference_resolution_status = await self._resolve_neighbor_dois(
        papers=references,
        max_ids=request.max_reference_resolution,
    )
    cited_by, cited_by_resolution_status = await self._resolve_neighbor_dois(
        papers=cited_by,
        max_ids=max(0, request.max_reference_resolution - len(reference_resolution_status.resolved)),
    )
```

Implement `_resolve_neighbor_dois` so DOI-only papers that resolve get `pmid` merged and the compact candidate later receives `resolved_pmid_from_doi`; unresolved DOI-only papers receive `doi_only_unresolved`. Convert `DoiResolutionResult` to one `LiteratureProviderStatus(provider="ncbi_idconv", operation="doi_to_pmid", status=..., result_count=resolved_count, message="resolved=X unresolved=Y cached=Z skipped=W failed=V timeout=U")`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_literature_identifier_resolution.py tests/unit/test_citation_graph_service.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/literature_identifier_resolution.py pubtator_link/services/citation_graph.py tests/unit/test_literature_identifier_resolution.py tests/unit/test_citation_graph_service.py
git commit -m "feat: batch resolve citation graph identifiers"
```

---

### Task 4: Topic Literature Candidate Ranking

**Files:**
- Modify: `pubtator_link/services/literature_graph_compact.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Test: `tests/unit/test_topic_literature_map_service.py`

- [ ] **Step 1: Add failing ranking and golden PMID tests**

Append to `tests/unit/test_topic_literature_map_service.py`:

```python
from pubtator_link.services.topic_literature_map import rank_topic_candidates


def test_topic_ranker_promotes_guideline_and_pediatric_colchicine_records() -> None:
    papers = [
        LiteraturePaper(
            pmid="33778981",
            title="Veterinary clinical pathology annual meeting abstracts",
            publication_types=["Congress"],
        ),
        LiteraturePaper(
            pmid="40616106",
            title="Behcet disease and trisomy 8 case report",
            publication_types=["Case Reports"],
        ),
        LiteraturePaper(
            pmid="28386255",
            title="EULAR recommendations for the management of familial Mediterranean fever",
            publication_types=["Guideline"],
            year=2016,
        ),
        LiteraturePaper(
            pmid="36680425",
            title="PREDICT-crFMF score in children with colchicine-resistant familial Mediterranean fever",
            publication_types=["Journal Article"],
            year=2023,
        ),
    ]

    ranked = rank_topic_candidates(
        papers,
        query="familial Mediterranean fever MEFV colchicine guideline Turkey child variant",
        seed_pmids=[],
        candidate_pmids=[paper.pmid for paper in papers if paper.pmid],
        accessible_pmids=[],
        bias_toward=["guideline", "pediatric"],
    )

    by_pmid = {candidate.pmid: candidate for candidate in ranked}
    assert [candidate.pmid for candidate in ranked[:3]] == ["28386255", "36680425", "33778981"]
    assert "conference_abstract_collection" in by_pmid["33778981"].demotion_reasons
    assert "low_query_overlap" in by_pmid["40616106"].demotion_reasons
    assert by_pmid["28386255"].relevance_to_query is not None
    assert "guideline_intent" in by_pmid["28386255"].relevance_to_query.matched_intents
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py::test_topic_ranker_promotes_guideline_and_pediatric_colchicine_records -q
```

Expected: fail because `rank_topic_candidates` does not exist.

- [ ] **Step 3: Implement deterministic ranking helpers**

In `pubtator_link/services/topic_literature_map.py`, add public helper `rank_topic_candidates` near the bottom:

```python
def rank_topic_candidates(
    papers: list[LiteraturePaper],
    *,
    query: str | None,
    seed_pmids: list[str],
    candidate_pmids: list[str],
    accessible_pmids: list[str],
    bias_toward: list[str] | None = None,
) -> list[LiteratureCandidateSummary]:
    intents = intent_flags_for_query(query)
    query_terms = _query_terms(query)
    seed_set = set(seed_pmids)
    candidate_set = set(candidate_pmids)
    accessible_set = set(accessible_pmids)
    ranked: list[LiteratureCandidateSummary] = []
    for paper in dedupe_papers(papers):
        score, rank_reasons, demotion_reasons, matched_terms = _topic_candidate_score(
            paper=paper,
            query_terms=query_terms,
            intents=intents,
            seed_set=seed_set,
            candidate_set=candidate_set,
            accessible_set=accessible_set,
            bias_toward=set(bias_toward or []),
        )
        relevance = LiteratureQueryRelevance(
            score=max(0.0, min(1.0, score / 20.0)),
            matched_terms=matched_terms[:8],
            matched_intents=sorted(intents),
            reasons=rank_reasons[:8],
        )
        ranked.append(
            candidate_summary(
                paper,
                score=score,
                relevance_to_query=relevance,
                rank_reasons=rank_reasons,
                demotion_reasons=demotion_reasons,
                source_tools=["topic_search"] if paper.pmid in seed_set else ["topic_search", "related_evidence"],
            )
        )
    return sorted(
        ranked,
        key=lambda candidate: (
            -float(candidate.score or 0),
            int("missing_pmid" in candidate.demotion_reasons),
            int("low_query_overlap" in candidate.demotion_reasons),
            candidate.year or 0,
            candidate.pmid or candidate.doi or candidate.title or "",
        ),
        reverse=False,
    )
```

Add `_topic_candidate_score`, `_query_terms`, `_publication_type_text`, and title/type demotion helpers. Use these exact demotion strings: `missing_pmid`, `doi_only_unresolved`, `conference_abstract_collection`, `supplement_collection`, `annual_review_collection`, `off_topic_title`, `low_query_overlap`, `metadata_only`. Treat title/type substrings `abstract`, `meeting`, `conference`, `congress`, `supplement`, `annual`, `veterinary`, `highlights`, and `trisomy 8` as demotion signals for this ranker.

- [ ] **Step 4: Run focused ranking test**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py::test_topic_ranker_promotes_guideline_and_pediatric_colchicine_records -q
```

Expected: pass.

- [ ] **Step 5: Run topic map service tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py tests/unit/test_literature_graph_compact.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/literature_graph_compact.py pubtator_link/services/topic_literature_map.py tests/unit/test_topic_literature_map_service.py
git commit -m "feat: rank topic literature candidates"
```

---

### Task 5: Topic Map Compact And Nodes/Edges Modes

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Test: `tests/unit/test_topic_literature_map_service.py`

- [ ] **Step 1: Add failing topic compact tests**

Append to `tests/unit/test_topic_literature_map_service.py`:

```python
@pytest.mark.asyncio
async def test_topic_map_compact_omits_topology_and_uses_pmid_indexes() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            response_mode="compact",
            max_candidates=3,
            max_demoted=1,
        )
    )

    assert response.meta.response_mode == "compact"
    assert response.nodes == []
    assert response.edges == []
    assert response.top_candidates
    assert response.summary.central_papers == []
    assert isinstance(response.accessible_full_text_pmids, list)
    assert isinstance(response.closed_central_pmids, list)
    assert len(response.demoted_candidate_pmids) <= 1
    assert response.recommended_next_pmids == [
        pmid for pmid in response.recommended_next_pmids if pmid
    ]


@pytest.mark.asyncio
async def test_topic_map_nodes_edges_mode_returns_bounded_topology_without_candidate_envelopes() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            pmids=["111", "222"],
            response_mode="nodes_edges",
            max_graph_nodes=2,
            max_graph_edges=1,
        )
    )

    assert response.meta.response_mode == "nodes_edges"
    assert len(response.nodes) <= 2
    assert len(response.edges) <= 1
    assert response.top_candidates == []
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py::test_topic_map_compact_omits_topology_and_uses_pmid_indexes tests/unit/test_topic_literature_map_service.py::test_topic_map_nodes_edges_mode_returns_bounded_topology_without_candidate_envelopes -q
```

Expected: fail because topic request/response mode fields do not exist and the service always returns full topology.

- [ ] **Step 3: Add topic request/response fields**

In `TopicLiteratureMapRequest`, add:

```python
    response_mode: LiteratureGraphResponseMode = "full"
    max_candidates: int = Field(default=12, ge=1, le=50)
    include_demoted: bool = True
    max_demoted: int = Field(default=3, ge=0, le=20)
    bias_toward: list[Literal["guideline", "cohort", "genotype_phenotype", "treatment", "pediatric", "population"]] | None = None
    max_graph_nodes: int = Field(default=30, ge=1, le=200)
    max_graph_edges: int = Field(default=60, ge=1, le=400)
```

In `TopicLiteratureMapResponse`, add:

```python
    response_mode: LiteratureGraphResponseMode = "full"
    top_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    recommended_next_pmids: list[str] = Field(default_factory=list)
    accessible_full_text_pmids: list[str] = Field(default_factory=list)
    closed_central_pmids: list[str] = Field(default_factory=list)
    demoted_candidate_pmids: list[str] = Field(default_factory=list)
    demoted_reasons_by_pmid: dict[str, list[str]] = Field(default_factory=dict)
    provider_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    omitted_counts: dict[str, int] = Field(default_factory=dict)
```

- [ ] **Step 4: Shape topic responses by mode**

In `TopicLiteratureMapService.build_map`, after `summary` and `hints` are computed:

- Build `ranked_candidates = rank_topic_candidates(...)`.
- Set `recommended_next_pmids` to PMID-bearing candidates not in `seed_pmids`, excluding `missing_pmid`, `doi_only_unresolved`, and `low_query_overlap` when there are stronger candidates.
- Set `accessible_full_text_pmids` and `closed_central_pmids` from candidate summaries, not repeated paper envelopes.
- Set `demoted_candidate_pmids` and `demoted_reasons_by_pmid` capped by `request.max_demoted`.
- For `compact`, return empty `nodes` and `edges`, empty full summary paper arrays, and `top_candidates=ranked_candidates[:request.max_candidates]`.
- For `nodes_edges`, return `nodes[:request.max_graph_nodes]`, `edges[:request.max_graph_edges]`, and no `top_candidates`.
- For `full`, preserve existing nodes/edges/summary and add the new compact fields.
- Put `_meta=LiteratureGraphResponseMeta(response_mode=request.response_mode, ranking_version=TOPIC_RANKING_VERSION, warnings=coalesced_provider_warnings(warnings), next_commands=_retrieval_hints(recommended_next_pmids), ...)`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/topic_literature_map.py tests/unit/test_topic_literature_map_service.py
git commit -m "feat: add topic map compact mode"
```

---

### Task 6: Related Evidence Response Mode And Enriched Reasons

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Test: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Add failing related evidence tests**

Append to `tests/unit/test_related_evidence_service.py`:

```python
class IntentMetadata:
    async def get_metadata(self, request):
        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid=pmid,
                    title="Pediatric colchicine resistance in familial Mediterranean fever",
                    pub_year=2024,
                    publication_types=["Guideline"],
                    coverage="full_text",
                    pmcid="PMC1",
                )
                for pmid in request.pmids
            ],
        )


@pytest.mark.asyncio
async def test_related_evidence_enriches_match_reasons_for_intents_and_access() -> None:
    service = RelatedEvidenceService(
        discovery_service=FakeDiscovery(),
        metadata_service=IntentMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="1",
            max_results=5,
            publication_types=["Guideline"],
            response_mode="compact",
        )
    )

    reasons = set(response.candidates[0].match_reasons)
    assert "pubmed_neighbor_score" in reasons
    assert "full_text_available" in reasons
    assert "shared_publication_type" in reasons
    assert "guideline_or_consensus_match" in reasons
    assert "pediatric_match" in reasons
    assert "treatment_match" in reasons
    assert response.meta.response_mode == "compact"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py::test_related_evidence_enriches_match_reasons_for_intents_and_access -q
```

Expected: fail because `response_mode` and enriched reason vocabulary do not exist.

- [ ] **Step 3: Add response mode and reason enrichment**

In `RelatedEvidenceCandidatesRequest`, add:

```python
    response_mode: LiteratureGraphResponseMode = "compact"
```

In `RelatedEvidenceService.find_candidates`, set `_meta=LiteratureGraphResponseMeta(response_mode=request.response_mode, warnings=..., next_commands=...)`.

Update `_match_reasons`:

```python
    if _has_full_text(paper):
        reasons.append("full_text_available")
    if paper.availability.is_open_access:
        reasons.append("open_access_available")
    if request.publication_types and _publication_type_matches(...):
        reasons.append("shared_publication_type")
    title_type_text = f"{paper.title or ''} {' '.join(paper.publication_types)}".casefold()
    if any(term in title_type_text for term in ("guideline", "recommendation", "consensus", "delphi")):
        reasons.append("guideline_or_consensus_match")
    if any(term in title_type_text for term in ("child", "children", "pediatric", "paediatric")):
        reasons.append("pediatric_match")
    if any(term in title_type_text for term in ("turkey", "turkish", "mediterranean")):
        reasons.append("population_match")
    if any(term in title_type_text for term in ("variant", "genotype", "phenotype", "penetrance")):
        reasons.append("variant_or_genotype_match")
    if any(term in title_type_text for term in ("colchicine", "treatment", "resistance", "management")):
        reasons.append("treatment_match")
    if request.year_min is not None or request.year_max is not None:
        reasons.append("year_window_match")
```

Keep `requested_publication_type` only if existing tests require it; otherwise replace it with `shared_publication_type`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_related_evidence_service.py tests/unit/test_literature_graph_models.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/related_evidence.py tests/unit/test_related_evidence_service.py
git commit -m "feat: enrich related evidence reasons"
```

---

### Task 7: MCP, Routes, Tool Schemas, And Documentation

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Modify: `tests/test_routes/test_publication_literature_graph.py`
- Modify: `docs/mcp-tool-catalog.md`

- [ ] **Step 1: Add failing route and MCP adapter tests**

Append to `tests/test_routes/test_publication_literature_graph.py`:

```python
@pytest.mark.asyncio
async def test_citation_graph_route_defaults_to_full_for_rest() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.get_citation_graph.return_value = PublicationCitationGraphResponse(
        source=LiteraturePaper(pmid="40562663"),
        response_mode="full",
    )
    app.dependency_overrides[get_citation_graph_service] = lambda: service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/publications/citation-graph",
            json={"pmid": "40562663"},
        )

    assert response.status_code == 200
    request = service.get_citation_graph.call_args.args[0]
    assert request.response_mode == "full"
```

Append to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
from pubtator_link.mcp.service_adapters import get_publication_citation_graph_impl
from pubtator_link.models.literature_graph import LiteraturePaper, PublicationCitationGraphResponse


async def test_citation_graph_adapter_accepts_compact_response_mode() -> None:
    class Service:
        async def get_citation_graph(self, request):
            assert request.response_mode == "compact"
            return PublicationCitationGraphResponse(source=LiteraturePaper(pmid="1"), response_mode="compact")

    result = await get_publication_citation_graph_impl(
        service=Service(),
        pmid="1",
        response_mode="compact",
    )

    assert result["response_mode"] == "compact"
```

Append to `tests/unit/mcp/test_mcp_tool_catalog.py`:

```python
def test_literature_graph_tools_expose_response_mode_and_size_guidance() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    for name in (
        "pubtator.get_publication_citation_graph",
        "pubtator.find_related_evidence_candidates",
        "pubtator.build_topic_literature_map",
    ):
        tool = catalog[name]
        assert "response_mode" in tool.input_schema["properties"]
        assert "response_size_class" in tool.description
        assert "full can be large" in tool.description
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: fail because adapters/tools do not accept response mode arguments and descriptions/catalog lack the new guidance.

- [ ] **Step 3: Update MCP adapter signatures**

In `pubtator_link/mcp/service_adapters.py`, update the three graph adapter functions to accept and pass:

```python
response_mode: Literal["compact", "nodes_edges", "full"] | None = None
```

For citation graph also pass:

```python
resolve_reference_pmids: bool = True
max_reference_resolution: int = 20
include_provider_status: bool = True
```

For topic map also pass:

```python
max_candidates: int = 12
include_demoted: bool = True
max_demoted: int = 3
bias_toward: list[Literal["guideline", "cohort", "genotype_phenotype", "treatment", "pediatric", "population"]] | None = None
max_graph_nodes: int = 30
max_graph_edges: int = 60
```

Staged MCP default rule for this release:

```python
effective_response_mode = response_mode or "full"
```

If `response_mode is None`, after `response.model_dump(by_alias=True)` add:

```python
result.setdefault("_meta", {}).setdefault("warnings", []).append(
    {
        "provider": "mcp",
        "status": "response_mode_deprecation",
        "retryable": False,
        "message": "Future MCP default will be response_mode='compact'; pass response_mode='full' for legacy nodes/edges arrays.",
    }
)
```

- [ ] **Step 4: Update MCP tool functions and descriptions**

In `pubtator_link/mcp/tools/publications.py`, add flat arguments to all three graph tools. Use `response_mode: Literal["compact", "nodes_edges", "full"] | None = None` for staged migration. Add the citation/topic budget arguments from Step 3.

Update docstrings so each includes:

```text
Returns response_size_class. response_mode='compact' is for LLM candidate selection; response_mode='full' can be large and is for legacy/debug graph inspection.
```

- [ ] **Step 5: Update existing route fakes for new fields**

Update the existing fake responses in `tests/test_routes/test_publication_literature_graph.py` so they include explicit response modes where the response model now exposes them:

```python
PublicationCitationGraphResponse(
    source=LiteraturePaper(pmid="40562663"),
    cited_by=[LiteraturePaper(pmid="40600001", title="Citing study")],
    candidate_pmids=["40600001"],
    response_mode="full",
)
```

```python
RelatedEvidenceCandidatesResponse(
    source=LiteraturePaper(pmid="111"),
    candidate_pmids=["222"],
)
```

```python
TopicLiteratureMapResponse(
    query="FMF",
    seed_pmids=["111"],
    summary=TopicLiteratureMapSummary(recommended_next_pmids=["111"]),
    response_mode="full",
)
```

- [ ] **Step 6: Regenerate or update MCP catalog**

Regenerate the checked-in catalog with the repository script:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
```

Confirm the rendered catalog includes these three graph tool updates:

- add `response_mode` argument enum.
- add citation DOI resolution args.
- add topic compact budget args.
- mention `response_size_class` and that `full` can be large.

- [ ] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

Run:

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/publications.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_tool_catalog.py docs/mcp-tool-catalog.md
git commit -m "docs: update literature graph tool docs"
```

---

## Final Verification

- [ ] **Step 1: Run focused graph suite**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_models.py tests/unit/test_literature_graph_compact.py tests/unit/test_literature_identifier_resolution.py tests/unit/test_citation_graph_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py tests/test_routes/test_publication_literature_graph.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: pass.

- [ ] **Step 2: Run local CI**

Run:

```bash
make ci-local
```

Expected: formatting, linting, type checking, and tests pass.

- [ ] **Step 3: Report exact verification result**

Report:

- commit hashes for each task commit.
- focused graph suite command and result.
- exact `make ci-local` result.
- any residual gaps, especially staged MCP default behavior if compact default is intentionally deferred for one release.

## Self-Review Checklist

- [ ] Spec coverage: shared response modes, compact serialization, provider status, publication envelope, citation compact, DOI resolution, topic ranking, topic compact/nodes_edges, related evidence reasons, MCP/tool docs, route defaults, and final CI are covered by tasks above.
- [ ] Placeholder scan: plan contains no placeholder markers or unspecified implementation placeholders.
- [ ] Type consistency: response mode values are `compact`, `nodes_edges`, `full`; ranking version is `topic_map_ranker_v1`; provider status values match the spec; demotion reasons use the approved vocabulary.
