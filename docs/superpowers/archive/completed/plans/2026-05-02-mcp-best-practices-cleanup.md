# MCP Best Practices Cleanup Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve PubTator-Link MCP usability for LLM clients by making discovery smaller, inputs more tolerant, failure modes truthful, review retrieval faster and less repetitive, and touched review/MCP code easier to maintain.

**Architecture:** Keep the MCP layer as a stable compatibility boundary. Make read-only search independent from review-session storage, move common LLM-facing contracts and normalization into small MCP helpers, shape batch retrieval in focused review-context helpers, and keep public imports backward compatible while extracting only code paths touched by this work.

**Tech Stack:** Python 3.11, FastMCP, Pydantic v2, pytest, Ruff, mypy, PubTator3, NCBI E-utilities, asyncpg.

---

## Existing Plan Review

The previous draft had the right product direction but needs these corrections before implementation:

- It overreached by creating broad new modules such as `pubtator_link/services/review_context/response_shaping.py`, `pubtator_link/models/review_retrieval.py`, and `pubtator_link/mcp/service_adapters/search.py` without proving they are needed. This revised plan creates only small MCP helper modules up front and makes larger splits conditional after tests pass.
- It referenced non-existent test files such as `tests/unit/mcp/test_mcp_capabilities.py`, `tests/unit/mcp/test_mcp_contracts.py`, `tests/unit/mcp/test_mcp_input_normalization.py`, and `tests/unit/mcp/test_mcp_error_contract.py` as if they already existed. This plan creates them explicitly.
- It used imaginary fixtures like `mcp_facade`, `diagnostics_service`, and `review_context_service`. This plan follows existing patterns: direct adapter tests in `tests/unit/mcp/test_mcp_service_adapters.py`, model/resource tests in `tests/unit/mcp/test_mcp_facade.py`, and service-level fake repositories in existing unit tests.
- It proposed broad cleanup beyond the requested touched files. This revision limits cleanup to `pubtator_link/mcp/service_adapters.py`, `pubtator_link/models/review_rerag.py`, `pubtator_link/mcp/tools/review.py`, and `pubtator_link/services/review_context_service.py`, plus narrowly required helper modules.
- It treated benchmark artifacts as a planning source. Benchmarks under `benchmarks/` remain local-only, gitignored, and optional validation only.

## File Structure

Create:

- `pubtator_link/mcp/contracts.py` - slim tool categories, preferred tool names, detail blocks for sample calls and schema policy.
- `pubtator_link/mcp/input_normalization.py` - pure helpers for tolerant LLM input aliases and `_meta.normalized_arguments` warnings.
- `tests/unit/mcp/test_mcp_contracts.py` - capabilities size/detail, preferred naming, guideline-search contract.
- `tests/unit/mcp/test_mcp_input_normalization.py` - pure normalization tests.

Modify:

- `pubtator_link/mcp/metadata.py` - add `details` parameter to `pubtator.get_server_capabilities`.
- `pubtator_link/mcp/resources.py` - slim default capabilities and opt-in detail assembly.
- `pubtator_link/mcp/errors.py` - recent MCP error recording and structured field-error helpers.
- `pubtator_link/mcp/tools/literature.py` - read-only default search, guideline-search description, input normalization where compatible.
- `pubtator_link/mcp/tools/review.py` - tolerant argument normalization, compact diagnostics defaults, audit export options, optional preferred aliases if compatible.
- `pubtator_link/mcp/service_adapters.py` - search read-only behavior, review indexing preflight handoff, audit export fallback, batch adapter normalization/meta; optional local extraction only for touched sections.
- `pubtator_link/models/review_rerag.py` - source preflight summary, batch diagnostics object, matched query fields, quote mode models, audit export errors.
- `pubtator_link/services/diagnostics.py` - truthful dependency status using schema, queue, and recent MCP errors.
- `pubtator_link/services/ncbi_discovery.py` - NBK extraction and GeneReviews PMID recovery through existing discovery APIs.
- `pubtator_link/services/review_indexing.py` - Bookshelf URL rejection and source coverage preflight summary before enqueue.
- `pubtator_link/services/review_context/batch_budgeting.py` - dedupe by `passage_id` with `matched_queries`, no duplicate-drop noise in compact mode.
- `pubtator_link/services/review_context/diagnostics.py` - batch diagnostics composition if a small helper is enough.
- `pubtator_link/services/review_context_service.py` - orchestrate compact/diagnostics/quotes response modes without duplicating shaping logic.
- `pubtator_link/services/workflow_help.py` - GeneReviews/NBK example and guideline-search clarification.
- `tests/unit/mcp/test_mcp_facade.py`
- `tests/unit/mcp/test_mcp_service_adapters.py`
- `tests/unit/mcp/test_review_rerag_mcp.py`
- `tests/unit/test_diagnostics_service.py`
- `tests/unit/test_ncbi_discovery_service.py`
- `tests/unit/test_review_indexing.py`
- `tests/unit/test_review_context_batch_budgeting.py`
- `tests/unit/test_review_context_service.py`
- `tests/unit/test_review_rerag_models.py`
- `tests/unit/test_workflow_help.py`

Do not modify `benchmarks/` except for optional local runs. Do not add benchmark outputs to git.

---

### Task 1: Make `search_literature` Read-Only By Default

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add a failing adapter test proving search does not call preflight by default**

