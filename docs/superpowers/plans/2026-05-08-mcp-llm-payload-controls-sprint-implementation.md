# MCP LLM Payload Controls Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the first-sprint MCP payload controls compact-first, paginated, budgeted, and backward-compatible for explicit full/detail and numeric-budget callers.

**Architecture:** Keep REST and direct service behavior stable where compatibility matters, while changing MCP defaults to LLM-friendly compact responses. Add small shared helpers for graph provenance/budget metadata, inspect-index cursors, and review response budgets; keep service logic as the source of truth and adapters as thin normalization layers.

**Tech Stack:** Python 3.12, FastAPI/FastMCP, Pydantic v2, asyncpg/PostgreSQL, pytest, Ruff, mypy, existing Makefile targets.

---

## File Structure

- Create: `pubtator_link/services/review_context/budgets.py` - shared review retrieval budget and verbosity resolver.
- Create: `pubtator_link/services/review_context/pagination.py` - opaque inspect-index cursor encoding, decoding, and scope hashing.
- Create: `tests/unit/test_review_context_budgets.py` - resolver tests for auto and numeric budgets.
- Create: `tests/unit/test_review_context_pagination.py` - cursor contract tests.
- Modify: `pubtator_link/mcp/service_adapters.py` - graph MCP compact defaults, inspect cursor wiring, review budget resolution.
- Modify: `pubtator_link/mcp/tools/publications.py` - graph MCP schema defaults.
- Modify: `pubtator_link/mcp/tools/review.py` - inspect pagination args, review `verbosity`, review `max_response_chars="auto"`.
- Modify: `pubtator_link/mcp/input_normalization.py` - `verbosity` casing and `"auto"` budget normalization.
- Modify: `pubtator_link/models/literature_graph.py` - graph request signature metadata, compact serializers, and compact score fields.
- Modify: `pubtator_link/models/review_rerag.py` - inspect pagination fields, budget type aliases, verbosity field.
- Modify: `pubtator_link/services/literature_graph_compact.py` - graph JSON size, request signature, drill-down commands, and truncation helpers.
- Modify: `pubtator_link/services/citation_graph.py` - request signature metadata and compact budget enforcement.
- Modify: `pubtator_link/services/topic_literature_map.py` - request signature metadata, compact summary filtering, and budget enforcement.
- Modify: `pubtator_link/services/related_evidence.py` - request signature metadata, compact score semantics, and omitted candidate counts.
- Modify: `pubtator_link/services/review_context_service.py` - inspect pagination and shared budget resolver use.
- Modify: `pubtator_link/repositories/review_rerag.py` - source and failed-source `limit` / `offset` support.
- Modify: `pubtator_link/api/routes/reviews.py` - REST inspect pagination query params.
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py` - MCP adapter tests.
- Modify: `tests/unit/mcp/test_mcp_facade.py` - MCP schema/capability tests.
- Modify: `tests/unit/mcp/test_mcp_tool_catalog.py` - catalog default and guidance tests.
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py` - review tool schema tests.
- Modify: `tests/unit/mcp/test_mcp_input_normalization.py` - input normalization tests.
- Modify: `tests/unit/test_literature_graph_compact.py` - graph helper tests.
- Modify: `tests/unit/test_citation_graph_service.py` - citation compact/cache/budget tests.
- Modify: `tests/unit/test_topic_literature_map_service.py` - topic compact/cache/budget tests.
- Modify: `tests/unit/test_related_evidence_service.py` - related compact/cache/budget tests.
- Modify: `tests/unit/test_review_context_service.py` - inspect pagination and budget resolver tests.
- Modify: `tests/unit/test_review_rerag_repository.py` - repository pagination tests.
- Modify: `tests/test_routes/test_reviews.py` - REST inspect and batch budget route tests.
- Modify: `tests/test_routes/test_publication_literature_graph.py` - REST graph default compatibility tests.

## Task 1: Make Graph MCP Defaults Compact

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_mcp_tool_catalog.py`

- [ ] **Step 1: Write failing adapter tests**

Add tests to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_graph_adapters_default_omitted_response_mode_to_compact() -> None:
    from pubtator_link.mcp.service_adapters import (
        build_topic_literature_map_impl,
        find_related_evidence_candidates_impl,
        get_publication_citation_graph_impl,
    )
    from pubtator_link.models.literature_graph import (
        LiteraturePaper,
        PublicationCitationGraphResponse,
        RelatedEvidenceCandidatesResponse,
        TopicLiteratureMapResponse,
    )

    class CitationService:
        request = None

        async def get_citation_graph(self, request):
            self.request = request
            return PublicationCitationGraphResponse(
                source=LiteraturePaper(pmid="1"),
                response_mode=request.response_mode,
            )

    class RelatedService:
        request = None

        async def find_candidates(self, request):
            self.request = request
            return RelatedEvidenceCandidatesResponse(
                source=LiteraturePaper(pmid=request.pmid),
                meta={"response_mode": request.response_mode},
            )

    class TopicService:
        request = None

        async def build_map(self, request):
            self.request = request
            return TopicLiteratureMapResponse(
                query=request.query,
                response_mode=request.response_mode,
            )

    citation = CitationService()
    related = RelatedService()
    topic = TopicService()

    citation_result = await get_publication_citation_graph_impl(
        service=citation,
        pmid="1",
    )
    related_result = await find_related_evidence_candidates_impl(
        service=related,
        pmid="1",
    )
    topic_result = await build_topic_literature_map_impl(
        service=topic,
        query="FMF",
    )

    assert citation.request.response_mode == "compact"
    assert related.request.response_mode == "compact"
    assert topic.request.response_mode == "compact"
    assert citation_result["response_mode"] == "compact"
    assert related_result["_meta"]["response_mode"] == "compact"
    assert topic_result["response_mode"] == "compact"
    assert "response_mode_deprecation" not in str(citation_result)
    assert "response_mode_deprecation" not in str(related_result)
    assert "response_mode_deprecation" not in str(topic_result)
```

- [ ] **Step 2: Write failing schema tests**

Extend graph schema tests in `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_literature_graph_mcp_schemas_default_to_compact() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tools = create_pubtator_mcp(profile="full")._tool_manager._tools
    for name in (
        "get_publication_citation_graph",
        "find_related_evidence_candidates",
        "build_topic_literature_map",
    ):
        response_mode = tools[name].parameters["properties"]["response_mode"]
        assert response_mode["default"] == "compact"
        assert "full" in response_mode["enum"] or "full" in response_mode["anyOf"][0]["enum"]
```

Update `tests/unit/mcp/test_mcp_tool_catalog.py` so the catalog description asserts compact-first guidance:

```python
assert "response_mode='compact'" in tool.description
assert "full can be large" in tool.description
```

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py -q -k "graph or citation_graph or related_evidence or topic_literature_map"
```

Expected: FAIL because omitted graph response modes still become `"full"` and schemas expose nullable defaults.

- [ ] **Step 4: Change graph MCP adapter defaults**

In `pubtator_link/mcp/service_adapters.py`, update all three graph adapters:

```python
effective_response_mode = response_mode or "compact"
```

Remove calls that add the MCP response-mode deprecation warning after omitted defaults become compact:

```python
result = response.model_dump(by_alias=True)
return result
```

If `_add_mcp_response_mode_warning()` has no remaining call sites, delete the helper.

- [ ] **Step 5: Change graph MCP tool signatures and descriptions**

In `pubtator_link/mcp/tools/publications.py`, change each graph tool argument:

```python
response_mode: LiteratureGraphResponseModeArg = "compact"
```

Apply this to:

- `build_topic_literature_map`
- `get_publication_citation_graph`
- `find_related_evidence_candidates`

Update each graph tool docstring so the catalog tests have matching runtime-facing guidance:

```python
"""Use this when a user needs reference or cited-by neighbors for one publication.
response_mode='compact' is the MCP default for LLM candidate selection; full can be
large and is for explicit debug graph inspection. Next: get_publication_passages."""
```

Use the same wording pattern for `build_topic_literature_map` and `find_related_evidence_candidates`, preserving each tool's existing purpose sentence and existing `Next:` guidance.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py -q -k "graph or citation_graph or related_evidence or topic_literature_map"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/publications.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py
git commit -m "feat: default graph MCP tools to compact"
```

