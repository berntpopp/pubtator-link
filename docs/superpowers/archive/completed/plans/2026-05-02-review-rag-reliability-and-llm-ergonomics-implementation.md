# Review RAG Reliability And LLM Ergonomics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make review RAG failures explicit, add bounded recovery diagnostics, improve source coverage fallback, and reduce LLM token waste in high-use MCP tools.

**Architecture:** Add small shared response-shaping helpers instead of scattering ad hoc fields through tools. Keep public models backward compatible by adding optional fields and new MCP arguments with existing defaults. Preserve current service boundaries: MCP tools call `service_adapters`, adapters call services, services own resolver and shaping behavior.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, FastMCP, asyncpg, httpx, pytest, Ruff, mypy, uv, Makefile, Docker Compose.

---

## File Structure

- Create `pubtator_link/services/degradation.py`: shared `degraded_mode` calculation and compact fallback preview helpers.
- Create `pubtator_link/services/mcp_diagnostics.py`: bounded diagnostics snapshot builder for MCP error envelopes.
- Modify `pubtator_link/mcp/errors.py`: accept diagnostics/degradation context and serialize `diagnostics_snapshot`, `degraded_mode`, and `fallback_preview`.
- Modify `pubtator_link/mcp/service_adapters.py`: pass degradation fields through publication passage/search/entity adapters; add dry-run and verbosity arguments.
- Modify `pubtator_link/mcp/tools/publications.py`: expose `dry_run` and `verbosity` on `pubtator.get_publication_passages`; expose `verbosity` on metadata.
- Modify `pubtator_link/mcp/tools/literature.py`: expose `verbosity`, adjust review-oriented citation defaults, and keep guideline defaults citation-rich.
- Modify `pubtator_link/mcp/tools/review.py`: expose `wait_until_ready` and `include_resolver_trace` on review indexing/retrieval tools.
- Modify `pubtator_link/models/publication_passages.py`: add `dry_run`, `verbosity`, `degraded_mode`, and resolver attempt response fields.
- Modify `pubtator_link/models/responses.py`: add `Verbosity`, optional `ranking_reasons`, and helper-friendly lean serialization fields.
- Modify `pubtator_link/models/review_rerag.py`: add inspect `coverage_summary`, batch response hygiene fields, wait alias, and resolver trace controls.
- Modify `pubtator_link/models/publication_metadata.py`: add `verbosity` where needed for metadata response shaping.
- Modify `pubtator_link/services/publication_passage_service.py`: implement dry-run response, degraded-mode summary, and lean/full response shaping.
- Modify `pubtator_link/services/full_text_preparation.py`: record structured resolver attempts and use Europe PMC/DOI-capable fallback before abstract fallback.
- Modify `pubtator_link/services/europe_pmc.py`: keep `EuropePmcLookupResult` metadata available to full-text preparation attempt recording.
- Modify `pubtator_link/services/search_shaping.py`: extend guideline ranking and add `ranking_reasons`.
- Modify `pubtator_link/services/entity_matching.py`: extract bounded synonyms from PubTator match text and upstream fields.
- Modify `pubtator_link/mcp/resources.py` and `docs/MCP_CONNECTION_GUIDE.md`: add tool categories and diagnostics workflow guidance; remove stale active `_v2`/`prepare_mode` guidance while keeping one cache-refresh compatibility note.
- Tests: `tests/unit/test_mcp_errors.py`, `tests/unit/test_publication_passage_service.py`, `tests/unit/mcp/test_mcp_service_adapters.py`, `tests/unit/mcp/test_mcp_facade.py`, `tests/unit/test_full_text_preparation.py`, `tests/unit/test_search_shaping.py`, `tests/unit/test_entity_matching.py`, `tests/unit/test_review_rerag_models.py`, `tests/unit/test_review_context_batch_budgeting.py`, `tests/unit/test_review_context_service.py`, `tests/unit/test_workflow_help.py`, `tests/unit/test_development_tooling.py`.

### Task 1: Degraded Mode Contract

**Files:**
- Create: `pubtator_link/services/degradation.py`
- Modify: `pubtator_link/models/publication_passages.py`
- Modify: `pubtator_link/services/publication_passage_service.py`
- Test: `tests/unit/test_publication_passage_service.py`

- [ ] **Step 1: Write failing degraded-mode helper tests**

Add to `tests/unit/test_publication_passage_service.py`:

```python
from pubtator_link.services.degradation import degraded_mode_from_coverage


def test_degraded_mode_from_coverage_prefers_most_severe_mode() -> None:
    assert degraded_mode_from_coverage({"1": "full_text", "2": "abstract_only"}) == "abstract_only"
    assert degraded_mode_from_coverage({"1": "title_only", "2": "abstract_only"}) == "metadata_only"
    assert degraded_mode_from_coverage({"1": "full_text"}) is None
    assert degraded_mode_from_coverage({}) is None
```

- [ ] **Step 2: Run test to verify red**

Run: `uv run pytest tests/unit/test_publication_passage_service.py::test_degraded_mode_from_coverage_prefers_most_severe_mode -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.services.degradation'`.

- [ ] **Step 3: Add degradation helper**

Create `pubtator_link/services/degradation.py`:

```python
from __future__ import annotations

from typing import Literal

DegradedMode = Literal["abstract_only", "metadata_only", "index_unavailable"]


def degraded_mode_from_coverage(coverage_by_pmid: dict[str, str]) -> DegradedMode | None:
    """Return the most severe user-visible degraded mode for source coverage."""
    values = set(coverage_by_pmid.values())
    if not values:
        return None
    if values <= {"full_text"}:
        return None
    if "title_only" in values or "unknown" in values:
        return "metadata_only"
    if "abstract_only" in values:
        return "abstract_only"
    return None
```