Append to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_search_literature_default_does_not_require_preflight_service() -> None:
    from pubtator_link.mcp.service_adapters import search_literature_impl

    class FakeClient:
        async def search_publications(self, **kwargs):
            return {"results": [{"pmid": "123", "title": "MEFV colchicine"}], "count": 1}

    class ExplodingPreflight:
        async def preflight_pmids(self, pmids):
            raise RuntimeError("review database unavailable")

    result = await search_literature_impl(
        client=FakeClient(),
        text="MEFV colchicine",
        coverage="none",
        preflight_service=ExplodingPreflight(),
        metadata="none",
        metadata_service=None,
    )

    assert result["success"] is True
    assert result["results"]
    assert "review database unavailable" not in str(result).lower()
```

- [ ] **Step 2: Add a schema/default test**

In `tests/unit/mcp/test_mcp_facade.py`, update the existing search schema assertions so `pubtator.search_literature` defaults to `coverage="none"` while still allowing `"preflight"` as an opt-in enum value.

- [ ] **Step 3: Run the expected failing tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "search_literature or search_schema"`

Expected before implementation: the schema/default test fails because `coverage` currently defaults to `"preflight"` in `pubtator_link/mcp/tools/literature.py`.

- [ ] **Step 4: Implement the minimal change**

Change `search_literature` in `pubtator_link/mcp/tools/literature.py` so:

```python
coverage: SearchCoverageMode = "none"
```

Keep `search_literature_impl` able to use `coverage="preflight"` when explicitly requested.

- [ ] **Step 5: Add read-only guidance to the returned payload**

In `search_literature_impl`, immediately after the call to `shaped_search_response`, add or update response metadata without requiring review storage:

```python
response.meta["coverage_note"] = (
    "Search is read-only metadata discovery. Use coverage='preflight' or "
    "pubtator.preflight_review_sources before indexing if source coverage matters."
)
response.meta["next_commands"] = [
    {"tool": "pubtator.preflight_review_sources", "arguments": {"pmids": response.candidate_pmids}},
    {"tool": "pubtator.index_review_evidence", "arguments": {"pmids": response.candidate_pmids}},
]
```

Adapt the exact attribute names to the existing `SearchResponse` model in `pubtator_link/models/responses.py`; do not introduce an untyped dict if the model already exposes `_meta`.

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "search_literature or search_schema"`

Expected after implementation: search works without a writable review database by default, and `coverage="preflight"` remains opt-in.

---

### Task 2: Make Diagnostics Reflect Real MCP Failures

**Files:**
- Modify: `pubtator_link/mcp/errors.py`
- Modify: `pubtator_link/services/diagnostics.py`
- Test: `tests/unit/test_diagnostics_service.py`
- Test: `tests/unit/test_mcp_errors.py`

- [ ] **Step 1: Add recent-error recorder tests**

Append to `tests/unit/test_mcp_errors.py`:

```python
def test_recent_mcp_errors_are_bounded_and_clearable() -> None:
    from pubtator_link.mcp.errors import clear_recent_mcp_errors, get_recent_mcp_errors, record_mcp_error

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator.index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
        raw_message="relation review_sources does not exist",
    )

    errors = get_recent_mcp_errors()

    assert errors[-1]["tool_name"] == "pubtator.index_review_evidence"
    assert errors[-1]["error_code"] == "review_index_unavailable"
    assert "relation review_sources does not exist" in errors[-1]["raw_message"]
```

- [ ] **Step 2: Add truthful diagnostics tests**

Append to `tests/unit/test_diagnostics_service.py`:

```python
@pytest.mark.asyncio
async def test_diagnostics_reports_recent_review_database_tool_error() -> None:
    from pubtator_link.mcp.errors import clear_recent_mcp_errors, record_mcp_error

    clear_recent_mcp_errors()
    record_mcp_error(
        tool_name="pubtator.index_review_evidence",
        error_code="review_index_unavailable",
        message="Review database operation failed.",
        raw_message="relation review_sources does not exist",
    )

    async def inspect_schema() -> ReviewSchemaDiagnostics:
        return ReviewSchemaDiagnostics(connected=True, current=True)

    service = DiagnosticsService(
        inspect_schema=inspect_schema,
        review_queue_available=lambda: True,
        europe_pmc_enabled=lambda: False,
    )

    response = await service.get_diagnostics()

    assert response.status == "degraded"
    assert response.subsystems["recent_mcp_errors"]["count"] == 1
    assert response.subsystems["recent_mcp_errors"]["latest"][0]["error_code"] == "review_index_unavailable"
    assert any("pubtator.index_review_evidence" in item for item in response.recovery)
```

- [ ] **Step 3: Run expected failing tests**

Run: `uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_diagnostics_service.py -q`

Expected before implementation: imports for `record_mcp_error`, `get_recent_mcp_errors`, or `clear_recent_mcp_errors` fail.

- [ ] **Step 4: Implement bounded recent-error storage**

In `pubtator_link/mcp/errors.py`, add pure functions:

```python
RECENT_MCP_ERROR_LIMIT = 50
_RECENT_MCP_ERRORS: list[dict[str, Any]] = []

def record_mcp_error(
    *,
    tool_name: str,
    error_code: str,
    message: str,
    raw_message: str | None = None,
) -> None:
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "tool_name": tool_name,
        "error_code": error_code,
        "message": message,
        "raw_message": raw_message[:500] if raw_message else None,
    }
    _RECENT_MCP_ERRORS.append(entry)
    del _RECENT_MCP_ERRORS[:-RECENT_MCP_ERROR_LIMIT]

def get_recent_mcp_errors(limit: int = 10) -> list[dict[str, Any]]:
    return [dict(item) for item in _RECENT_MCP_ERRORS[-limit:]]

def clear_recent_mcp_errors() -> None:
    _RECENT_MCP_ERRORS.clear()