## Task 2: Add Shared Graph Request Signature And Budget Helpers

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/literature_graph_compact.py`
- Modify: `tests/unit/test_literature_graph_compact.py`

- [ ] **Step 1: Write failing helper tests**

Add tests to `tests/unit/test_literature_graph_compact.py`:

```python
import json

from pubtator_link.models.literature_graph import (
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    PublicationCitationGraphRequest,
)
from pubtator_link.services.literature_graph_compact import (
    COMPACT_BUDGET_BYTES,
    graph_detail_next_commands,
    graph_request_metadata,
    graph_payload_json_bytes,
    mark_graph_payload_truncated,
)


def test_graph_request_signature_metadata_is_deterministic_for_request() -> None:
    request = PublicationCitationGraphRequest(pmid="123", response_mode="compact")

    first = graph_request_metadata(
        tool_name="get_publication_citation_graph",
        request=request,
        source_versions={"pubmed": "live"},
    )
    second = graph_request_metadata(
        tool_name="get_publication_citation_graph",
        request=request,
        source_versions={"pubmed": "live"},
    )

    assert first.request_signature == second.request_signature
    assert first.request_signature is not None
    assert first.cache_key == first.request_signature
    assert first.snapshot_date is not None
    assert first.source_versions["pubmed"] == "live"


def test_graph_payload_json_bytes_uses_compact_json() -> None:
    payload = {"source": LiteraturePaper(pmid="123").model_dump(mode="json")}
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

    assert graph_payload_json_bytes(payload) == len(expected)
    assert 0 < graph_payload_json_bytes(payload) < 1024


def test_graph_detail_next_commands_preserve_request_args() -> None:
    request = PublicationCitationGraphRequest(pmid="123", response_mode="compact")

    commands = graph_detail_next_commands(
        tool_name="get_publication_citation_graph",
        request=request,
        modes=("full", "nodes_edges"),
    )

    assert commands[0]["tool"] == "get_publication_citation_graph"
    assert commands[0]["arguments"]["pmid"] == "123"
    assert commands[0]["arguments"]["response_mode"] == "full"
    assert commands[1]["arguments"]["response_mode"] == "nodes_edges"


def test_mark_graph_payload_truncated_merges_counts_and_budget_advice() -> None:
    meta = LiteratureGraphResponseMeta(response_mode="compact")

    updated = mark_graph_payload_truncated(
        meta,
        omitted_counts={"candidate_details": 3},
        budget_bytes=COMPACT_BUDGET_BYTES,
    )

    assert updated.truncated is True
    assert updated.omitted_counts["candidate_details"] == 3
    assert "12000" in updated.budget_advice or "12 KiB" in updated.budget_advice
```

- [ ] **Step 2: Run helper tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_compact.py -q
```

Expected: FAIL because the helper functions do not exist.

- [ ] **Step 3: Add graph request signature metadata**

In `pubtator_link/models/literature_graph.py`, extend `LiteratureGraphResponseMeta`:

```python
request_signature: str | None = None
```

Keep the existing `cache_key` field as a compatibility alias populated with the same value during this sprint.

- [ ] **Step 4: Implement shared graph helper functions**

In `pubtator_link/services/literature_graph_compact.py`, add imports:

```python
from collections.abc import Mapping

from pubtator_link.models.literature_graph import (
    LiteratureGraphResponseMeta,
    LiteratureGraphResponseMode,
)
from pubtator_link.services.provenance import corpus_snapshot_date, stable_cache_key
```

Add constants and helpers:

```python
GRAPH_PAYLOAD_CONTRACT_VERSION = "literature_graph_payload_controls_v1"


def graph_payload_json_bytes(payload: Any) -> int:
    if hasattr(payload, "model_dump_json"):
        return len(payload.model_dump_json(by_alias=True).encode("utf-8"))
    return len(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def graph_request_metadata(
    *,
    tool_name: str,
    request: Any,
    source_versions: Mapping[str, str] | None = None,
) -> LiteratureGraphResponseMeta:
    versions = {
        "payload_contract": GRAPH_PAYLOAD_CONTRACT_VERSION,
        **dict(source_versions or {}),
    }
    request_signature = stable_cache_key(
        "literature_graph",
        {
            "tool": tool_name,
            "request": request.model_dump(mode="json"),
        },
    )
    return LiteratureGraphResponseMeta(
        response_mode=request.response_mode,
        request_signature=request_signature,
        cache_key=request_signature,
        snapshot_date=corpus_snapshot_date(),
        source_versions=versions,
    )


def graph_detail_next_commands(
    *,
    tool_name: str,
    request: Any,
    modes: tuple[LiteratureGraphResponseMode, ...],
) -> list[dict[str, Any]]:
    request_args = request.model_dump(mode="json", exclude_none=True)
    return [
        {
            "tool": tool_name,
            "arguments": {**request_args, "response_mode": mode},
        }
        for mode in modes
        if mode != request.response_mode
    ]


def graph_budget_bytes(response_mode: LiteratureGraphResponseMode) -> int | None:
    if response_mode == "compact":
        return COMPACT_BUDGET_BYTES
    if response_mode == "nodes_edges":
        return NODES_EDGES_BUDGET_BYTES
    return None


def mark_graph_payload_truncated(
    meta: LiteratureGraphResponseMeta,
    *,
    omitted_counts: Mapping[str, int],
    budget_bytes: int,
) -> LiteratureGraphResponseMeta:
    merged = dict(meta.omitted_counts)
    for key, count in omitted_counts.items():
        if count > 0:
            merged[key] = merged.get(key, 0) + count
    return meta.model_copy(
        update={
            "truncated": True,
            "omitted_counts": merged,
            "budget_advice": (
                f"Response was compacted to stay within the {budget_bytes} byte "
                f"({budget_bytes // 1024} KiB) graph payload budget; request "
                "response_mode='full' or narrower inputs for detail."
            ),
        }
    )
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
uv run pytest tests/unit/test_literature_graph_compact.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/literature_graph_compact.py tests/unit/test_literature_graph_compact.py
git commit -m "feat: add graph request metadata helpers"
```

## Task 3: Enforce Compact Citation Graph Budgets And Cache Metadata

**Files:**
- Modify: `pubtator_link/services/citation_graph.py`
- Modify: `tests/unit/test_citation_graph_service.py`
- Modify: `tests/test_routes/test_publication_literature_graph.py`

- [ ] **Step 1: Write failing citation graph service tests**

Add tests to `tests/unit/test_citation_graph_service.py`:

```python
@pytest.mark.asyncio
async def test_citation_graph_compact_populates_cache_snapshot_and_versions() -> None:
    service = CitationGraphService(
        crossref=FakeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
        )
    )

    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert response.meta.snapshot_date is not None
    assert response.meta.source_versions["payload_contract"] == (
        "literature_graph_payload_controls_v1"
    )
    assert response.meta.source_versions["crossref"] == "live"
    assert any(
        command["arguments"]["response_mode"] == "full"
        for command in response.meta.next_commands
    )
    assert any(
        command["arguments"]["response_mode"] == "nodes_edges"
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_citation_graph_compact_reports_budget_truncation() -> None:
    service = CitationGraphService(
        crossref=LargeCrossref(),
        discovery_service=FakeDiscovery(),
        metadata_service=FakeMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1016/j.ard.2025.05.020",
            direction="references",
            response_mode="compact",
            resolve_reference_pmids=False,
            max_results=25,
        )
    )

    assert response.meta.truncated is True
    assert response.meta.budget_advice is not None
    assert response.meta.omitted_counts
    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
```

Keep the existing REST default-full test and add this explicit full-mode assertion:

```python
assert request.response_mode == "full"
```