- [ ] **Step 4: Run helper test to verify green**

Run: `uv run pytest tests/unit/test_publication_passage_service.py::test_degraded_mode_from_coverage_prefers_most_severe_mode -q`

Expected: PASS.

- [ ] **Step 5: Write failing response-field test**

Add to `tests/unit/test_publication_passage_service.py` using the existing fixture helpers:

```python
@pytest.mark.asyncio
async def test_get_passages_sets_degraded_mode_for_abstract_only_response() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(PublicationPassageRequest(pmids=["111"]))

    assert response.coverage_by_pmid == {"111": "abstract_only"}
    assert response.degraded_mode == "abstract_only"
```

- [ ] **Step 6: Run response test to verify red**

Run: `uv run pytest tests/unit/test_publication_passage_service.py::test_get_passages_sets_degraded_mode_for_abstract_only_response -q`

Expected: FAIL because `PublicationPassageResponse` has no `degraded_mode`.

- [ ] **Step 7: Add model field and service assignment**

Modify `pubtator_link/models/publication_passages.py`:

```python
from pubtator_link.services.degradation import DegradedMode


degraded_mode: DegradedMode | None = None
```

Insert the field in `PublicationPassageResponse` after `source_versions`.

Modify both `PublicationPassageService.get_passages()` return paths in `pubtator_link/services/publication_passage_service.py`:

```python
from pubtator_link.services.degradation import degraded_mode_from_coverage

degraded_mode=degraded_mode_from_coverage(coverage_by_pmid),
```

For exception paths where coverage is `unknown`, build `coverage_by_pmid` with `"unknown"` and pass it through the same helper.

- [ ] **Step 8: Run focused publication passage tests**

Run: `uv run pytest tests/unit/test_publication_passage_service.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/services/degradation.py pubtator_link/models/publication_passages.py pubtator_link/services/publication_passage_service.py tests/unit/test_publication_passage_service.py
git commit -m "feat: expose degraded mode for publication passages"
```

### Task 2: MCP Error Diagnostics Snapshot

**Files:**
- Create: `pubtator_link/services/mcp_diagnostics.py`
- Modify: `pubtator_link/mcp/errors.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing diagnostics snapshot test**

Add to `tests/unit/test_mcp_errors.py`:

```python
def test_mcp_tool_error_includes_bounded_diagnostics_snapshot() -> None:
    error = mcp_tool_error(
        RuntimeError("relation review_passages is unavailable"),
        McpErrorContext(
            tool_name="pubtator.index_review_evidence",
            pmids=["35042149", "39540697"],
            diagnostics_snapshot={
                "database": {
                    "status": "ready",
                    "schema_current": True,
                    "missing_tables": [],
                    "missing_columns": [],
                },
                "review_index": {
                    "review_id": "fmf-vus",
                    "known_sources": 2,
                    "prepared_sources": 0,
                    "failed_sources": 2,
                },
                "recovery_hint": "Continue with abstract_only fallback.",
            },
            degraded_mode="index_unavailable",
            fallback_preview={
                "tool": "pubtator.get_publication_passages",
                "mode": "compact_passages",
                "source_count": 2,
                "degraded_mode": "abstract_only",
                "coverage_by_pmid": {"35042149": "abstract_only"},
            },
        ),
    )

    payload = json.loads(str(error))

    assert payload["degraded_mode"] == "index_unavailable"
    assert payload["diagnostics_snapshot"]["database"]["schema_current"] is True
    assert payload["fallback_preview"]["source_count"] == 2
    assert len(json.dumps(payload["diagnostics_snapshot"])) < 2048
```

- [ ] **Step 2: Run test to verify red**

Run: `uv run pytest tests/unit/test_mcp_errors.py::test_mcp_tool_error_includes_bounded_diagnostics_snapshot -q`

Expected: FAIL because `McpErrorContext` does not accept `diagnostics_snapshot`, `degraded_mode`, or `fallback_preview`.

- [ ] **Step 3: Extend MCP error context and payload**

Modify `pubtator_link/mcp/errors.py`:

```python
from pubtator_link.services.degradation import DegradedMode


@dataclass(frozen=True)
class McpErrorContext:
    tool_name: str
    pmids: list[str] | None = None
    fallback_tool: str | None = None
    fallback_args: dict[str, Any] | None = None
    diagnostics_snapshot: dict[str, Any] | None = None
    degraded_mode: DegradedMode | None = None
    fallback_preview: dict[str, Any] | None = None
```

Inside `mcp_tool_error()`, after building `payload`, add:

```python
    if context.degraded_mode is not None:
        payload["degraded_mode"] = context.degraded_mode
    if context.diagnostics_snapshot is not None:
        payload["diagnostics_snapshot"] = context.diagnostics_snapshot
    if context.fallback_preview is not None:
        payload["fallback_preview"] = context.fallback_preview
```

Extend `run_mcp_tool()` keyword arguments:

```python
    diagnostics_snapshot: dict[str, Any] | None = None,
    degraded_mode: DegradedMode | None = None,
    fallback_preview: dict[str, Any] | None = None,
```

Pass those values into the the `McpErrorContext` call construction inside the generic `except Exception as exc:` branch:

```python
                diagnostics_snapshot=diagnostics_snapshot,
                degraded_mode=degraded_mode,
                fallback_preview=fallback_preview,
```

- [ ] **Step 4: Add bounded diagnostics helper**

Create `pubtator_link/services/mcp_diagnostics.py`:

```python
from __future__ import annotations

from typing import Any