```

Replace the function bodies with concrete implementations that append an ISO timestamp, `tool_name`, `error_code`, sanitized `message`, and bounded `raw_message`, trim `_RECENT_MCP_ERRORS` to `RECENT_MCP_ERROR_LIMIT`, return a copy of the latest errors, and clear the list for test isolation. Call `record_mcp_error` from `run_mcp_tool` for both `ToolError` and generic exceptions.

- [ ] **Step 5: Include recent errors in diagnostics status**

In `DiagnosticsService.get_diagnostics`, import `get_recent_mcp_errors` and add:

```python
recent_errors = get_recent_mcp_errors()
subsystems["recent_mcp_errors"] = {"count": len(recent_errors), "latest": recent_errors}
```

If there is any recent error with a tool name starting `pubtator.index_review`, `pubtator.stage_research_session`, `pubtator.retrieve_review_context`, or `pubtator.export_review_audit_bundle`, return `status="degraded"` even when schema inspection is green. Add a recovery line pointing to the exact failing tool and raw reason.

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_diagnostics_service.py -q`

Expected after implementation: diagnostics no longer says `ready` immediately after a review DB tool failure.

---

### Task 3: Slim `get_server_capabilities` With Opt-In Details

**Files:**
- Create: `pubtator_link/mcp/contracts.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/metadata.py`
- Test: `tests/unit/mcp/test_mcp_contracts.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Create failing contract tests**

Create `tests/unit/mcp/test_mcp_contracts.py`:

```python
from __future__ import annotations

import json

from pubtator_link.mcp.resources import get_capabilities_resource


def test_default_capabilities_are_small_and_skeletal() -> None:
    payload = get_capabilities_resource()
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    assert len(serialized) <= 2500
    assert payload["core_workflow_tools"]
    assert payload["tool_categories"]
    assert "sample_calls" not in payload
    assert "schema_policy" not in payload
    assert "recommended_workflows" not in payload


def test_capabilities_details_are_opt_in() -> None:
    payload = get_capabilities_resource(details=["sample_calls", "schema_policy"])

    assert payload["details"]["sample_calls"]["pubtator.search_literature"]["text"]
    assert "singleton string" in payload["details"]["schema_policy"]["list_inputs"].lower()
```

- [ ] **Step 2: Add tool schema test for the `details` argument**

In `tests/unit/mcp/test_mcp_facade.py`, add:

```python
def test_get_server_capabilities_accepts_details_argument() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.get_server_capabilities"]
    properties = tool.parameters["properties"]

    assert "details" in properties
    assert properties["details"]["default"] is None
```

- [ ] **Step 3: Run expected failing tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_contracts.py tests/unit/mcp/test_mcp_facade.py -q -k "capabilities"`

Expected before implementation: default capabilities exceed 2.5 KB and `details` is not in the tool schema.

- [ ] **Step 4: Add contract constants**

Create `pubtator_link/mcp/contracts.py` with:

```python
CORE_WORKFLOW_TOOLS = [
    "pubtator.workflow_help",
    "pubtator.search_literature",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context_batch",
    "pubtator.diagnostics",
]

TOOL_CATEGORIES = {
    "discovery": ["pubtator.search_literature", "pubtator.lookup_citation", "pubtator.convert_article_ids"],
    "review": ["pubtator.preflight_review_sources", "pubtator.index_review_evidence", "pubtator.inspect_review_index"],
    "retrieval": ["pubtator.retrieve_review_context_batch", "pubtator.get_review_passages_by_id", "pubtator.get_review_audit_trail"],
    "diagnostics": ["pubtator.diagnostics"],
}
```

Add compact `SAMPLE_CALLS`, `SCHEMA_POLICY`, and `PREFERRED_TOOL_NAMES` constants in the same file.

- [ ] **Step 5: Slim resources and add progressive detail**

Change `get_capabilities_resource(details: list[str] | None = None)` to return only `server`, `transport`, `endpoint`, `research_use_only`, `core_workflow_tools`, `tool_categories`, and `next_tool` by default. Add selected blocks under `details` only when requested.

- [ ] **Step 6: Update the MCP tool signature**

Change `get_server_capabilities` in `pubtator_link/mcp/metadata.py`:

```python
async def get_server_capabilities(details: list[str] | None = None) -> dict[str, Any]:
    return get_capabilities_resource(details=details)
```

- [ ] **Step 7: Verify**

Run: `uv run pytest tests/unit/mcp/test_mcp_contracts.py tests/unit/mcp/test_mcp_facade.py -q -k "capabilities"`

Expected after implementation: default serialized capabilities are below 2.5 KB; sample calls and schema policy are opt-in.

---

### Task 4: Normalize Common LLM Input Mistakes At The MCP Boundary

**Files:**
- Create: `pubtator_link/mcp/input_normalization.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_input_normalization.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Create pure normalization tests**

Create `tests/unit/mcp/test_mcp_input_normalization.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link.mcp.input_normalization import (
    InputNormalizationError,
    normalize_retrieve_review_context_batch_args,
)


def test_normalizes_query_alias_to_queries_list() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "query": "MEFV colchicine"}
    )

    assert args["queries"] == ["MEFV colchicine"]
    assert warnings[0]["field"] == "query"


def test_normalizes_limit_alias_to_max_total_passages() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "queries": ["MEFV"], "limit": 5}
    )

    assert args["max_total_passages"] == 5
    assert warnings[0]["field"] == "limit"


def test_normalizes_enum_casing() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "queries": "MEFV", "response_mode": "Quotes"}
    )

    assert args["queries"] == ["MEFV"]
    assert args["response_mode"] == "quotes"
    assert {warning["field"] for warning in warnings} == {"queries", "response_mode"}