- [ ] **Step 2: Run citation tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py tests/test_routes/test_publication_literature_graph.py -q -k "citation_graph"
```

Expected: FAIL because citation graph request signature metadata and budget enforcement are missing.

- [ ] **Step 3: Import graph helpers**

In `pubtator_link/services/citation_graph.py`, import:

```python
from pubtator_link.services.literature_graph_compact import (
    candidate_summary,
    coalesced_provider_warnings,
    graph_budget_bytes,
    graph_request_metadata,
    graph_detail_next_commands,
    graph_payload_json_bytes,
    json_size_class,
    mark_graph_payload_truncated,
)
```

- [ ] **Step 4: Populate request signature metadata**

Before building `PublicationCitationGraphResponse`, create metadata:

```python
meta = graph_request_metadata(
    tool_name="get_publication_citation_graph",
    request=request,
    source_versions=_citation_source_versions(request, self),
).model_copy(
    update={
        "warnings": coalesced_provider_warnings(warnings),
        "next_commands": [
            *_next_commands(candidate_pmids),
            *graph_detail_next_commands(
                tool_name="get_publication_citation_graph",
                request=request,
                modes=("full", "nodes_edges"),
            ),
        ],
        "provider_status": [
            *references_status,
            *cited_by_status,
            *identifier_resolution_status,
            *open_access_status,
        ],
        "omitted_counts": compact_omitted_counts,
        "truncated": bool(compact_omitted_counts),
    }
)
```

Add helper:

```python
def _citation_source_versions(
    request: PublicationCitationGraphRequest,
    service: CitationGraphService,
) -> dict[str, str]:
    versions: dict[str, str] = {"pubmed": "live"}
    if service.crossref is not None:
        versions[CROSSREF_PROVIDER] = "live"
    if service.europe_pmc is not None:
        versions[EUROPE_PMC_PROVIDER] = "live"
    if service.openalex is not None:
        versions[OPENALEX_PROVIDER] = "live"
    if request.include_open_access_status and service.unpaywall is not None:
        versions[UNPAYWALL_PROVIDER] = "live"
    return versions
```

- [ ] **Step 5: Add deterministic compact budget trimming**

After constructing the response and before setting `response_size_class`, call:

```python
response = _enforce_citation_graph_budget(response)
response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
return response
```

Add helper:

```python
def _enforce_citation_graph_budget(
    response: PublicationCitationGraphResponse,
) -> PublicationCitationGraphResponse:
    budget = graph_budget_bytes(response.response_mode)
    if budget is None:
        return response
    if graph_payload_json_bytes(response) <= budget:
        return response

    omitted: dict[str, int] = {}
    reference_candidates = [
        _budget_compact_candidate(candidate) for candidate in response.reference_candidates
    ]
    cited_by_candidates = [
        _budget_compact_candidate(candidate) for candidate in response.cited_by_candidates
    ]
    compacted = response.model_copy(
        update={
            "reference_candidates": reference_candidates,
            "cited_by_candidates": cited_by_candidates,
        }
    )
    if graph_payload_json_bytes(compacted) <= budget:
        omitted["candidate_details"] = (
            len(response.reference_candidates) + len(response.cited_by_candidates)
        )
        return compacted.model_copy(
            update={
                "meta": mark_graph_payload_truncated(
                    compacted.meta,
                    omitted_counts=omitted,
                    budget_bytes=budget,
                )
            }
        )

    compacted, omitted = _drop_citation_candidates_to_budget(
        compacted,
        budget=budget,
        omitted_counts=omitted,
    )
    return compacted.model_copy(
        update={
            "meta": mark_graph_payload_truncated(
                compacted.meta,
                omitted_counts=omitted,
                budget_bytes=budget,
            )
        }
    )


def _drop_citation_candidates_to_budget(
    response: PublicationCitationGraphResponse,
    *,
    budget: int,
    omitted_counts: dict[str, int],
) -> tuple[PublicationCitationGraphResponse, dict[str, int]]:
    current_bytes = graph_payload_json_bytes(response)
    overage = current_bytes - budget
    if overage <= 0:
        return response, omitted_counts

    cited_by_candidates, dropped_cited_by, overage = _drop_suffix_by_estimated_bytes(
        response.cited_by_candidates,
        overage,
    )
    reference_candidates, dropped_references, overage = _drop_suffix_by_estimated_bytes(
        response.reference_candidates,
        overage,
    )
    if dropped_cited_by:
        omitted_counts["cited_by_candidates"] = (
            omitted_counts.get("cited_by_candidates", 0) + dropped_cited_by
        )
    if dropped_references:
        omitted_counts["reference_candidates"] = (
            omitted_counts.get("reference_candidates", 0) + dropped_references
        )

    trimmed = response.model_copy(
        update={
            "reference_candidates": reference_candidates,
            "cited_by_candidates": cited_by_candidates,
        }
    )
    if graph_payload_json_bytes(trimmed) <= budget:
        return trimmed, omitted_counts

    omitted_counts["reference_candidates"] = omitted_counts.get(
        "reference_candidates", 0
    ) + len(trimmed.reference_candidates)
    omitted_counts["cited_by_candidates"] = omitted_counts.get("cited_by_candidates", 0) + len(
        trimmed.cited_by_candidates
    )
    return trimmed.model_copy(
        update={"reference_candidates": [], "cited_by_candidates": []}
    ), omitted_counts


def _drop_suffix_by_estimated_bytes(
    candidates: list[LiteratureCandidateSummary],
    overage: int,
) -> tuple[list[LiteratureCandidateSummary], int, int]:
    reclaimed = 0
    dropped = 0
    for candidate in reversed(candidates):
        reclaimed += graph_payload_json_bytes(candidate)
        dropped += 1
        if reclaimed >= overage:
            break
    if dropped == 0:
        return candidates, 0, overage
    return candidates[: len(candidates) - dropped], dropped, max(0, overage - reclaimed)


def _budget_compact_candidate(
    candidate: LiteratureCandidateSummary,
) -> LiteratureCandidateSummary:
    return candidate.model_copy(
        update={
            "publication_types": candidate.publication_types[:3],
            "access_flags": {},
            "relevance_to_query": None,
            "rank_reasons": candidate.rank_reasons[:3],
            "demotion_reasons": candidate.demotion_reasons[:3],
            "signals": candidate.signals[:5],
            "source_tools": [],
            "next_actions": [],
        }
    )
```

- [ ] **Step 6: Run citation tests**

Run:

```bash
uv run pytest tests/unit/test_citation_graph_service.py tests/test_routes/test_publication_literature_graph.py -q -k "citation_graph"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/citation_graph.py tests/unit/test_citation_graph_service.py tests/test_routes/test_publication_literature_graph.py
git commit -m "feat: budget citation graph compact responses"
```

## Task 4: Enforce Topic And Related Graph Compact Contracts

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Modify: `tests/unit/test_topic_literature_map_service.py`
- Modify: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing topic tests**

Add tests to `tests/unit/test_topic_literature_map_service.py`:

```python
@pytest.mark.asyncio
async def test_topic_map_compact_serialization_omits_empty_nodes_edges() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(query="FMF", response_mode="compact")
    )

    payload = response.model_dump(by_alias=True)

    assert "nodes" not in payload
    assert "edges" not in payload
    assert response.meta.omitted_counts["nodes"] > 0
    assert response.meta.omitted_counts["edges"] > 0
    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert any(
        command["arguments"]["response_mode"] == "full"
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_topic_map_compact_filters_doi_only_summary_papers() -> None:
    service = TopicLiteratureMapService(
        search_client=FakeSearchClient(),
        metadata_service=FakeMetadata(),
        citation_graph_service=DoiOnlyCitationGraph(),
        related_evidence_service=EmptyRelatedEvidence(),
    )

    response = await service.build_map(
        TopicLiteratureMapRequest(
            pmids=["111"],
            response_mode="compact",
            max_neighbors_per_paper=1,
        )
    )

    summary_payload = response.summary.model_dump(mode="json")
    assert "10.1000/unresolved-topic" not in str(summary_payload)
    assert response.meta.omitted_counts["doi_only_unresolved"] == 1
```

- [ ] **Step 2: Write failing related evidence tests**

Add tests to `tests/unit/test_related_evidence_service.py`:

```python
@pytest.mark.asyncio
async def test_related_evidence_compact_populates_cache_and_omitted_candidate_count() -> None:
    metadata = RecordingMetadata()
    service = RelatedEvidenceService(
        discovery_service=ManyCandidateDiscovery(),
        metadata_service=metadata,
        citation_graph_service=ManyCandidateCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            max_results=10,
            response_mode="compact",
            include_citation_neighbors=True,
        )
    )

    assert response.meta.request_signature is not None
    assert response.meta.cache_key == response.meta.request_signature
    assert response.meta.snapshot_date is not None
    assert response.meta.source_versions["pubmed"] == "live"
    assert response.meta.truncated is True
    assert response.meta.omitted_counts["candidates"] > 0
    assert any(
        command["arguments"]["response_mode"] == "full"
        for command in response.meta.next_commands
    )