MAX_DIAGNOSTICS_SNAPSHOT_CHARS = 2048


def bounded_diagnostics_snapshot(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a compact diagnostics snapshot or None if it is too large."""
    if snapshot is None:
        return None
    safe = {
        key: value
        for key, value in snapshot.items()
        if key in {"database", "review_index", "recovery_hint"}
    }
    import json

    encoded = json.dumps(safe, separators=(",", ":"), sort_keys=True)
    return safe if len(encoded) <= MAX_DIAGNOSTICS_SNAPSHOT_CHARS else None
```

Call `bounded_diagnostics_snapshot(context.diagnostics_snapshot)` before adding the snapshot to `payload`.

- [ ] **Step 5: Run MCP error tests**

Run: `uv run pytest tests/unit/test_mcp_errors.py -q`

Expected: PASS.

- [ ] **Step 6: Write failing MCP notice schema-preservation test**

Add to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
def test_review_tools_accept_context_without_exposing_ctx_parameter() -> None:
    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["pubtator.retrieve_review_context_batch"]
    schema = tool.parameters

    assert "ctx" not in schema["properties"]
```

This test prevents FastMCP `Context` injection from becoming a public JSON-schema argument.

- [ ] **Step 7: Add optional FastMCP context to review tools that emit degradation notices**

Modify `pubtator_link/mcp/tools/review.py` imports:

```python
from fastmcp import Context, FastMCP
```

For `retrieve_review_context`, `retrieve_review_context_batch`, and `index_review_evidence`, add an optional context parameter using FastMCP's context injection pattern:

```python
ctx: Context | None = None,
```

After each tool call returns `result`, emit:

```python
degraded_mode = result.get("degraded_mode")
if ctx is not None and degraded_mode:
    await ctx.warning(
        f"Review evidence is degraded: {degraded_mode}. Inspect coverage before relying on passage-level claims.",
        logger="pubtator.review",
    )
```

Use `ctx: Context` as the first parameter in each tool function. FastMCP excludes `Context` parameters from the public tool schema; the schema-preservation test proves that contract.

- [ ] **Step 8: Run MCP notice/schema tests**

Run: `uv run pytest tests/unit/test_mcp_errors.py tests/unit/mcp/test_review_rerag_mcp.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/mcp/errors.py pubtator_link/mcp/tools/review.py pubtator_link/services/mcp_diagnostics.py tests/unit/test_mcp_errors.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: add bounded MCP diagnostics snapshots"
```

### Task 3: Publication Passage Dry-Run And Verbosity

**Files:**
- Modify: `pubtator_link/models/publication_passages.py`
- Modify: `pubtator_link/services/publication_passage_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Test: `tests/unit/test_publication_passage_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing dry-run service test**

Add to `tests/unit/test_publication_passage_service.py`:

```python
@pytest.mark.asyncio
async def test_get_passages_dry_run_returns_estimate_without_text() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], dry_run=True, full=True)
    )

    assert response.dry_run is True
    assert response.passages == []
    assert response.context_estimate.estimated_passages > 0
    assert response.context_estimate.estimated_chars > 0
```

- [ ] **Step 2: Run dry-run test to verify red**

Run: `uv run pytest tests/unit/test_publication_passage_service.py::test_get_passages_dry_run_returns_estimate_without_text -q`

Expected: FAIL because `PublicationPassageRequest` has no `dry_run`.

- [ ] **Step 3: Add request/response fields and dry-run branch**

Modify `pubtator_link/models/publication_passages.py`:

```python
Verbosity = Literal["lean", "standard", "full"]


dry_run: bool = False
verbosity: Verbosity = "standard"


dry_run: bool = False
```

Insert `dry_run` and `verbosity` in `PublicationPassageRequest` after `include_references`. Insert `dry_run` in `PublicationPassageResponse` after `degraded_mode`.

In `PublicationPassageService.get_passages()`, after ``_compact_export`` and before ``_apply_char_budget``:

```python
        if request.dry_run:
            estimate = self._estimate_from_passages(passages, request.pmids, request.mode)
            coverage_by_pmid, coverage_reason_by_pmid, failed_pmids, warnings = self._coverage_summary(
                passages, request
            )
            return PublicationPassageResponse(
                success=True,
                pmids=request.pmids,
                mode=request.mode,
                passages=[],
                context_estimate=estimate,
                coverage_by_pmid=coverage_by_pmid,
                coverage_reason_by_pmid=coverage_reason_by_pmid,
                failed_pmids=failed_pmids,
                warnings=warnings,
                cache_key=_publication_passage_cache_key(request),
                corpus_snapshot_date=corpus_snapshot_date(),
                source_versions={"pubtator3": "live"},
                degraded_mode=degraded_mode_from_coverage(coverage_by_pmid),
                dry_run=True,
            )
```

- [ ] **Step 4: Run dry-run service test**

Run: `uv run pytest tests/unit/test_publication_passage_service.py::test_get_passages_dry_run_returns_estimate_without_text -q`

Expected: PASS.

- [ ] **Step 5: Write failing MCP adapter/tool schema tests**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_get_publication_passages_adapter_passes_dry_run_and_verbosity() -> None:
    service = RecordingPublicationPassageService()

    await get_publication_passages_impl(
        service=service,
        pmids=["111"],
        dry_run=True,
        verbosity="lean",
    )

    assert service.request.dry_run is True
    assert service.request.verbosity == "lean"
```

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_get_publication_passages_schema_exposes_dry_run_and_verbosity() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.get_publication_passages"]
    schema = tool.parameters

    assert schema["properties"]["dry_run"]["default"] is False
    assert set(schema["properties"]["verbosity"]["enum"]) == {"lean", "standard", "full"}
```

- [ ] **Step 6: Run adapter/schema tests to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_get_publication_passages_adapter_passes_dry_run_and_verbosity tests/unit/mcp/test_mcp_facade.py::test_get_publication_passages_schema_exposes_dry_run_and_verbosity -q`

Expected: FAIL because adapter/tool signatures do not expose these arguments.

- [ ] **Step 7: Thread dry-run and verbosity through MCP**

Modify `get_publication_passages_impl()` in `pubtator_link/mcp/service_adapters.py`:

```python
    dry_run: bool = False,
    verbosity: Literal["lean", "standard", "full"] = "standard",
```

Pass the values into ``PublicationPassageRequest``:

```python
            dry_run=dry_run,
            verbosity=verbosity,
```

Modify `get_publication_passages()` in `pubtator_link/mcp/tools/publications.py`:

```python
        dry_run: bool = False,
        verbosity: Literal["lean", "standard", "full"] = "standard",
```

Pass the values into ``get_publication_passages_impl``:

```python
                dry_run=dry_run,
                verbosity=verbosity,
```

- [ ] **Step 8: Run publication and MCP tests**

Run: `uv run pytest tests/unit/test_publication_passage_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/publication_passages.py pubtator_link/services/publication_passage_service.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/publications.py tests/unit/test_publication_passage_service.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add passage dry-run and verbosity controls"
```

### Task 4: Structured Coverage Resolver Attempts

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/full_text_preparation.py`
- Modify: `pubtator_link/services/europe_pmc.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_full_text_preparation.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing resolver attempt test**

Add to `tests/unit/test_full_text_preparation.py`:

```python
class UnavailableEuropePmcClient:
    def __init__(self, *, pmcid: str, doi: str) -> None:
        self.pmcid = pmcid
        self.doi = doi
        self.lookup_calls: list[str] = []

    async def lookup_open_access_record(self, pmcid_or_pmid: str):
        from pubtator_link.services.europe_pmc import EuropePmcLookupResult

        self.lookup_calls.append(pmcid_or_pmid)
        return EuropePmcLookupResult(
            available=False,
            pmcid=self.pmcid,
            doi=self.doi,
            reason="license_reuse_unavailable",
        )


@pytest.mark.asyncio
async def test_prepare_pmid_records_resolver_attempts_before_abstract_fallback() -> None:
    repository = RecordingRepository()
    client = RecordingPubTatorClient(
        [
            {"PubTator3": [{"id": "111", "pmid": "111", "passages": []}]},
            {
                "documents": [
                    {
                        "id": "111",
                        "pmid": "111",
                        "passages": [
                            {
                                "infons": {"type": "abstract"},
                                "text": "Abstract fallback text.",
                            }
                        ],
                    }
                ]
            },
        ]
    )
    europe_pmc = UnavailableEuropePmcClient(pmcid="PMC123", doi="10.1000/example")
    base_config = _config()
    config = ReviewReragConfig(
        **{**base_config.__dict__, "enable_europe_pmc_fallback": True}
    )
    service = FullTextPreparationService(
        config=config,
        repository=repository,
        pubtator_client=client,
        europe_pmc_client=europe_pmc,
    )

    status = await service.prepare_pmid("review-1", "111")

    assert status == "complete"
    assert [attempt["source_kind"] for attempt in repository.attempts] == [
        "pubtator_full_bioc",
        "europe_pmc_jats",
        "pubtator_abstract",
    ]
    assert repository.attempts[1]["coverage_reason"] in {
        "pmc_not_open_access",
        "parser_unsupported",
        "license_reuse_unavailable",
    }
```

The important assertion is that each resolver attempt is recorded before the abstract fallback succeeds.

- [ ] **Step 2: Run resolver test to verify current behavior**

Run: `uv run pytest tests/unit/test_full_text_preparation.py::test_prepare_pmid_records_resolver_attempts_before_abstract_fallback -q`

Expected: FAIL because the Europe PMC not-available attempt does not yet propagate PMCID/DOI metadata consistently.

- [ ] **Step 3: Add DOI/PMCID metadata propagation assertion**

Extend the same test:

```python
    assert repository.attempts[1]["pmcid"] == "PMC123"
    assert repository.attempts[1]["doi"] == "10.1000/example"
```

Run the same test again.

Expected: FAIL until Europe PMC attempt metadata is propagated to `_record_pmid_attempt()`.

- [ ] **Step 4: Propagate structured resolver metadata**

Modify the Europe PMC not-available branch in `FullTextPreparationService.prepare_pmid()`:

```python
            europe_pmc_result = await self._europe_pmc_passages_with_metadata(
                review_id=review_id,
                pmid=pmid,
            )
            passages = europe_pmc_result.passages
```

Use `passages` for the existing Europe PMC success branch. In the not-available branch, record metadata with this call:

```python
            await self._record_pmid_attempt(
                review_id=review_id,
                pmid=pmid,
                source_kind="europe_pmc_jats",
                status="not_available",
                reason=europe_pmc_result.reason,
                coverage_reason=europe_pmc_result.coverage_reason,
                coverage_hint=coverage_hint,
                retry_metadata=None,
                pmcid=europe_pmc_result.pmcid,
                doi=europe_pmc_result.doi,
            )
```

Add a small dataclass near the top of `pubtator_link/services/full_text_preparation.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class EuropePmcPassageResult:
    passages: list[ReviewPassageRow]
    pmcid: str | None
    doi: str | None
    reason: str | None
    coverage_reason: CoverageReason
```

Replace `_europe_pmc_passages()` with `_europe_pmc_passages_with_metadata()` that returns the dataclass. Keep a compatibility wrapper if existing tests call `_europe_pmc_passages()` directly.

- [ ] **Step 5: Run full-text preparation tests**

Run: `uv run pytest tests/unit/test_full_text_preparation.py -q`

Expected: PASS.

- [ ] **Step 6: Write failing resolver trace default test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_review_retrieval_schema_hides_resolver_trace_by_default() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.retrieve_review_context_batch"]
    schema = tool.parameters

    assert schema["properties"]["include_resolver_trace"]["default"] is False
```

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
@pytest.mark.asyncio
async def test_retrieve_review_context_batch_adapter_omits_resolver_trace_by_default() -> None:
    service = RecordingReviewContextService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="review-1",
        queries=["MEFV"],
        include_resolver_trace=False,
    )

    assert "resolver_attempts" not in result
```

- [ ] **Step 7: Add resolver trace controls to review retrieval**

Modify `pubtator_link/mcp/tools/review.py` retrieval tool signatures:

```python
include_resolver_trace: bool = False,
```

Thread this through `pubtator_link/mcp/service_adapters.py` into the relevant request or response-shaping layer. After `model_dump()`, strip trace-heavy fields unless requested:

```python
if not include_resolver_trace:
    result.pop("resolver_attempts", None)
    for source in result.get("sources", []):
        source.pop("resolver_attempts", None)
```

Apply the same rule to batch retrieval summaries and inspect responses where resolver attempts are present.

- [ ] **Step 8: Run resolver tests**

Run: `uv run pytest tests/unit/test_full_text_preparation.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/full_text_preparation.py pubtator_link/services/europe_pmc.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/service_adapters.py tests/unit/test_full_text_preparation.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: record structured coverage resolver attempts"
```

### Task 5: Guideline Ranking And Entity Synonyms

**Files:**
- Modify: `pubtator_link/services/search_shaping.py`
- Modify: `pubtator_link/services/entity_matching.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/unit/test_search_shaping.py`
- Test: `tests/unit/test_entity_matching.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing guideline ranking test**

Add to `tests/unit/test_search_shaping.py`:

```python
def test_guideline_boost_prioritizes_named_consensus_guidelines() -> None:
    items = [
        {
            "pmid": "1",
            "title": "Familial Mediterranean fever review",
            "abstract": "General review of MEFV.",
            "publication_types": ["Review"],
        },
        {
            "pmid": "2",
            "title": "EULAR recommendations for the management of familial Mediterranean fever",
            "abstract": "Ozen 2016 consensus recommendations.",
            "publication_types": ["Practice Guideline"],
        },
    ]

    selected = selected_search_items(items, guideline_boost=True, limit=2)

    assert [item["pmid"] for item in selected] == ["2", "1"]
```

- [ ] **Step 2: Run guideline test**

Run: `uv run pytest tests/unit/test_search_shaping.py::test_guideline_boost_prioritizes_named_consensus_guidelines -q`

Expected: PASS. Continue to Step 3 because ranking reasons are still missing.

- [ ] **Step 3: Write failing ranking reasons test**

Add to `tests/unit/test_search_shaping.py`:

```python
def test_guideline_rank_features_include_reasons() -> None:
    result = shaped_search_result(
        item={
            "pmid": "2",
            "title": "EULAR recommendations for FMF",
            "abstract": "Consensus guidance.",
            "publication_types": ["Practice Guideline"],
        },
        response_mode="standard",
        include_citations="none",
        text_hl_format="plain",
        guideline_boost=True,
        metadata="none",
    )

    assert result.rank_features is not None
    assert result.rank_features["guideline_boost"] > 0
    assert "practice guideline" in result.ranking_reasons
    assert "eular" in result.ranking_reasons
```

- [ ] **Step 4: Run ranking reasons test to verify red**

Run: `uv run pytest tests/unit/test_search_shaping.py::test_guideline_rank_features_include_reasons -q`

Expected: FAIL because `SearchResult` has no `ranking_reasons`.

- [ ] **Step 5: Add ranking reasons**

Modify `pubtator_link/models/responses.py`:

```python
    ranking_reasons: list[str] = Field(default_factory=list, description="Transparent ranking reasons")
```

Modify `_guideline_rank_features()` in `pubtator_link/services/search_shaping.py`:

```python
def _guideline_rank_features(item: dict[str, Any]) -> dict[str, Any]:
    publication_types = [str(value).lower() for value in item.get("publication_types", [])]
    title = str(item.get("title") or "").lower()
    abstract = str(item.get("abstract") or "").lower()
    reasons: list[str] = []
    type_boost = 0
    for value in publication_types:
        for term in GUIDELINE_TYPES:
            if term in value:
                type_boost += 3
                reasons.append(term)
                break
    term_boost = 0
    for term in GUIDELINE_TERMS:
        if term in title or term in abstract:
            term_boost += 1
            reasons.append(term)
    return {
        "guideline_boost": type_boost + term_boost,
        "ranking_reasons": list(dict.fromkeys(reasons)),
    }
```

In `shaped_search_result()`, set:

```python
        ranking_reasons=rank_features.get("ranking_reasons", []) if rank_features else [],
```

- [ ] **Step 6: Write failing entity synonym extraction test**

Add to `tests/unit/test_entity_matching.py`:

```python
from pubtator_link.services.entity_matching import synonyms_from_entity_item


def test_synonyms_from_entity_item_uses_upstream_and_match_text() -> None:
    item = {
        "synonyms": ["MEFV", "FMF gene", "MEFV"],
        "match": "Matched on synonyms <m>pyrin</m>, <m>marenostrin</m>",
    }

    assert synonyms_from_entity_item(item) == ["MEFV", "FMF gene", "pyrin", "marenostrin"]
```

- [ ] **Step 7: Run synonym test to verify red**

Run: `uv run pytest tests/unit/test_entity_matching.py::test_synonyms_from_entity_item_uses_upstream_and_match_text -q`

Expected: FAIL because `synonyms_from_entity_item` does not exist.

- [ ] **Step 8: Implement bounded synonym helper and adapter use**

Modify `pubtator_link/services/entity_matching.py`:

```python
from typing import Any


def synonyms_from_entity_item(item: dict[str, Any], *, limit: int = 10) -> list[str]:
    values: list[str] = []
    for synonym in item.get("synonyms") or []:
        if isinstance(synonym, str) and synonym.strip():
            values.append(synonym.strip())
    values.extend(matched_terms_from_match_text(item.get("match")))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"</?m>", "", value).strip(" .")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped
```

Modify `search_biomedical_entities_impl()` in `pubtator_link/mcp/service_adapters.py`:

```python
from pubtator_link.services.entity_matching import (
    matched_terms_from_match_text,
    synonyms_from_entity_item,
)
```

Use `synonyms_from_entity_item(item)` in the ``EntityMatch`` construction:

```python
            synonyms=synonyms_from_entity_item(item),
```

- [ ] **Step 9: Run search/entity tests**

Run: `uv run pytest tests/unit/test_search_shaping.py tests/unit/test_entity_matching.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pubtator_link/models/responses.py pubtator_link/services/search_shaping.py pubtator_link/services/entity_matching.py pubtator_link/mcp/service_adapters.py tests/unit/test_search_shaping.py tests/unit/test_entity_matching.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: improve guideline ranking and entity synonyms"
```

### Task 6: Citation Defaults, Lean Serialization, And Cleanup

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`
- Modify: `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write failing MCP citation default test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_search_literature_schema_defaults_to_nlm_citations_for_metadata() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.search_literature"]
    schema = tool.parameters

    assert schema["properties"]["metadata"]["default"] == "basic"
    assert schema["properties"]["include_citations"]["default"] == "nlm"
```

- [ ] **Step 2: Run citation default test to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_search_literature_schema_defaults_to_nlm_citations_for_metadata -q`

Expected: FAIL because `include_citations` currently defaults to `"none"`.

- [ ] **Step 3: Change MCP search citation default**

Modify `pubtator_link/mcp/tools/literature.py`:

```python
        include_citations: IncludeCitations = "nlm",
```

Keep REST route defaults unchanged.

- [ ] **Step 4: Write failing active-doc cleanup test**

Add to `tests/unit/test_development_tooling.py`:

```python
def test_active_docs_do_not_advertise_v2_or_prepare_mode_examples() -> None:
    active_paths = [
        Path("docs/MCP_CONNECTION_GUIDE.md"),
        Path("pubtator_link/mcp/resources.py"),
    ]
    joined = "\n".join(path.read_text() for path in active_paths)

    assert "search_literature_v2" not in joined
    assert '"prepare_mode": "selected"' not in joined
```

- [ ] **Step 5: Run cleanup test**

Run: `uv run pytest tests/unit/test_development_tooling.py::test_active_docs_do_not_advertise_v2_or_prepare_mode_examples -q`

Expected: FAIL before cleanup because active docs/resources still contain stale examples.

- [ ] **Step 6: Clean active guidance**

Modify `pubtator_link/mcp/resources.py`:

- Keep `schema_policy.deprecated_fields` for `prepare_mode`.
- Remove sample-call arguments that include `"prepare_mode": "selected"`.
- Keep `deprecated_tools: []`.

Modify `docs/MCP_CONNECTION_GUIDE.md` to keep exactly one compatibility note:

```markdown
If a client still displays old `_v2` aliases, refresh the MCP/tool cache and reconnect. Current public tools use canonical names only.
```

- [ ] **Step 7: Update status docs**

Modify:

- `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`
- `docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`

Add a short status bullet in each doc saying the reliability/ergonomics plan is now tracked by:

```markdown
`docs/superpowers/plans/2026-05-02-review-rag-reliability-and-llm-ergonomics-implementation.md`
```

- [ ] **Step 8: Run MCP/tooling tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_development_tooling.py -q`

Expected: PASS.

- [ ] **Step 9: Run full CI**

Run: `make ci-local`

Expected: PASS with zero failures.

- [ ] **Step 10: Rebuild and restart Docker**

Run:

```bash
make docker-build
make docker-down
make docker-up
```

Expected: all commands exit 0.

- [ ] **Step 11: Verify running service**

Run:

```bash
curl -sS http://localhost:8011/ready
curl -sS http://localhost:8011/metrics | head -40
```

Expected:

- `/ready` returns `"schema_current": true`.
- `/metrics` contains `mcp_tool_calls_total` and `mcp_tool_latency_seconds`.

- [ ] **Step 12: Commit**

```bash
git add pubtator_link/mcp/tools/literature.py pubtator_link/mcp/tools/publications.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/resources.py docs/MCP_CONNECTION_GUIDE.md docs/2026-05-02-pubtator-link-observability-implementation-guide.md docs/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_development_tooling.py
git commit -m "feat: align MCP citation defaults and cleanup guidance"
```

### Task 7: MCP Consumer Polish And Workflow Capability Surface

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_indexing.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_workflow_help.py`

- [ ] **Step 1: Write failing prepare-mode drift test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_index_review_evidence_schema_does_not_expose_prepare_mode() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.index_review_evidence"]
    schema = tool.parameters

    assert "prepare_mode" not in schema["properties"]
```

Add to `tests/unit/test_workflow_help.py`:

```python
def test_workflow_help_does_not_show_prepare_mode_argument() -> None:
    help_text = workflow_help_text()

    assert "prepare_mode" not in help_text
```

- [ ] **Step 2: Run prepare-mode drift tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_index_review_evidence_schema_does_not_expose_prepare_mode tests/unit/test_workflow_help.py::test_workflow_help_does_not_show_prepare_mode_argument -q`

Expected: FAIL before cleanup because active workflow guidance still shows `prepare_mode`.

- [ ] **Step 3: Remove active prepare_mode examples and keep model compatibility**

Modify `pubtator_link/mcp/tools/review.py` so `index_review_evidence()` does not expose `prepare_mode` in the public tool signature. The adapter can keep passing the internal default:

```python
prepare_mode="selected",
```

Modify `pubtator_link/services/workflow_help.py` and `pubtator_link/mcp/resources.py` to remove sample-call arguments containing:

```json
{"prepare_mode": "selected"}
```

Keep `PrepareMode = Literal["selected"]` in `pubtator_link/models/review_rerag.py` for REST/backward compatibility until the next minor release.

- [ ] **Step 4: Write failing batch response hygiene test**

Add to `tests/unit/test_review_context_batch_budgeting.py`:

```python
def test_compact_batch_response_omits_empty_results_when_merged_pack_is_primary() -> None:
    response = merge_batch_context(
        request=_batch_request(response_mode="compact"),
        query_results=[_query_result("q1", ["p1"])],
        coverage_by_source={},
    )
    dumped = response.model_dump(exclude_none=True, exclude_defaults=True)

    assert "merged_context_pack" in dumped
    assert "results" not in dumped
```

- [ ] **Step 5: Run batch hygiene test to verify red**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py::test_compact_batch_response_omits_empty_results_when_merged_pack_is_primary -q`

Expected: FAIL before serialization cleanup because `results: []` is still serialized for compact responses.

- [ ] **Step 6: Add batch response serialization hygiene**

Modify `RetrieveReviewContextBatchResponse` in `pubtator_link/models/review_rerag.py`:

```python
@model_serializer(mode="wrap")
def omit_empty_results_for_compact(self, handler):
    data = handler(self)
    if self.response_mode in {"compact", "merged_only", "diagnostics"} and not self.results:
        data.pop("results", None)
    return data
```

Import `model_serializer` from Pydantic in the same file.

- [ ] **Step 7: Write failing wait-until-ready alias test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_index_review_evidence_schema_exposes_wait_until_ready_alias() -> None:
    tool = create_pubtator_mcp()._tool_manager._tools["pubtator.index_review_evidence"]
    schema = tool.parameters

    assert schema["properties"]["wait_until_ready"]["default"] is False
    assert schema["properties"]["timeout_ms"]["default"] == 0
```

- [ ] **Step 8: Run wait alias test to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_index_review_evidence_schema_exposes_wait_until_ready_alias -q`

Expected: FAIL because the current public argument is `wait_for_completion`, not `wait_until_ready`.

- [ ] **Step 9: Add wait alias without breaking existing wait fields**

Modify `pubtator_link/mcp/tools/review.py` `index_review_evidence()` signature:

```python
wait_until_ready: bool = False,
timeout_ms: int = 0,
```

Pass into the adapter as:

```python
wait_for_completion=wait_until_ready,
wait_for_status="complete_or_partial" if wait_until_ready else wait_for_status,
timeout_ms=timeout_ms,
```

Keep existing internal `wait_for_completion` support in `IndexReviewEvidenceRequest` and `ReviewIndexingService` unchanged.

- [ ] **Step 10: Write failing tool category capability test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_capabilities_expose_tool_categories_and_diagnostics_workflow() -> None:
    capabilities = _capabilities_payload()

    assert capabilities["tool_categories"]["discovery"]
    assert "pubtator.search_literature" in capabilities["tool_categories"]["discovery"]
    assert "pubtator.index_review_evidence" in capabilities["tool_categories"]["indexing"]
    assert "pubtator.retrieve_review_context_batch" in capabilities["tool_categories"]["retrieval"]
    assert "pubtator.diagnostics" in capabilities["workflow"]["recommended_tools"]
```

Import `get_capabilities_resource` inside the test, matching existing capability tests in `tests/unit/mcp/test_mcp_facade.py`:

```python
from pubtator_link.mcp.resources import get_capabilities_resource

capabilities = get_capabilities_resource()
```

- [ ] **Step 11: Run capability test to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py::test_capabilities_expose_tool_categories_and_diagnostics_workflow -q`

Expected: FAIL until `tool_categories` and diagnostics workflow entries are added.

- [ ] **Step 12: Add capability categories and diagnostics workflow guidance**

Modify `pubtator_link/mcp/resources.py` capabilities payload:

```python
"tool_categories": {
    "discovery": [
        "pubtator.search_literature",
        "pubtator.search_guidelines",
        "pubtator.search_biomedical_entities",
        "pubtator.find_entity_relations",
        "pubtator.lookup_variant_evidence",
    ],
    "indexing": [
        "pubtator.preflight_review_sources",
        "pubtator.stage_research_session",
        "pubtator.index_review_evidence",
        "pubtator.inspect_review_index",
    ],
    "retrieval": [
        "pubtator.retrieve_review_context",
        "pubtator.retrieve_review_context_batch",
        "pubtator.get_review_passages_by_id",
        "pubtator.get_neighboring_review_passages",
    ],
    "metadata": [
        "pubtator.get_publication_metadata",
        "pubtator.get_publication_passages",
        "pubtator.estimate_publication_context",
        "pubtator.diagnostics",
    ],
},
"workflow": {
    "recommended_tools": [
        "pubtator.search_literature",
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
        "pubtator.inspect_review_index",
        "pubtator.diagnostics",
        "pubtator.retrieve_review_context_batch",
    ],
},
```

Preserve existing capability fields and append these keys rather than replacing the payload.

- [ ] **Step 13: Write failing inspect coverage summary test**

Add to `tests/unit/test_review_context_service.py`:

```python
@pytest.mark.asyncio
async def test_inspect_review_index_includes_coverage_summary() -> None:
    repository = FakeReviewContextRepository([])
    repository.source_summaries = [
        ReviewSourceSummary(source_id="s1", pmid="1", source_kind="pubtator_full_bioc", job_status="complete", coverage="full_text"),
        ReviewSourceSummary(source_id="s2", pmid="2", source_kind="pubtator_abstract", job_status="complete", coverage="abstract_only"),
        ReviewSourceSummary(source_id="s3", pmid="3", source_kind="pubtator_abstract", job_status="complete", coverage="title_only"),
    ]
    service = ReviewContextService(repository)

    response = await service.inspect_review_index("review-1", InspectReviewIndexRequest())

    assert response.coverage_summary == {
        "full_text": 1,
        "abstract_only": 1,
        "title_only": 1,
        "unknown": 0,
    }
```

- [ ] **Step 14: Run inspect summary test to verify red**

Run: `uv run pytest tests/unit/test_review_context_service.py::test_inspect_review_index_includes_coverage_summary -q`

Expected: FAIL because inspect response has no `coverage_summary`.

- [ ] **Step 15: Add inspect coverage summary**

Modify `InspectReviewIndexResponse` in `pubtator_link/models/review_rerag.py`:

```python
coverage_summary: dict[str, int] = Field(default_factory=dict)
```

Modify `ReviewContextService.inspect_review_index()` in `pubtator_link/services/review_context_service.py`:

```python
coverage_summary = {"full_text": 0, "abstract_only": 0, "title_only": 0, "unknown": 0}
for source in sources:
    coverage_summary[source.coverage] = coverage_summary.get(source.coverage, 0) + 1
```

Pass `coverage_summary=coverage_summary` into ``InspectReviewIndexResponse``.

- [ ] **Step 16: Write failing dropped truncation test**

Add to `tests/unit/test_review_context_batch_budgeting.py`:

```python
def test_batch_response_truncates_large_dropped_list_with_summary() -> None:
    response = merge_batch_context(
        request=_batch_request(response_mode="compact", max_total_passages=1),
        query_results=[_query_result("q1", [f"p{index}" for index in range(30)])],
        coverage_by_source={},
    )

    assert len(response.merged_context_pack.dropped) <= 10
    assert response.merged_context_pack.dropped_summary["truncated_count"] > 0
```

- [ ] **Step 17: Run dropped truncation test to verify red**

Run: `uv run pytest tests/unit/test_review_context_batch_budgeting.py::test_batch_response_truncates_large_dropped_list_with_summary -q`

Expected: FAIL because dropped entries are not summarized.

- [ ] **Step 18: Add dropped summary fields and cap**

Modify `ContextPack` in `pubtator_link/models/review_rerag.py`:

```python
dropped_summary: dict[str, int] = Field(default_factory=dict)
```

In `merge_batch_context()` in `pubtator_link/services/review_context/batch_budgeting.py`, after building dropped entries:

```python
MAX_DROPPED_ITEMS = 10
truncated_count = max(0, len(dropped) - MAX_DROPPED_ITEMS)
visible_dropped = dropped[:MAX_DROPPED_ITEMS]
dropped_summary = {"truncated_count": truncated_count} if truncated_count else {}
```

Pass `dropped=visible_dropped` and `dropped_summary=dropped_summary` into the merged `ContextPack`.

- [ ] **Step 19: Run consumer polish tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py tests/unit/test_workflow_help.py -q`

Expected: PASS.

- [ ] **Step 20: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_indexing.py pubtator_link/services/review_context/batch_budgeting.py pubtator_link/services/review_context_service.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/resources.py pubtator_link/services/workflow_help.py tests/unit/test_review_rerag_models.py tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_workflow_help.py
git commit -m "feat: improve MCP consumer workflow ergonomics"
```

## Final Verification

- [ ] Run `make ci-local`.
- [ ] Run `make docker-build`.
- [ ] Run `make docker-down`.
- [ ] Run `make docker-up`.
- [ ] Run `curl -sS http://localhost:8011/ready`.
- [ ] Run `curl -sS http://localhost:8011/metrics | head -40`.
- [ ] Confirm `git status --short` is clean after all task commits.

## Spec Coverage Check

- Degraded mode is covered by Task 1 and Task 2.
- Inline diagnostics snapshots are covered by Task 2.
- MCP degradation notices are prepared by Task 2 through error-envelope fields; adding `ctx.warning()` directly can be paired with Task 2 where FastMCP context injection is validated by existing tool schema tests.
- Source coverage resolver attempts are covered by Task 4.
- `verbosity`, dry-run, and citation defaults are covered by Task 3 and Task 6.
- Guideline ranking and entity synonyms are covered by Task 5.
- `_v2` and `prepare_mode` cleanup is covered by Task 6.
- MCP-native degradation notices are covered by Task 2.
- MCP-consumer improvements from the 15-dimension review are covered by Task 7: prepare-mode drift, batch `results` hygiene, wait alias, tool categories, inspect `coverage_summary`, diagnostics workflow guidance, dropped truncation, and `_v2` cleanup.
- Resolver trace defaults are covered by Task 4.