def test_rejects_ambiguous_query_and_queries() -> None:
    with pytest.raises(InputNormalizationError) as error:
        normalize_retrieve_review_context_batch_args(
            {"review_id": "r1", "query": "a", "queries": ["b"]}
        )

    assert error.value.field_errors[0]["field"] == "queries"
```

- [ ] **Step 2: Run expected failing tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_input_normalization.py -q`

Expected before implementation: module import fails.

- [ ] **Step 3: Implement pure helper module**

In `pubtator_link/mcp/input_normalization.py`, implement:

```python
class InputNormalizationError(ValueError):
    def __init__(self, field_errors: list[dict[str, str]], recovery_hint: str) -> None:
        super().__init__("invalid MCP arguments")
        self.field_errors = field_errors
        self.recovery_hint = recovery_hint

def normalize_retrieve_review_context_batch_args(
    args: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    normalized = dict(args)
    warnings: list[dict[str, str]] = []
    # Fill in the alias and enum rules listed below.
    return normalized, warnings

def attach_normalization_meta(
    result: dict[str, Any],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    if warnings:
        meta = result.setdefault("_meta", {})
        meta["normalized_arguments"] = warnings
    return result
```

Supported aliases only:

- `query` or `question` -> `queries=["the provided query text"]`
- singleton string -> one-item list for `queries`, `pmids`, `entity_ids`, `sections`, `prioritize_pmids`
- `limit` or `size` -> `max_total_passages`
- case-insensitive enum normalization for `response_mode`, `budget_strategy`, and `table_mode`

Reject ambiguous calls with field errors instead of guessing.

- [ ] **Step 4: Wire normalization in the batch adapter without changing FastMCP schema**

In `retrieve_review_context_batch_impl`, normalize a local dict built from the function arguments before constructing `RetrieveReviewContextBatchRequest`. Add `_meta.normalized_arguments` warnings to the returned dict when normalization occurred.

- [ ] **Step 5: Add adapter coverage**

Append to `tests/unit/mcp/test_mcp_service_adapters.py` a fake service test for the adapter boundary. Change `retrieve_review_context_batch_impl` to accept `queries: list[str] | str` and optional `limit: int | None = None`, then call `retrieve_review_context_batch_impl(service=Service(), review_id="r1", queries="MEFV", response_mode="Quotes", limit=3)`. The expected assertion is:

```python
assert result["_meta"]["normalized_arguments"]
assert captured_request.queries == ["MEFV"]
assert captured_request.response_mode == "quotes"
assert captured_request.max_total_passages == 3
```

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/mcp/test_mcp_input_normalization.py tests/unit/mcp/test_mcp_service_adapters.py -q -k "normaliz or retrieve_review_context_batch"`

Expected after implementation: common LLM mistakes are normalized with visible `_meta` warnings; ambiguous inputs return structured field errors.

---

### Task 5: Add GeneReviews/NBK Recovery And Bookshelf Rejection

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: `pubtator_link/models/discovery.py`
- Modify: `pubtator_link/services/review_indexing.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: `tests/unit/test_review_indexing.py`
- Test: `tests/unit/test_workflow_help.py`

- [ ] **Step 1: Add NBK extraction and lookup tests**

Append to `tests/unit/test_ncbi_discovery_service.py`:

```python
@pytest.mark.asyncio
async def test_lookup_citation_extracts_nbk_and_adds_recovery_hint() -> None:
    class Client(FakeDiscoveryClient):
        async def lookup_citations(self, citations):
            assert citations == ["GeneReviews NBK1139 familial Mediterranean fever"]
            return [CitationLookupRecord(citation=citations[0], status="not_found", reason="not_found")]

        async def convert_article_ids(self, ids, source):
            assert ids == ["NBK1139"]
            return [ArticleIdConversionRecord(input_id="NBK1139", input_kind="auto", status="unresolved", reason="not_found")]

    service = DiscoveryService(Client())

    response = await service.lookup_citation(["https://www.ncbi.nlm.nih.gov/books/NBK1139/"])

    assert response.records[0].reason in {"nbk_not_mapped", "not_found"}
    assert response.meta.next_commands
    assert "NBK1139" in str(response.meta.next_commands)
```

If the real NCBI converter cannot resolve NBK IDs directly, the implementation should still return a deterministic recovery hint and should not fabricate a PMID.

- [ ] **Step 2: Add Bookshelf URL rejection test**

Append to `tests/unit/test_review_indexing.py`:

```python
@pytest.mark.asyncio
async def test_index_rejects_bookshelf_url_before_enqueue() -> None:
    service = ReviewIndexingService(repository=FakeIndexRepository(), queue=FakeQueue())

    with pytest.raises(ValueError, match="bookshelf_url_not_indexable"):
        await service.index_review_evidence(
            "review-1",
            IndexReviewEvidenceRequest(
                curated_urls=["https://www.ncbi.nlm.nih.gov/books/NBK1139/"]
            ),
        )
```

- [ ] **Step 3: Add workflow help test**

Append to `tests/unit/test_workflow_help.py`:

```python
def test_workflow_help_mentions_genereviews_nbk_recovery() -> None:
    payload = WorkflowHelpService().get_help("clinical_genetics_review").model_dump_json()

    assert "GeneReviews" in payload
    assert "NBK" in payload
    assert "lookup_citation" in payload
```

- [ ] **Step 4: Run expected failing tests**

Run: `uv run pytest tests/unit/test_ncbi_discovery_service.py tests/unit/test_review_indexing.py tests/unit/test_workflow_help.py -q -k "nbk or Bookshelf or GeneReviews or workflow"`