@pytest.mark.asyncio
async def test_related_evidence_compact_uses_normalized_neighbor_score() -> None:
    service = RelatedEvidenceService(
        discovery_service=ScoreRangeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            response_mode="compact",
            include_citation_neighbors=False,
        )
    )
    payload = response.model_dump(by_alias=True)

    assert payload["candidates"][0]["normalized_neighbor_score"] is not None
    assert "pubmed_neighbor_score" not in payload["candidates"][0]
    assert "score" not in payload["candidates"][0]
```

- [ ] **Step 3: Run topic and related tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py -q -k "compact or related_evidence"
```

Expected: FAIL because topic empty arrays, topic summary DOI-only filtering, related request signature metadata, related omission counts, and compact score serialization are incomplete.

- [ ] **Step 4: Add compact serializers to literature graph models**

In `RelatedEvidenceCandidatesResponse`, add response-mode-aware compact candidate serialization:

```python
@model_serializer(mode="wrap")
def omit_raw_scores_for_compact(self, handler: Any) -> dict[str, Any]:
    data = handler(self)
    if not isinstance(data, dict) or self.meta.response_mode != "compact":
        return data
    for candidate in data.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("normalized_neighbor_score") is not None:
            candidate.pop("score", None)
            candidate.pop("pubmed_neighbor_score", None)
    return data
```

In `TopicLiteratureMapResponse`, add a compact serializer:

```python
@model_serializer(mode="wrap")
def omit_empty_topology_for_compact(self, handler: Any) -> dict[str, Any]:
    data = handler(self)
    if not isinstance(data, dict) or self.response_mode != "compact":
        return data
    for field in ("nodes", "edges"):
        if not data.get(field):
            data.pop(field, None)
    return data
```

- [ ] **Step 5: Populate topic request signature metadata and filter compact summary**

In `pubtator_link/services/topic_literature_map.py`, import graph helpers:

```python
from pubtator_link.services.literature_graph_compact import (
    TOPIC_RANKING_VERSION,
    candidate_summary,
    coalesced_provider_warnings,
    compact_author_summary,
    graph_budget_bytes,
    graph_request_metadata,
    graph_detail_next_commands,
    graph_payload_json_bytes,
    intent_flags_for_query,
    json_size_class,
    mark_graph_payload_truncated,
    normalize_query_text,
)
```

Change `_compact_summary()` to keep only PMID-bearing papers:

```python
def _compact_summary(
    summary: TopicLiteratureMapSummary,
    recommended_next_pmids: list[str],
) -> TopicLiteratureMapSummary:
    return TopicLiteratureMapSummary(
        central_papers=[_compact_paper(paper) for paper in summary.central_papers if paper.pmid][
            :5
        ],
        recent_connected_papers=[
            _compact_paper(paper) for paper in summary.recent_connected_papers if paper.pmid
        ][:5],
        bridge_papers=[_compact_paper(paper) for paper in summary.bridge_papers if paper.pmid][
            :5
        ],
        dominant_author_groups=summary.dominant_author_groups,
        accessible_full_text_candidates=[],
        closed_central_sources=[
            _compact_paper(paper) for paper in summary.closed_central_sources if paper.pmid
        ][:5],
        recommended_next_pmids=recommended_next_pmids,
    )
```

Build response `_meta` from `graph_request_metadata()`:

```python
meta = graph_request_metadata(
    tool_name="build_topic_literature_map",
    request=request,
    source_versions={
        "pubtator_search": "live",
        "pubmed": "live",
        "citation_graph": "live",
        "related_evidence": "live",
    },
).model_copy(
    update={
        "truncated": any(count > 0 for count in omitted_counts.values()),
        "omitted_counts": omitted_counts,
        "ranking_version": TOPIC_RANKING_VERSION,
        "warnings": coalesced_provider_warnings(warnings),
        "next_commands": [
            *hints,
            *graph_detail_next_commands(
                tool_name="build_topic_literature_map",
                request=request,
                modes=("full", "nodes_edges"),
            ),
        ],
        "provider_status": [],
    }
)
```

- [ ] **Step 6: Add topic budget enforcement**

After constructing `TopicLiteratureMapResponse`, call:

```python
response = _enforce_topic_map_budget(response)
response.meta.response_size_class = json_size_class(response.model_dump(by_alias=True))
return response
```

Add helper:

```python
def _enforce_topic_map_budget(response: TopicLiteratureMapResponse) -> TopicLiteratureMapResponse:
    budget = graph_budget_bytes(response.response_mode)
    if budget is None:
        return response
    if graph_payload_json_bytes(response) <= budget:
        return response

    omitted: dict[str, int] = {}
    compacted = response.model_copy(
        update={
            "demoted_candidate_pmids": [],
            "demoted_reasons_by_pmid": {},
            "candidate_retrieval_hints": response.candidate_retrieval_hints[:1],
        }
    )
    omitted["demoted_candidates"] = len(response.demoted_candidate_pmids)
    compacted, dropped = _drop_topic_candidates_to_budget(compacted, budget=budget)
    if dropped:
        omitted["top_candidates"] = omitted.get("top_candidates", 0) + dropped
    return compacted.model_copy(
        update={
            "meta": mark_graph_payload_truncated(
                compacted.meta,
                omitted_counts=omitted,
                budget_bytes=budget,
            )
        }
    )


def _drop_topic_candidates_to_budget(
    response: TopicLiteratureMapResponse,
    *,
    budget: int,
) -> tuple[TopicLiteratureMapResponse, int]:
    overage = graph_payload_json_bytes(response) - budget
    if overage <= 0:
        return response, 0
    reclaimed = 0
    dropped = 0
    for candidate in reversed(response.top_candidates):
        reclaimed += graph_payload_json_bytes(candidate)
        dropped += 1
        if reclaimed >= overage:
            break
    trimmed = response.model_copy(
        update={"top_candidates": response.top_candidates[: len(response.top_candidates) - dropped]}
    )
    if graph_payload_json_bytes(trimmed) <= budget:
        return trimmed, dropped
    return trimmed.model_copy(update={"top_candidates": []}), len(response.top_candidates)
```

- [ ] **Step 6a: Keep compact empty-array pruning in the response serializer**

Do not move content selection or budget trimming into Pydantic serializers. The serializer added in this task only removes empty `nodes` and `edges` at dump time for compact responses; all truncation and selection logic stays in `TopicLiteratureMapService`.

```python
payload = response.model_dump(by_alias=True)
assert "nodes" not in payload
assert "edges" not in payload
```

- [ ] **Step 7: Add related evidence request signature metadata and omission counts**

In `pubtator_link/services/related_evidence.py`, import graph helpers:

```python
from pubtator_link.services.literature_graph_compact import (
    coalesced_provider_warnings,
    graph_request_metadata,
    graph_detail_next_commands,
    json_size_class,
)
```

Before truncating candidates to `request.max_results`, record full count:

```python
candidate_count_before_limit = len(candidates)
candidates = candidates[: request.max_results]
omitted_counts = {
    "candidates": max(0, candidate_count_before_limit - len(candidates)),
}
```

Build `_meta` with cache fields:

```python
meta = graph_request_metadata(
    tool_name="find_related_evidence_candidates",
    request=request,
    source_versions={
        "pubmed": "live",
        "ncbi_elink": "live",
        "citation_graph": "live",
    },
).model_copy(
    update={
        "warnings": coalesced_provider_warnings(warnings),
        "next_commands": [
            *_next_commands(ordered_pmids),
            *graph_detail_next_commands(
                tool_name="find_related_evidence_candidates",
                request=request,
                modes=("full",),
            ),
        ],
        "truncated": any(count > 0 for count in omitted_counts.values()),
        "omitted_counts": {k: v for k, v in omitted_counts.items() if v > 0},
    }
)
```

- [ ] **Step 8: Run graph compact tests**

Run:

```bash
uv run pytest tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py tests/unit/test_literature_graph_compact.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/literature_graph.py pubtator_link/services/topic_literature_map.py pubtator_link/services/related_evidence.py tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py
git commit -m "feat: tighten compact graph payloads"
```

## Task 5: Add Inspect Review Index Pagination Models And Cursor Helpers