Expected before implementation: NBK behavior and workflow assertions fail.

- [ ] **Step 5: Implement NBK detection**

In `pubtator_link/services/ncbi_discovery.py`, add a small helper:

```python
NBK_RE = re.compile(r"\bNBK\d+\b", re.IGNORECASE)

def extract_nbk_ids(values: Sequence[str]) -> list[str]:
    ids: list[str] = []
    for value in values:
        ids.extend(match.group(0).upper() for match in NBK_RE.finditer(value))
    return list(dict.fromkeys(ids))
```

In `DiscoveryService.lookup_citation`, when an NBK ID or Bookshelf URL is present:

- preserve normal citation lookup
- attempt `convert_article_ids([nbk_id], "auto")` if supported by the injected client protocol
- add `_meta.next_commands` with a recovery call to `pubtator.lookup_citation` and, when a PMID is resolved, `pubtator.index_review_evidence`
- mark unresolved NBK records with a clear reason such as `nbk_not_mapped`

- [ ] **Step 6: Reject Bookshelf URLs before enqueue**

In `ReviewIndexingService.index_review_evidence`, inspect `request.curated_urls` before `_source_specs(request)`. Raise `ValueError("bookshelf_url_not_indexable: NBK1139; call pubtator.lookup_citation with the NBK ID and index the returned PMID")`.

Task 8 will convert this into field errors at the MCP boundary.

- [ ] **Step 7: Add workflow example**

In `WorkflowHelpService`, include a concise GeneReviews example:

```text
GeneReviews/NBK: do not index NCBI Bookshelf URLs directly. Call pubtator.lookup_citation with the NBK ID, then index the returned PMID when available.
```

- [ ] **Step 8: Verify**

Run: `uv run pytest tests/unit/test_ncbi_discovery_service.py tests/unit/test_review_indexing.py tests/unit/test_workflow_help.py -q -k "nbk or Bookshelf or GeneReviews or workflow"`

Expected after implementation: Bookshelf URLs fail fast with recovery guidance; NBK lookups expose a PMID when available or a truthful not-found path.

---

### Task 6: Surface Source Coverage Early In `index_review_evidence`

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_indexing.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_review_indexing.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Add model fields test**

Append to `tests/unit/test_review_rerag_models.py`:

```python
def test_index_review_evidence_response_exposes_source_preflight_summary() -> None:
    from pubtator_link.models.review_rerag import IndexReviewEvidenceResponse, PreparationStatus

    response = IndexReviewEvidenceResponse(
        review_id="r1",
        queued=0,
        already_prepared=0,
        preparation_status=PreparationStatus(),
        source_preflight_summary={
            "total_sources": 2,
            "full_text": 1,
            "abstract_only": 1,
            "title_only": 0,
            "failed": 0,
        },
        source_preflight_message="1/2 sources full_text, 1/2 abstract_only, 0/2 title_only, 0/2 failed.",
    )

    assert response.source_preflight_summary["abstract_only"] == 1
    assert "abstract_only" in response.source_preflight_message
```

- [ ] **Step 2: Add service dry-run coverage test**

Append to `tests/unit/test_review_indexing.py` using the fake repository method shown here:

```python
@pytest.mark.asyncio
async def test_index_includes_source_coverage_summary_before_enqueue() -> None:
    class Repository(FakeIndexRepository):
        async def source_coverage_summary(self, review_id, source_ids):
            return {
                "total_sources": 2,
                "full_text": 1,
                "abstract_only": 1,
                "title_only": 0,
                "failed": 0,
            }

    service = ReviewIndexingService(repository=Repository(), queue=FakeQueue())

    response = await service.index_review_evidence(
        "review-1",
        IndexReviewEvidenceRequest(pmids=["1", "2"], dry_run=True),
    )

    assert response.source_preflight_summary["total_sources"] == 2
    assert "abstract_only" in response.source_preflight_message
```

- [ ] **Step 3: Run expected failing tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_indexing.py -q -k "source_preflight or coverage_summary"`

Expected before implementation: `IndexReviewEvidenceResponse` lacks source preflight fields.

- [ ] **Step 4: Add bounded response fields**

In `IndexReviewEvidenceResponse`, add:

```python
source_preflight_summary: dict[str, int] = Field(default_factory=dict)
source_preflight_message: str | None = None
source_preflight_warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Compute available coverage before enqueue**

In `ReviewIndexingService`, add an optional protocol method check:

```python
coverage_summary_fn = getattr(self.repository, "source_coverage_summary", None)
```

If present, call it before enqueue and include counts for `full_text`, `abstract_only`, `title_only`, and `failed`. If absent, return `{}` and do not block indexing.

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_indexing.py tests/unit/mcp/test_mcp_service_adapters.py -q -k "index_review_evidence or source_preflight or coverage_summary"`

Expected after implementation: `index_review_evidence` surfaces source coverage when available and remains backward compatible when the repository cannot provide it.

---

### Task 7: Deduplicate Batch Retrieval By Passage And Collapse Diagnostics

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Change the existing duplicate test to require `matched_queries`**

Update `test_merge_batch_context_deduplicates_passages` in `tests/unit/test_review_context_batch_budgeting.py`:

```python
assert [passage.passage_id for passage in merged.passages] == ["p1"]
assert merged.passages[0].matched_queries == ["q1", "q2"]
assert all(drop.reason != "duplicate_passage" for drop in merged.dropped)
assert merged.dropped_summary.by_reason.get("duplicate_passage", 0) == 0
```

- [ ] **Step 2: Add compact diagnostics gating test**

Append to `tests/unit/test_review_context_batch_budgeting.py` or `tests/unit/test_review_context_service.py`:

```python
def test_compact_batch_response_omits_diagnostics_when_not_requested() -> None:
    response = RetrieveReviewContextBatchResponse(
        review_id="r1",
        response_mode="compact",
        include_diagnostics=False,
        results=[],
        merged_context_pack=ContextPack(question="q1", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
        query_summaries=[],
        source_budget_summaries=[],
        pmid_status_summary=[],
    )

    dumped = response.model_dump(exclude_none=True, exclude_defaults=True)

    assert "query_summaries" not in dumped
    assert "source_budget_summaries" not in dumped
    assert "pmid_status_summary" not in dumped
    assert "diagnostics" not in dumped
```

- [ ] **Step 3: Run expected failing tests**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q -k "deduplicates or diagnostics or batch"`

Expected before implementation: duplicate accounting still appears as dropped passages, and batch response diagnostics are top-level by default.

- [ ] **Step 4: Add matched-query fields**

In `ContextPassage`, add:

```python
matched_queries: list[str] = Field(default_factory=list)
matched_query_indices: list[int] = Field(default_factory=list)
```

- [ ] **Step 5: Update merge behavior**

In `merge_batch_context`, replace duplicate drops with aggregation:

- when first adding a passage, set `matched_queries=[request.queries[query_index]]` and `matched_query_indices=[query_index]`
- when a duplicate `passage_id` appears, find the existing merged passage and append the query/index if not present
- do not append `ContextDropReason(reason="duplicate_passage")` for compact/default mode

- [ ] **Step 6: Add one batch diagnostics object**

In `review_rerag.py`, add:

```python
class RetrieveReviewBatchDiagnostics(BaseModel):
    query_summaries: list[QueryDiagnosticsSummary] = Field(default_factory=list)
    source_budget_summaries: list[SourceBudgetSummary] = Field(default_factory=list)
    pmid_status_summary: list[PmidStatusSummary] = Field(default_factory=list)
    dropped_summary: SourceDroppedSummary | dict[str, int] = Field(default_factory=dict)
```

In `RetrieveReviewContextBatchResponse`, add:

```python
include_diagnostics: bool = False
diagnostics: RetrieveReviewBatchDiagnostics | None = None
```

Update the serializer to omit top-level `query_summaries`, `source_budget_summaries`, and `pmid_status_summary` when `include_diagnostics` is false and `response_mode != "diagnostics"`.

- [ ] **Step 7: Populate diagnostics only when requested**

In `ReviewContextService.retrieve_context_batch`, pass `include_diagnostics=request.include_diagnostics or request.response_mode == "diagnostics"` into the response and populate the new `diagnostics` block only in that case. Change the default `RetrieveReviewContextBatchRequest.include_diagnostics` from `True` to `False`.

- [ ] **Step 8: Update schema tests**

Update `tests/unit/mcp/test_mcp_facade.py` and `tests/unit/mcp/test_review_rerag_mcp.py` so `pubtator.retrieve_review_context_batch` now defaults `include_diagnostics` to `False`.

- [ ] **Step 9: Verify**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q -k "batch or retrieve_review_context"`

Expected after implementation: compact batch retrieval returns one passage per `passage_id`, carries `matched_queries`, and emits a single diagnostics block only when requested.

---

### Task 8: Add `response_mode="quotes"`

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Add model and schema tests**

Append to `tests/unit/test_review_rerag_models.py`:

```python
def test_batch_response_accepts_quotes_mode() -> None:
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
        ReviewQuote,
    )

    response = RetrieveReviewContextBatchResponse(
        review_id="r1",
        response_mode="quotes",
        results=[],
        merged_context_pack=ContextPack(question="q1", passages=[], citation_map={}),
        preparation_status=PreparationStatus(),
        quotes=[
            ReviewQuote(
                stable_citation_key="c_abc",
                pmid="123",
                passage_id="PMID:123:abstract:1",
                section="abstract",
                quote="MEFV evidence.",
                matched_queries=["MEFV"],
                coverage_status="abstract_only",
            )
        ],
    )

    assert response.quotes[0].stable_citation_key == "c_abc"
```

Append to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
def test_batch_response_mode_schema_includes_quotes() -> None:
    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["pubtator.retrieve_review_context_batch"].parameters

    assert "quotes" in schema["properties"]["response_mode"]["enum"]
```

- [ ] **Step 2: Run expected failing tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py -q -k "quotes"`

Expected before implementation: `quotes` is not a valid mode and `ReviewQuote` does not exist.

- [ ] **Step 3: Add quote models**

In `review_rerag.py`:

```python
ReviewBatchResponseMode = Literal["compact", "merged_only", "full", "diagnostics", "quotes"]

class ReviewQuote(BaseModel):
    stable_citation_key: str
    pmid: str | None = None
    passage_id: str
    section: str
    quote: str = Field(max_length=350)
    matched_queries: list[str] = Field(default_factory=list)
    coverage_status: SourceCoverage = "unknown"
```

Add `quotes: list[ReviewQuote] = Field(default_factory=list)` to `RetrieveReviewContextBatchResponse`.

- [ ] **Step 4: Shape quote mode**

In `ReviewContextService.retrieve_context_batch`, when `request.response_mode == "quotes"`:

- still use `merge_batch_context` for ranking and dedupe
- return `merged_context_pack.passages=[]` to keep output short
- populate `quotes` from merged passages
- each quote must include `stable_citation_key`, `pmid`, `passage_id`, `section`, `quote`, `matched_queries`, and `coverage_status`

Use existing `passage.quote.text` if present; otherwise trim `passage.text` to a sentence or bounded 350-character window.

- [ ] **Step 5: Add quote shaping test**

Add to `tests/unit/test_review_context_batch_budgeting.py` or `tests/unit/test_review_context_service.py` a fake passage with long text and assert:

```python
assert response.response_mode == "quotes"
assert response.quotes
assert all(len(item.quote) <= 350 for item in response.quotes)
assert response.merged_context_pack.passages == []
```

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py -q -k "quote or batch"`