**Files:**
- Create: `pubtator_link/services/review_context/pagination.py`
- Create: `tests/unit/test_review_context_pagination.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing cursor tests**

Create `tests/unit/test_review_context_pagination.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link.services.review_context.pagination import (
    InspectReviewIndexCursor,
    decode_inspect_review_index_cursor,
    encode_inspect_review_index_cursor,
    inspect_review_index_scope_hash,
)


def test_inspect_review_index_cursor_round_trips_offsets_and_scope() -> None:
    scope_hash = inspect_review_index_scope_hash(
        review_id="review-1",
        session_id="session-1",
        pmids=["222", "111"],
    )
    token = encode_inspect_review_index_cursor(
        InspectReviewIndexCursor(
            scope_hash=scope_hash,
            source_offset=50,
            failed_source_offset=3,
        )
    )

    decoded = decode_inspect_review_index_cursor(
        token,
        expected_scope_hash=scope_hash,
    )

    assert decoded.source_offset == 50
    assert decoded.failed_source_offset == 3


def test_inspect_review_index_cursor_rejects_wrong_scope() -> None:
    token = encode_inspect_review_index_cursor(
        InspectReviewIndexCursor(
            scope_hash="aaaaaaaaaaaa",
            source_offset=0,
            failed_source_offset=0,
        )
    )

    with pytest.raises(ValueError, match="cursor scope does not match request"):
        decode_inspect_review_index_cursor(
            token,
            expected_scope_hash="bbbbbbbbbbbb",
        )


def test_inspect_review_index_cursor_rejects_invalid_token() -> None:
    with pytest.raises(ValueError, match="invalid inspect_review_index cursor"):
        decode_inspect_review_index_cursor("not-valid", expected_scope_hash="aaaaaaaaaaaa")
```

- [ ] **Step 2: Write failing model serialization test**

Add to `tests/unit/test_review_context_service.py`:

```python
def test_inspect_review_index_response_serializes_pagination_fields() -> None:
    response = InspectReviewIndexResponse(
        review_id="review-1",
        response_mode="compact",
        preparation_status=PreparationStatus(),
        sources=[],
        totals=ReviewIndexTotals(source_count=12, failed_source_count=2),
        failed_sources=[],
        next_cursor="abc",
        page_source_count=5,
        page_failed_source_count=1,
        omitted_counts={"sources": 7, "failed_sources": 1},
    )

    data = response.model_dump()

    assert data["next_cursor"] == "abc"
    assert data["page_source_count"] == 5
    assert data["page_failed_source_count"] == 1
    assert data["omitted_counts"] == {"sources": 7, "failed_sources": 1}
```

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_pagination.py tests/unit/test_review_context_service.py -q -k "cursor or pagination"
```

Expected: FAIL because the cursor helper and model fields do not exist.

- [ ] **Step 4: Implement cursor helper**

Create `pubtator_link/services/review_context/pagination.py`:

```python
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InspectReviewIndexCursor:
    scope_hash: str
    source_offset: int
    failed_source_offset: int
    version: int = 1


def inspect_review_index_scope_hash(
    *,
    review_id: str,
    session_id: str | None,
    pmids: list[str],
) -> str:
    payload = {
        "review_id": review_id,
        "session_id": session_id,
        "pmids": sorted(pmids),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def encode_inspect_review_index_cursor(cursor: InspectReviewIndexCursor) -> str:
    payload = {
        "v": cursor.version,
        "scope_hash": cursor.scope_hash,
        "source_offset": cursor.source_offset,
        "failed_source_offset": cursor.failed_source_offset,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_inspect_review_index_cursor(
    token: str,
    *,
    expected_scope_hash: str,
) -> InspectReviewIndexCursor:
    try:
        padding = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(f"{token}{padding}".encode("ascii"))
        payload: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        raise ValueError("invalid inspect_review_index cursor") from exc

    if payload.get("v") != 1:
        raise ValueError("invalid inspect_review_index cursor version")
    if payload.get("scope_hash") != expected_scope_hash:
        raise ValueError("cursor scope does not match request")

    source_offset = payload.get("source_offset")
    failed_source_offset = payload.get("failed_source_offset")
    if not isinstance(source_offset, int) or source_offset < 0:
        raise ValueError("invalid inspect_review_index source offset")
    if not isinstance(failed_source_offset, int) or failed_source_offset < 0:
        raise ValueError("invalid inspect_review_index failed source offset")

    return InspectReviewIndexCursor(
        scope_hash=expected_scope_hash,
        source_offset=source_offset,
        failed_source_offset=failed_source_offset,
    )
```

- [ ] **Step 5: Add inspect request and response fields**

In `pubtator_link/models/review_rerag.py`, extend `InspectReviewIndexRequest`:

```python
limit: int | None = Field(default=None, ge=1, le=100)
cursor: str | None = None
```

Extend `InspectReviewIndexResponse`:

```python
next_cursor: str | None = None
page_source_count: int = Field(default=0, ge=0)
page_failed_source_count: int = Field(default=0, ge=0)
omitted_counts: dict[str, int] = Field(default_factory=dict)
```

- [ ] **Step 6: Run tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_pagination.py tests/unit/test_review_context_service.py -q -k "cursor or pagination"
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/review_context/pagination.py pubtator_link/models/review_rerag.py tests/unit/test_review_context_pagination.py tests/unit/test_review_context_service.py
git commit -m "feat: add review index pagination models"
```

## Task 6: Implement Inspect Review Index Pagination In Repository And Service

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `tests/unit/test_review_context_service.py`
- Modify: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write failing service pagination test**

Add to `tests/unit/test_review_context_service.py`:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_paginates_sources_and_failed_sources() -> None:
    repository = FakeReviewContextRepository([], preparation_status={"complete": 3, "failed": 2})
    repository.source_summaries = [
        ReviewSourceSummary(
            source_id=f"PMID:{pmid}",
            pmid=pmid,
            source_kind="pubtator_abstract",
            job_status="complete",
            coverage="abstract_only",
        )
        for pmid in ("111", "222", "333")
    ]
    repository.failed_source_summaries = [
        FailedSourceSummary(
            source_id=f"PMID:{pmid}",
            pmid=pmid,
            source_kind="pubtator_full_bioc",
            job_status="failed",
        )
        for pmid in ("444", "555")
    ]
    repository.index_totals = ReviewIndexTotals(
        source_count=3,
        failed_source_count=2,
        passage_count=3,
    )
    service = ReviewContextService(repository)

    first = await service.inspect_review_index(
        "review-1",
        InspectReviewIndexRequest(response_mode="compact", limit=2),
    )
    second = await service.inspect_review_index(
        "review-1",
        InspectReviewIndexRequest(
            response_mode="compact",
            limit=2,
            cursor=first.next_cursor,
        ),
    )

    assert [source.pmid for source in first.sources] == ["111", "222"]
    assert [source.pmid for source in second.sources] == ["333"]
    assert [source.pmid for source in first.failed_sources] == ["444", "555"]
    assert second.failed_sources == []
    assert first.next_cursor is not None
    assert second.next_cursor is None
    assert first.page_source_count == 2
    assert first.page_failed_source_count == 2
    assert first.totals.source_count == 3
    assert first.omitted_counts["sources"] == 1
```

Update `FakeReviewContextRepository.list_review_sources()` and `list_review_failed_sources()` in the same test file to accept `limit` and `offset` and slice returned summaries:

```python
start = offset or 0
stop = None if limit is None else start + limit
return self.source_summaries[start:stop]
```

- [ ] **Step 2: Write failing repository pagination tests**

Add to `tests/unit/test_review_rerag_repository.py`:

```python
@pytest.mark.asyncio
async def test_list_review_sources_applies_limit_and_offset() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "source_id": "222",
            "pmid": "222",
            "source_kind": "pubtator_abstract",
            "job_status": "complete",
            "error": None,
            "attempt_statuses": ["success"],
            "sections": ["abstract"],
            "passage_count": 1,
            "char_count": 20,
            "coverage_reason": "abstract_fallback_used",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources("review-1", limit=1, offset=1)
    _sql, args = connection.executed[0]

    assert [source.pmid for source in sources] == ["222"]
    assert args[-2:] == (1, 1)


@pytest.mark.asyncio
async def test_list_review_failed_sources_applies_limit_and_offset() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "source_id": "222",
            "pmid": "222",
            "source_kind": "pubtator_full_bioc",
            "job_status": "failed",
            "error": "not available",
            "attempt_statuses": ["failed"],
            "coverage_reason": "upstream_404",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        },
        {
            "source_id": "333",
            "pmid": "333",
            "source_kind": "pubtator_full_bioc",
            "job_status": "failed",
            "error": "not available",
            "attempt_statuses": ["failed"],
            "coverage_reason": "upstream_404",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    failed = await repository.list_review_failed_sources("review-1", limit=2, offset=1)
    _sql, args = connection.executed[0]

    assert [source.pmid for source in failed] == ["222", "333"]
    assert args[-2:] == (2, 1)
```