Expected after implementation: quote mode returns short citable snippets without long passage windows.

---

### Task 9: Make Audit Export Return Field Errors Or Inline JSON

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/errors.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add response model test**

Append to `tests/unit/test_review_rerag_models.py`:

```python
def test_audit_bundle_response_can_report_field_errors() -> None:
    from pubtator_link.models.review_rerag import McpReviewAuditBundleResponse

    response = McpReviewAuditBundleResponse(
        success=False,
        audit_bundle=None,
        error={
            "code": "validation_failed",
            "field_errors": [{"field": "export_path", "reason": "parent directory is not writable"}],
            "recovery_hint": "Use fallback_inline=True or choose a writable path.",
        },
    )

    assert response.error["field_errors"][0]["field"] == "export_path"
```

- [ ] **Step 2: Add adapter fallback tests**

Append to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_export_review_audit_bundle_adapter_returns_inline_fallback() -> None:
    from pubtator_link.mcp.service_adapters import export_review_audit_bundle_impl
    from pubtator_link.models.review_rerag import PreparationStatus, ReviewAuditBundle, ReviewIndexTotals

    class Service:
        async def export_bundle(self, review_id, session_id=None):
            return ReviewAuditBundle(
                review_id=review_id,
                session_id=session_id,
                generated_at="2026-05-02T00:00:00Z",
                preparation_status=PreparationStatus(),
                totals=ReviewIndexTotals(),
                sources=[],
                failed_sources=[],
                coverage_distribution={},
                resolver_attempts=[],
                passage_ids=[],
                stable_citation_keys={},
            )

    result = await export_review_audit_bundle_impl(
        service=Service(),
        review_id="r1",
        fallback_inline=True,
        export_path="/not/writable/audit.json",
    )

    assert result["success"] is True
    assert result["inline_bundle"] is not None
    assert result["export_path"] is None
```

- [ ] **Step 3: Add tool schema test**

In `tests/unit/mcp/test_mcp_facade.py`, assert `pubtator.export_review_audit_bundle` exposes optional `export_path` and `fallback_inline`.

- [ ] **Step 4: Run expected failing tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "audit_bundle or export"`

Expected before implementation: response model requires `audit_bundle`, adapter signature lacks export options, and schema lacks `fallback_inline`.

- [ ] **Step 5: Update model**

Change `McpReviewAuditBundleResponse`:

```python
success: bool = True
audit_bundle: ReviewAuditBundle | None = None
inline_bundle: dict[str, Any] | None = None
export_path: str | None = None
error: dict[str, Any] | None = None
```

- [ ] **Step 6: Implement adapter behavior**

Change `export_review_audit_bundle_impl` signature to accept:

```python
export_path: str | None = None
fallback_inline: bool = False
```

If `export_path` is supplied and cannot be written, return `success=False` with `field_errors` unless `fallback_inline=True`, in which case return `inline_bundle=bundle.model_dump(mode="json")`. Keep inline output bounded; if too large, return `code="export_unavailable"` with a recovery hint.

- [ ] **Step 7: Update MCP tool signature**

Expose `export_path` and `fallback_inline` in `pubtator_link/mcp/tools/review.py`.

- [ ] **Step 8: Verify**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "audit_bundle or export"`

Expected after implementation: validation failures include field errors, and file-export failure can fall back to inline JSON.

---

### Task 10: Clarify Guideline Search And Preferred Tool Names

**Files:**
- Modify: `pubtator_link/mcp/contracts.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/mcp/test_mcp_contracts.py`
- Test: `tests/unit/test_workflow_help.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add guideline contract test**

Append to `tests/unit/mcp/test_mcp_contracts.py`:

```python
def test_capabilities_document_guideline_search_as_filtered_literature_search() -> None:
    payload = get_capabilities_resource(details=["sample_calls", "schema_policy"])
    text = json.dumps(payload).lower()

    assert "search_guidelines" in text
    assert "search_literature" in text
    assert "publication_types" in text
    assert "filtered" in text or "guideline" in text
```

- [ ] **Step 2: Add preferred naming test**

Append to `tests/unit/mcp/test_mcp_contracts.py`:

```python
def test_preferred_tool_names_are_documented_without_breaking_existing_names() -> None:
    payload = get_capabilities_resource(details=["schema_policy"])
    preferred = payload["details"]["schema_policy"]["preferred_tool_names"]

    assert preferred["retrieve_review_context_batch"] == "pubtator.retrieve_review_context_batch"
    assert "pubtator.retrieve_review_context_batch" in payload["core_workflow_tools"]
```

- [ ] **Step 3: Run expected failing tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_contracts.py tests/unit/test_workflow_help.py tests/unit/mcp/test_mcp_facade.py -q -k "guideline or preferred or tool_names"`

Expected before implementation: guideline relationship and preferred naming are not explicit in the slim contract.

- [ ] **Step 4: Clarify `search_guidelines` without removing it**

Keep `pubtator.search_guidelines` for backward compatibility. Update its docstring to state it is a convenience wrapper over `search_literature` with guideline/systematic-review publication-type filters and guideline boosting, not an independent guideline database.

- [ ] **Step 5: Document naming policy**

Do not rename existing tools in this task. In `contracts.py`, add:

```python
PREFERRED_TOOL_NAMES = {
    "search_literature": "pubtator.search_literature",
    "retrieve_review_context_batch": "pubtator.retrieve_review_context_batch",
    "index_review_evidence": "pubtator.index_review_evidence",
    "diagnostics": "pubtator.diagnostics",
}
```

Explain that the `pubtator.` prefix is retained for backward compatibility and to disambiguate in clients that do not include the MCP server name in display text. If future aliases are added, they must be additive only.

- [ ] **Step 6: Verify**

Run: `uv run pytest tests/unit/mcp/test_mcp_contracts.py tests/unit/test_workflow_help.py tests/unit/mcp/test_mcp_facade.py -q -k "guideline or preferred or capabilities"`

Expected after implementation: guideline search is explicitly documented as filtered literature search, and tool-name verbosity is documented without breaking registered names.

---

### Task 11: Clean Up Only Touched Large Code Paths

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Optional Create: `pubtator_link/mcp/review_tool_helpers.py`
- Optional Create: `pubtator_link/services/review_context/quotes.py`
- Test: existing tests changed above

- [ ] **Step 1: Snapshot sizes**

Run: `wc -l pubtator_link/mcp/service_adapters.py pubtator_link/models/review_rerag.py pubtator_link/mcp/tools/review.py pubtator_link/services/review_context_service.py`

Expected baseline from inspection:

```text
950 pubtator_link/mcp/service_adapters.py
928 pubtator_link/models/review_rerag.py
652 pubtator_link/mcp/tools/review.py
652 pubtator_link/services/review_context_service.py
```

- [ ] **Step 2: Extract only if a touched function becomes harder to read**

Allowed extractions:

- move quote shaping helpers from `review_context_service.py` to `pubtator_link/services/review_context/quotes.py`
- move normalization/field-error glue from `tools/review.py` to `pubtator_link/mcp/review_tool_helpers.py`
- move no unrelated publication, annotation, variant, or entity adapter functions

- [ ] **Step 3: Preserve public imports**

If any adapter helpers move out of `service_adapters.py`, re-export the same function names from `pubtator_link/mcp/service_adapters.py` so existing imports in tests and tool modules continue to work.

- [ ] **Step 4: Run focused import regression**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q`

Expected: all existing imports still resolve.

- [ ] **Step 5: Run line-count check again**

Run: `wc -l pubtator_link/mcp/service_adapters.py pubtator_link/models/review_rerag.py pubtator_link/mcp/tools/review.py pubtator_link/services/review_context_service.py`

Expected: no touched file grows substantially. At least one touched file should shrink if helper extraction was needed; otherwise the PR description should state why no extraction was justified.

---

### Task 12: End-To-End Verification And Optional Local Benchmark

**Files:**
- Modify: `README.md` only if the public workflow text is stale after implementation.
- Do not modify: `benchmarks/` or benchmark outputs.

- [ ] **Step 1: Run focused MCP/review suite**

Run:

```bash
uv run pytest \
  tests/unit/mcp \
  tests/unit/test_diagnostics_service.py \
  tests/unit/test_ncbi_discovery_service.py \
  tests/unit/test_review_indexing.py \
  tests/unit/test_review_context_batch_budgeting.py \
  tests/unit/test_review_context_service.py \
  tests/unit/test_review_rerag_models.py \
  tests/unit/test_workflow_help.py \
  -q
```

Expected: all focused MCP, diagnostics, discovery, indexing, batch retrieval, model, and workflow-help tests pass.

- [ ] **Step 2: Run required repo check**

Run: `make ci-local`

Expected: formatting, linting, mypy, and test suite pass.

- [ ] **Step 3: Optional benchmark validation**

If local benchmark validation is useful, run the existing ignored benchmark harness under `benchmarks/` and keep outputs untracked. Do not promote benchmark prompts, logs, or results into source code.

Expected qualitative checks:

- default `get_server_capabilities()` serializes to 1-2 KB, hard limit 2.5 KB
- `search_literature` works without writable review-session storage
- diagnostics reports recent review DB/tool failures as degraded
- compact batch retrieval is smaller and no longer reports duplicate passages as dropped evidence
- `response_mode="quotes"` returns short citable snippets
- NBK/GeneReviews path gives either a PMID recovery path or a truthful unresolved reason

## Completion Checklist

- [ ] `search_literature` is read-only by default and does not require writable review storage.
- [ ] Diagnostics include schema/connection/queue/recent-tool-error details and do not report ready after review DB failures.
- [ ] `get_server_capabilities()` defaults to a 1-2 KB skeleton with opt-in details.
- [ ] Batch retrieval deduplicates by `passage_id` and returns `matched_queries`.
- [ ] Batch diagnostics are collapsed into one diagnostics block and gated behind `include_diagnostics=True` or `response_mode="diagnostics"`.
- [ ] `export_review_audit_bundle` returns field errors or inline JSON fallback.
- [ ] `index_review_evidence` surfaces abstract-only/title-only/failed/full-text source coverage early when available.
- [ ] Tool-name verbosity is documented; existing `pubtator.` names remain backward compatible.
- [ ] `response_mode="quotes"` returns `stable_citation_key`, PMID, `passage_id`, `section`, quote, `matched_queries`, and `coverage_status`.
- [ ] `search_guidelines` is documented as a filtered/boosted literature search wrapper unless a truly distinct backend is added.
- [ ] GeneReviews/NBK IDs and NCBI Bookshelf URLs have explicit recovery behavior.
- [ ] Common LLM input mistakes are normalized with visible `_meta` warnings.
- [ ] Cleanup is limited to touched code paths.
- [ ] `make ci-local` passes.