- [ ] **Step 3: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py -q -k "inspect_review_index or list_review_sources or list_review_failed_sources"
```

Expected: FAIL because repository methods and the service do not accept pagination arguments.

- [ ] **Step 4: Extend repository protocols**

In `pubtator_link/services/review_context_service.py` and `pubtator_link/repositories/review_rerag.py`, extend `list_review_sources()` signatures:

```python
limit: int | None = None,
offset: int = 0,
```

Extend `list_review_failed_sources()` signatures:

```python
limit: int | None = None,
offset: int = 0,
```

- [ ] **Step 5: Add SQL limit and offset**

In `PostgresReviewReragRepository.list_review_sources()`, append:

```sql
limit coalesce($4::int, 2147483647)
offset $5::int
```

Pass parameters:

```python
review_id,
pmid_filter,
session_id,
limit,
offset,
```

For the passage sample query, keep using the paged `source_ids` list already derived from returned sources.

In `list_review_failed_sources()`, append:

```sql
limit coalesce($3::int, 2147483647)
offset $4::int
```

Pass parameters:

```python
review_id,
session_id,
limit,
offset,
```

- [ ] **Step 6: Implement service pagination**

In `ReviewContextService.inspect_review_index()`, compute scope and cursor offsets:

```python
scope_hash = inspect_review_index_scope_hash(
    review_id=review_id,
    session_id=request.session_id,
    pmids=request.pmids,
)
source_offset = 0
failed_source_offset = 0
if request.cursor:
    cursor = decode_inspect_review_index_cursor(
        request.cursor,
        expected_scope_hash=scope_hash,
    )
    source_offset = cursor.source_offset
    failed_source_offset = cursor.failed_source_offset
```

Fetch global totals before page queries so exhausted sides can be skipped:

```python
totals = await self.repository.review_index_totals(review_id, session_id=request.session_id)
```

Use `request.limit` for repository calls, skipping a side once its cursor offset reaches the global count:

```python
sources = (
    []
    if request.limit is not None and source_offset >= totals.source_count
    else await self.repository.list_review_sources(
        review_id,
        request.pmids,
        include_passage_samples=request.include_passage_samples,
        sample_per_pmid=request.sample_per_pmid,
        min_sample_chars=request.min_sample_chars,
        sample_section_policy=request.sample_section_policy,
        session_id=request.session_id,
        limit=request.limit,
        offset=source_offset,
    )
)
failed_sources = (
    []
    if request.limit is not None and failed_source_offset >= totals.failed_source_count
    else await self.repository.list_review_failed_sources(
        review_id,
        session_id=request.session_id,
        limit=request.limit,
        offset=failed_source_offset,
    )
)
```

Compute next cursor and omitted counts after `totals`:

```python
next_source_offset = source_offset + len(sources)
next_failed_source_offset = failed_source_offset + len(failed_sources)
remaining_sources = max(0, totals.source_count - next_source_offset)
remaining_failed_sources = max(0, totals.failed_source_count - next_failed_source_offset)
next_cursor = None
if request.limit is not None and (remaining_sources > 0 or remaining_failed_sources > 0):
    next_cursor = encode_inspect_review_index_cursor(
        InspectReviewIndexCursor(
            scope_hash=scope_hash,
            source_offset=next_source_offset,
            failed_source_offset=next_failed_source_offset,
        )
    )
omitted_counts = {
    key: value
    for key, value in {
        "sources": remaining_sources,
        "failed_sources": remaining_failed_sources,
    }.items()
    if request.limit is not None and value > 0
}
```

Pass pagination fields into `InspectReviewIndexResponse`.

- [ ] **Step 7: Run service and repository tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py -q -k "inspect_review_index or list_review_sources or list_review_failed_sources"
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/services/review_context_service.py pubtator_link/repositories/review_rerag.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: paginate review index inspection service"
```

## Task 7: Wire Inspect Review Index Pagination Through MCP And REST

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing MCP adapter test**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_adapter_wires_limit_cursor_and_next_command() -> None:
    from pubtator_link.mcp.service_adapters import inspect_review_index_impl
    from pubtator_link.models.review_rerag import (
        InspectReviewIndexResponse,
        PreparationStatus,
        ReviewIndexTotals,
    )

    class RecordingService:
        request = None

        async def inspect_review_index(self, review_id, request):
            self.request = request
            return InspectReviewIndexResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                preparation_status=PreparationStatus(complete=1),
                sources=[],
                totals=ReviewIndexTotals(source_count=2),
                failed_sources=[],
                next_cursor="cursor-2",
                page_source_count=1,
                omitted_counts={"sources": 1},
            )

    service = RecordingService()

    result = await inspect_review_index_impl(
        service=service,
        review_id="review-1",
        response_mode="compact",
        limit=1,
        cursor="cursor-1",
    )

    assert service.request.limit == 1
    assert service.request.cursor == "cursor-1"
    assert result["next_cursor"] == "cursor-2"
    assert result["_meta"]["next_commands"][0]["tool"] == "inspect_review_index"
    assert result["_meta"]["next_commands"][0]["arguments"]["cursor"] == "cursor-2"
```

- [ ] **Step 2: Write failing MCP schema tests**

Add to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
def test_inspect_review_index_schema_exposes_pagination_args() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["inspect_review_index"].parameters

    assert schema["properties"]["limit"]["default"] == 50
    assert "cursor" in schema["properties"]
```

- [ ] **Step 3: Write failing REST route test**

Add to `tests/test_routes/test_reviews.py`:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_route_accepts_limit_and_cursor() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.inspect_review_index.return_value = InspectReviewIndexResponse(
        review_id="rev_123",
        response_mode="compact",
        preparation_status=PreparationStatus(complete=1),
        sources=[],
        totals=ReviewIndexTotals(source_count=2),
        failed_sources=[],
        next_cursor="cursor-2",
        page_source_count=1,
        omitted_counts={"sources": 1},
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/reviews/rev_123/index",
            params={
                "response_mode": "compact",
                "limit": "1",
                "cursor": "cursor-1",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["next_cursor"] == "cursor-2"
    request = service.inspect_review_index.await_args.kwargs["request"]
    assert request.limit == 1
    assert request.cursor == "cursor-1"
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py -q -k "inspect_review_index"
```

Expected: FAIL because MCP and REST wiring does not expose `limit` or `cursor`.

- [ ] **Step 5: Wire MCP adapter and next command**

In `inspect_review_index_impl()` in `pubtator_link/mcp/service_adapters.py`, add parameters:

```python
limit: int | None = 50,
cursor: str | None = None,
```

Pass them into `InspectReviewIndexRequest`.

After dumping the response, add next-command metadata:

```python
result = response.model_dump()
if response.next_cursor:
    result.setdefault("_meta", {})["next_commands"] = [
        {
            "tool": "inspect_review_index",
            "arguments": {
                "review_id": review_id,
                "session_id": session_id,
                "pmids": pmids or [],
                "response_mode": response_mode,
                "limit": limit,
                "cursor": response.next_cursor,
            },
        }
    ]
return result
```

- [ ] **Step 6: Wire MCP tool signature**

In `pubtator_link/mcp/tools/review.py`, add tool parameters:

```python
limit: Annotated[int | None, Field(ge=1, le=100)] = 50,
cursor: str | None = None,
```

Pass `limit=limit` and `cursor=cursor` into `inspect_review_index_impl()`.

- [ ] **Step 7: Wire REST route query params**

In `pubtator_link/api/routes/reviews.py`, add route parameters:

```python
limit: int | None = Query(default=None, ge=1, le=100),
cursor: str | None = None,
```

Pass `limit=limit` and `cursor=cursor` into `InspectReviewIndexRequest`.

- [ ] **Step 8: Run MCP and REST tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py -q -k "inspect_review_index"
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/api/routes/reviews.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py
git commit -m "feat: expose review index pagination"
```

## Task 8: Add Shared Review Budget Resolver

**Files:**
- Create: `pubtator_link/services/review_context/budgets.py`
- Create: `tests/unit/test_review_context_budgets.py`
- Modify: `pubtator_link/models/review_rerag.py`

- [ ] **Step 1: Write failing budget resolver tests**

Create `tests/unit/test_review_context_budgets.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link.services.review_context.budgets import (
    resolve_batch_budget_args,
    resolve_max_response_chars,
)


def test_resolve_max_response_chars_auto_uses_verbosity_presets() -> None:
    assert resolve_max_response_chars("auto", verbosity="lean") == 12000
    assert resolve_max_response_chars("Auto", verbosity="lean") == 12000
    assert resolve_max_response_chars("auto", verbosity="standard") == 24000
    assert resolve_max_response_chars("auto", verbosity="full") == 60000


def test_resolve_max_response_chars_preserves_numeric_budget() -> None:
    assert resolve_max_response_chars(36000, verbosity="lean") == 36000
    assert resolve_max_response_chars("36000", verbosity="full") == 36000


@pytest.mark.parametrize("value", [1999, 100001, "large"])
def test_resolve_max_response_chars_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        resolve_max_response_chars(value, verbosity="standard")


def test_resolve_batch_budget_args_uses_auto_response_budget() -> None:
    resolved = resolve_batch_budget_args(
        max_total_passages=8,
        max_chars_per_passage=2200,
        max_chars=None,
        max_response_chars="auto",
        verbosity="lean",
    )

    assert resolved.max_chars == 24000
    assert resolved.max_response_chars == 12000
    assert resolved.budget_source == "auto_fit"


def test_resolve_batch_budget_args_preserves_explicit_numeric_budget() -> None:
    resolved = resolve_batch_budget_args(
        max_total_passages=8,
        max_chars_per_passage=2200,
        max_chars=8000,
        max_response_chars=36000,
        verbosity="lean",
    )

    assert resolved.max_chars == 8000
    assert resolved.max_response_chars == 36000
    assert resolved.budget_source == "caller"
```

- [ ] **Step 2: Run budget tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py -q
```

Expected: FAIL because the budget resolver module does not exist.

- [ ] **Step 3: Add review budget type aliases**

In `pubtator_link/models/review_rerag.py`, near `BudgetSource`, add:

```python
ReviewResponseVerbosity = Literal["lean", "standard", "full"]
MaxResponseChars = int | Literal["auto"]
```

Change `RetrieveReviewContextBatchRequest` fields:

```python
max_response_chars: MaxResponseChars = 48000
verbosity: ReviewResponseVerbosity = "standard"
```

The numeric default preserves REST/direct-call compatibility. MCP tool signatures in Task 9 default to `"auto"` explicitly, and REST callers opt into auto behavior by sending `"max_response_chars": "auto"`.

- [ ] **Step 4: Implement budget resolver**

Create `pubtator_link/services/review_context/budgets.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pubtator_link.models.review_rerag import (
    BudgetSource,
    MaxResponseChars,
    ReviewResponseVerbosity,
)

REVIEW_BATCH_DEFAULT_MAX_CHARS = 24_000
REVIEW_BATCH_DEFAULT_MAX_RESPONSE_CHARS = 48_000
REVIEW_BATCH_MAX_CHARS_CAP = 50_000
REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP = 100_000
AUTO_RESPONSE_BUDGETS: dict[ReviewResponseVerbosity, int] = {
    "lean": 12_000,
    "standard": 24_000,
    "full": 60_000,
}


@dataclass(frozen=True)
class ResolvedBatchBudgets:
    max_chars: int
    max_response_chars: int
    budget_source: BudgetSource


def resolve_max_response_chars(
    value: Any,
    *,
    verbosity: ReviewResponseVerbosity,
) -> int:
    if value is None:
        return AUTO_RESPONSE_BUDGETS[verbosity]
    if isinstance(value, str):
        if value.strip().lower() == "auto":
            return AUTO_RESPONSE_BUDGETS[verbosity]
        try:
            value = int(value.strip())
        except ValueError as exc:
            raise ValueError("max_response_chars must be an integer or 'auto'") from exc
    if not isinstance(value, int):
        raise ValueError("max_response_chars must be an integer or 'auto'")
    if value < 2_000 or value > REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP:
        raise ValueError("max_response_chars must be between 2000 and 100000")
    return value


def resolve_batch_budget_args(
    *,
    max_total_passages: int,
    max_chars_per_passage: int,
    max_chars: int | str | None,
    max_response_chars: MaxResponseChars | str | None,
    verbosity: ReviewResponseVerbosity,
) -> ResolvedBatchBudgets:
    explicit_chars = max_chars is not None
    explicit_response = max_response_chars is not None and not _is_auto_response_budget(
        max_response_chars
    )
    effective_max_chars = (
        _coerce_max_chars(max_chars)
        if explicit_chars
        else min(
            REVIEW_BATCH_MAX_CHARS_CAP,
            max(
                REVIEW_BATCH_DEFAULT_MAX_CHARS,
                max_total_passages * max_chars_per_passage,
            ),
        )
    )
    effective_max_response_chars = resolve_max_response_chars(
        max_response_chars if max_response_chars is not None else "auto",
        verbosity=verbosity,
    )
    budget_source: BudgetSource = "caller" if explicit_chars or explicit_response else "auto_fit"
    return ResolvedBatchBudgets(
        max_chars=effective_max_chars,
        max_response_chars=effective_max_response_chars,
        budget_source=budget_source,
    )


def _is_auto_response_budget(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def _coerce_max_chars(value: int | str | None) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(value.strip())
    else:
        result = REVIEW_BATCH_DEFAULT_MAX_CHARS
    if result < 500 or result > REVIEW_BATCH_MAX_CHARS_CAP:
        raise ValueError("max_chars must be between 500 and 50000")
    return result
```

- [ ] **Step 5: Run resolver tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_context/budgets.py pubtator_link/models/review_rerag.py tests/unit/test_review_context_budgets.py
git commit -m "feat: add review response budget resolver"
```

## Task 9: Wire Auto Budgets And Verbosity Through Review MCP Tools

**Files:**
- Modify: `pubtator_link/mcp/input_normalization.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `tests/unit/mcp/test_mcp_input_normalization.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing normalization tests**

Add to `tests/unit/mcp/test_mcp_input_normalization.py`:

```python
def test_retrieve_batch_normalizes_verbosity_casing_and_auto_budget() -> None:
    normalized, warnings = normalize_retrieve_review_context_batch_args(
        {
            "queries": ["MEFV"],
            "verbosity": "Lean",
            "max_response_chars": "Auto",
        }
    )

    assert normalized["verbosity"] == "lean"
    assert normalized["max_response_chars"] == "auto"
    assert any(warning["field"] == "verbosity" for warning in warnings)
    assert any(warning["field"] == "max_response_chars" for warning in warnings)
```

- [ ] **Step 2: Write failing MCP adapter budget tests**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_accepts_auto_budget_and_verbosity() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class RecordingService:
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=request.budget_source,
            )

    service = RecordingService()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="review-1",
        queries=["MEFV"],
        verbosity="full",
        max_response_chars="auto",
    )

    assert service.request.verbosity == "full"
    assert service.request.max_response_chars == 60000
    assert service.request.budget_source == "auto_fit"


@pytest.mark.asyncio
async def test_ground_question_adapter_resolves_auto_budget_by_verbosity() -> None:
    from pubtator_link.mcp import service_adapters

    result, context_service = await _run_ground_question_fixture(
        service_adapters,
        verbosity="standard",
        max_response_chars="auto",
    )

    assert result["success"] is True
    assert context_service.retrieve_request.max_response_chars == 24000
    assert context_service.retrieve_request.verbosity == "standard"
```

Add `_run_ground_question_fixture()` above the new test by moving the fake client, queue, indexing service, and context service classes from `test_ground_question_adapter_chains_search_index_inspect_retrieve()` into that helper. The existing test and the new verbosity test should both call the helper.

- [ ] **Step 3: Write failing schema and route tests**

In `tests/unit/mcp/test_review_rerag_mcp.py`, add:

```python
def test_retrieve_batch_schema_exposes_verbosity_and_auto_response_budget() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["get_review_context_batch"].parameters

    assert schema["properties"]["verbosity"]["default"] == "standard"
    assert set(schema["properties"]["verbosity"]["enum"]) == {"lean", "standard", "full"}
    assert schema["properties"]["max_response_chars"]["default"] == "auto"
```

In `tests/unit/mcp/test_mcp_facade.py`, add:

```python
def test_ground_question_schema_exposes_verbosity_and_auto_budget() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["ground_question"]
    properties = tool.parameters["properties"]

    assert properties["verbosity"]["default"] == "lean"
    assert properties["max_response_chars"]["default"] == "auto"
```

In `tests/test_routes/test_reviews.py`, add:

```python
@pytest.mark.asyncio
async def test_retrieve_review_context_batch_route_accepts_auto_budget_and_verbosity() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.retrieve_context_batch.return_value = RetrieveReviewContextBatchResponse(
        review_id="rev_123",
        response_mode="compact",
        results=[],
        merged_context_pack=ContextPack(question="MEFV", passages=[], citation_map={}),
        preparation_status=PreparationStatus(complete=1),
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context/batch",
            json={
                "queries": ["MEFV"],
                "verbosity": "lean",
                "max_response_chars": "auto",
            },
        )

    assert response.status_code == 200
    request = service.retrieve_context_batch.await_args.kwargs["request"]
    assert request.verbosity == "lean"
    assert request.max_response_chars == "auto"
```

- [ ] **Step 4: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py -q -k "budget or verbosity or ground_question or retrieve_review_context_batch"
```

Expected: FAIL because MCP tools, adapters, normalization, and service budget resolution are not wired.

- [ ] **Step 5: Normalize verbosity and auto budget**

In `pubtator_link/mcp/input_normalization.py`, add:

```python
field_errors.extend(
    _normalize_enum_casing(
        normalized,
        warnings,
        field="verbosity",
        allowed_values={"lean", "standard", "full"},
    )
)
```

Add a small helper to canonicalize case-insensitive `"auto"` without coercing it to an integer:

```python
def _normalize_auto_literal(
    normalized: dict[str, Any],
    warnings: list[dict[str, str]],
    *,
    field: str,
) -> None:
    value = normalized.get(field)
    if not isinstance(value, str):
        return
    if value.strip().lower() != "auto":
        return
    if value == "auto":
        return
    normalized[field] = "auto"
    warnings.append(_warning(field, field, f"Normalized '{field}' auto casing."))
```

Call it from `normalize_retrieve_review_context_batch_args()`:

```python
_normalize_auto_literal(normalized, warnings, field="max_response_chars")
```

- [ ] **Step 6: Use resolver in batch adapter**

In `pubtator_link/mcp/service_adapters.py`, import:

```python
from pubtator_link.services.review_context.budgets import resolve_batch_budget_args
```

Change `retrieve_review_context_batch_impl()` signature:

```python
max_response_chars: int | Literal["auto"] | None = "auto",
verbosity: ReviewResponseVerbosity | str = "standard",
```

Add `verbosity` to the args dict. Replace `_review_batch_budget_args()` use with:

```python
resolved_budgets = resolve_batch_budget_args(
    max_total_passages=effective_max_total_passages,
    max_chars_per_passage=effective_max_chars_per_passage,
    max_chars=normalized_args.get("max_chars"),
    max_response_chars=normalized_args.get("max_response_chars", "auto"),
    verbosity=normalized_args.get("verbosity", "standard"),
)
```

Populate request args:

```python
"max_chars": resolved_budgets.max_chars,
"max_response_chars": resolved_budgets.max_response_chars,
"budget_source": resolved_budgets.budget_source,
"verbosity": normalized_args.get("verbosity", "standard"),
```

Remove duplicated batch budget constants and `_review_batch_budget_args()` if no call sites remain.

- [ ] **Step 7: Resolve auto budget in service for REST/direct callers**

In `ReviewContextService.retrieve_context_batch()`, at the start of the method, add:

```python
if isinstance(request.max_response_chars, str) and request.max_response_chars.lower() == "auto":
    resolved_budgets = resolve_batch_budget_args(
        max_total_passages=request.max_total_passages,
        max_chars_per_passage=request.max_chars_per_passage,
        max_chars=request.max_chars,
        max_response_chars=request.max_response_chars,
        verbosity=request.verbosity,
    )
    request = request.model_copy(
        update={
            "max_chars": resolved_budgets.max_chars,
            "max_response_chars": resolved_budgets.max_response_chars,
            "budget_source": resolved_budgets.budget_source,
        }
    )
```

Update `_effective_batch_budget_source()` to receive numeric `request.max_response_chars` after this resolution path.

- [ ] **Step 8: Wire MCP tool signatures**

In `pubtator_link/mcp/tools/review.py`, import `MaxResponseChars` and `ReviewResponseVerbosity`.

Change `retrieve_review_context_batch()` signature:

```python
max_response_chars: MaxResponseChars = "auto",
verbosity: ReviewResponseVerbosity = "standard",
```

Pass `verbosity=verbosity`.

Change `ground_question()` signature:

```python
verbosity: ReviewResponseVerbosity = "lean",
max_response_chars: MaxResponseChars = "auto",
```

Pass both into `ground_question_impl()`.

- [ ] **Step 9: Wire ground question resolver**

In `ground_question_impl()` in `pubtator_link/mcp/service_adapters.py`, add parameters:

```python
verbosity: ReviewResponseVerbosity | str = "lean",
max_response_chars: int | Literal["auto"] = "auto",
```

Before constructing `RetrieveReviewContextBatchRequest`, resolve:

```python
resolved_max_response_chars = resolve_max_response_chars(
    max_response_chars,
    verbosity=verbosity,
)
```

Set downstream request:

```python
verbosity=verbosity,
max_response_chars=resolved_max_response_chars,
```

- [ ] **Step 10: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_budgets.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py -q -k "budget or verbosity or ground_question or retrieve_review_context_batch"
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add pubtator_link/mcp/input_normalization.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review.py pubtator_link/services/review_context_service.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py tests/test_routes/test_reviews.py
git commit -m "feat: add auto review retrieval budgets"
```

## Task 10: Final Compatibility And CI Verification

**Files:**
- Modify only files already changed by Tasks 1-9 if verification reveals issues.

- [ ] **Step 1: Run graph-focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_tool_catalog.py tests/unit/test_literature_graph_compact.py tests/unit/test_citation_graph_service.py tests/unit/test_topic_literature_map_service.py tests/unit/test_related_evidence_service.py tests/test_routes/test_publication_literature_graph.py -q
```

Expected: PASS.

- [ ] **Step 2: Run inspect/review-focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_pagination.py tests/unit/test_review_context_budgets.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_review_rerag_mcp.py tests/test_routes/test_reviews.py -q
```

Expected: PASS.

- [ ] **Step 3: Run integration response-mode test**

Run:

```bash
uv run pytest tests/integration/test_mcp_response_modes.py -q
```

Expected: PASS.

- [ ] **Step 4: Run formatter and lint checks**

Run:

```bash
make format
make lint
```

Expected: both commands complete successfully.

- [ ] **Step 5: Run required full local CI**

Run:

```bash
make ci-local
```

Expected: PASS. Do not claim sprint completion until this command passes or every failure is documented with root cause and owner.

- [ ] **Step 6: Commit final verification fixes if any were required**

If Step 4 or Step 5 required code or test changes, commit only those changes:

```bash
git add pubtator_link tests
git commit -m "fix: stabilize payload control checks"
```

If no files changed after Step 5, do not create an empty commit.

## Self-Review

- Spec coverage: Tasks 1-4 cover compact graph defaults, budgets, request signature metadata, empty topology handling, DOI-only collapse, and REST compatibility. Tasks 5-7 cover inspect pagination, cursor contract, global totals, page counts, omission counts, MCP recovery hints, and route coverage. Tasks 8-9 cover auto budgets, verbosity, explicit numeric compatibility, normalization, schema tests, and route behavior. Task 10 requires `make ci-local`.
- Red-flag scan: the plan contains concrete file paths, commands, expected results, and code snippets for each implementation step.
- Type consistency: `ReviewResponseVerbosity`, `MaxResponseChars`, `InspectReviewIndexCursor`, and response pagination field names are used consistently across model, service, adapter, route, and test tasks.
