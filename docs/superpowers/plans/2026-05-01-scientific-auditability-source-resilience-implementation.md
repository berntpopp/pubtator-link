# Scientific Auditability Source Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add coverage-first auditability, upstream retry/backoff, bounded parallel retrieval/preflight, passage addressability, and a review audit bundle without breaking existing REST or MCP behavior.

**Architecture:** Extend the existing review re-RAG models, repository, preparation service, MCP tools, and route patterns. Make source coverage and resolver attempts first-class data, put retry/backoff in reusable API/resolver helpers, and keep concurrency bounded with deterministic response ordering.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic, asyncpg/PostgreSQL, httpx, pytest, pytest-asyncio, respx, Ruff, mypy, Makefile targets.

---

## File Structure

- Modify `pubtator_link/models/review_rerag.py` for coverage reasons, source hints, resolver attempts, evidence tiers, passage lookup responses, and audit bundle models.
- Modify `pubtator_link/repositories/review_schema.sql` or the existing schema file that defines `review_passages`, `review_preparation_jobs`, and `full_text_retrieval_attempts`.
- Modify `pubtator_link/repositories/review_rerag.py` and `pubtator_link/repositories/review_rerag_mappers.py` for new persisted fields and query methods.
- Create `pubtator_link/api/retry.py` for reusable retry policy helpers.
- Modify `pubtator_link/api/client.py` to apply retry policy to idempotent PubTator calls.
- Create `pubtator_link/services/source_preflight.py` for PMC ID Converter, BioC-PMC/OAI-PMH probes, and PMID coverage hint orchestration.
- Modify `pubtator_link/services/full_text_preparation.py` to record structured resolver attempts and actual coverage reasons.
- Modify `pubtator_link/services/review_context_service.py` for bounded concurrent batch retrieval and passage lookup methods.
- Create `pubtator_link/services/review_audit.py` for audit bundle assembly.
- Modify `pubtator_link/mcp/service_adapters.py`, `pubtator_link/mcp/tools/review.py`, `pubtator_link/mcp/facade.py`, and `pubtator_link/mcp/resources.py` for new MCP tools.
- Modify `pubtator_link/api/routes/reviews.py` for REST route equivalents where they match existing route style.
- Add or extend tests under `tests/unit/`, `tests/unit/mcp/`, and `tests/test_routes/`.
- Update `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md` after implementation to mark completed roadmap items.

## Task 1: Models And Schema For Source Audit Data

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_schema.sql` or the local review schema file if named differently
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_schema_sql.py`
- Test: `tests/unit/test_review_rerag_mappers.py`

- [ ] **Step 1: Locate the schema file**

Run: `rg -n "create table if not exists full_text_retrieval_attempts|create table if not exists review_passages" pubtator_link tests`

Expected: one schema file under `pubtator_link/repositories/` or a nearby module. Use that exact file in the remaining steps instead of `pubtator_link/repositories/review_schema.sql` if the name differs.

- [ ] **Step 2: Write failing model tests**

Add tests that assert these model defaults and derived values:

```python
from pubtator_link.models.review_rerag import (
    EvidenceTier,
    ResolverAttemptSummary,
    SourceCoverageHint,
    coverage_to_evidence_tier,
)


def test_source_coverage_hint_defaults_to_unknown_reason() -> None:
    hint = SourceCoverageHint(pmid="40234174")

    assert hint.expected_coverage == "unknown"
    assert hint.coverage_reason == "unknown"
    assert hint.pmc_fallback_available is False
    assert hint.resolver_attempts == []


def test_resolver_attempt_summary_captures_retry_metadata() -> None:
    attempt = ResolverAttemptSummary(
        source_kind="pubtator_full_bioc",
        status="failed",
        attempt_count=3,
        last_status_code=503,
        retry_after_ms=1000,
        backoff_ms=750,
        terminal_reason="retry_exhausted",
    )

    assert attempt.attempt_count == 3
    assert attempt.last_status_code == 503
    assert attempt.terminal_reason == "retry_exhausted"


def test_evidence_tier_derives_from_actual_coverage() -> None:
    assert coverage_to_evidence_tier("full_text", "pubtator_full_bioc") == EvidenceTier.PASSAGE_FULL_TEXT
    assert coverage_to_evidence_tier("abstract_only", "pubtator_abstract") == EvidenceTier.PASSAGE_ABSTRACT
    assert coverage_to_evidence_tier("title_only", "pubtator_abstract") == EvidenceTier.METADATA_TITLE
    assert coverage_to_evidence_tier("curated_url", "curated_pdf") == EvidenceTier.CURATED_FULL_TEXT
```

- [ ] **Step 3: Run model tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py -q`

Expected: FAIL because `SourceCoverageHint`, `ResolverAttemptSummary`, `EvidenceTier`, or `coverage_to_evidence_tier` is not defined.

- [ ] **Step 4: Add audit models**

In `pubtator_link/models/review_rerag.py`, add enum/string model definitions near the other review types:

```python
CoverageReason = Literal[
    "full_text_available",
    "abstract_fallback_used",
    "title_only_metadata",
    "no_pmcid",
    "pmc_not_open_access",
    "license_reuse_unavailable",
    "upstream_timeout",
    "upstream_404",
    "retry_exhausted",
    "parser_unsupported",
    "blocked_source",
    "unknown",
]


class EvidenceTier(StrEnum):
    PASSAGE_FULL_TEXT = "PASSAGE_FULL_TEXT"
    PASSAGE_ABSTRACT = "PASSAGE_ABSTRACT"
    METADATA_TITLE = "METADATA_TITLE"
    CURATED_FULL_TEXT = "CURATED_FULL_TEXT"
    UNVERIFIED_EXTERNAL = "UNVERIFIED_EXTERNAL"


class ResolverAttemptSummary(BaseModel):
    source_kind: str
    status: AttemptStatus
    attempt_count: int = Field(default=1, ge=1)
    last_status_code: int | None = None
    retry_after_ms: int | None = None
    backoff_ms: int | None = None
    terminal_reason: CoverageReason | str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    source_id: str | None = None
    url: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    content_type: str | None = None
    content_length: int | None = Field(default=None, ge=0)


class SourceCoverageHint(BaseModel):
    pmid: str
    expected_coverage: SourceCoverage = "unknown"
    coverage_reason: CoverageReason = "unknown"
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    pmc_fallback_available: bool = False
    resolver_attempts: list[ResolverAttemptSummary] = Field(default_factory=list)


def coverage_to_evidence_tier(coverage: SourceCoverage, source_kind: str) -> EvidenceTier:
    if coverage == "full_text":
        return EvidenceTier.PASSAGE_FULL_TEXT
    if coverage == "abstract_only":
        return EvidenceTier.PASSAGE_ABSTRACT
    if coverage == "title_only":
        return EvidenceTier.METADATA_TITLE
    if coverage == "curated_url":
        return EvidenceTier.CURATED_FULL_TEXT
    if source_kind in {"curated_pdf", "curated_html", "docling_pdf"}:
        return EvidenceTier.CURATED_FULL_TEXT
    return EvidenceTier.UNVERIFIED_EXTERNAL
```

- [ ] **Step 5: Extend inspection models additively**

Add optional fields to `ReviewSourceSummary` and `FailedSourceSummary`:

```python
coverage_reason: CoverageReason = "unknown"
pmcid: str | None = None
doi: str | None = None
license_or_access_hint: str | None = None
pmc_fallback_available: bool = False
resolver_attempts: list[ResolverAttemptSummary] = Field(default_factory=list)
```

Do not remove or rename existing fields.

- [ ] **Step 6: Extend schema and mapper tests**

Add assertions that the retrieval attempts table contains columns for:

```python
"attempt_count"
"last_status_code"
"retry_after_ms"
"backoff_ms"
"terminal_reason"
"pmcid"
"doi"
"license_or_access_hint"
```

Add mapper tests that a row with those fields produces a `ReviewSourceSummary` with `coverage_reason`, `pmcid`, `doi`, and at least one `resolver_attempts` entry.

- [ ] **Step 7: Run focused tests to verify failure**

Run: `uv run pytest tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_mappers.py -q`

Expected: FAIL until schema and mapper code are updated.

- [ ] **Step 8: Update schema and mappers**

Add nullable columns to `full_text_retrieval_attempts` and map them into `ResolverAttemptSummary`. Keep existing insert callers working by giving repository method keyword defaults.

- [ ] **Step 9: Run focused tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_mappers.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories tests/unit
git commit -m "feat: add review source audit models"
```

## Task 2: Retry And Backoff For Idempotent Upstream Calls

**Files:**
- Create: `pubtator_link/api/retry.py`
- Modify: `pubtator_link/api/client.py`
- Test: `tests/unit/test_api_retry.py`
- Test: `tests/unit/test_pubtator_client_retry.py`

- [ ] **Step 1: Write retry policy tests**

Create `tests/unit/test_api_retry.py` with tests for retryable status codes, `Retry-After`, and capped jitter. Use a deterministic random function.

- [ ] **Step 2: Write PubTator client retry tests**

Create `tests/unit/test_pubtator_client_retry.py` using `respx` or `httpx.MockTransport` to prove:

- GET export retries `503` then succeeds.
- GET export respects `Retry-After`.
- `404` does not retry.
- POST text processing does not retry by default.

- [ ] **Step 3: Run retry tests to verify failure**

Run: `uv run pytest tests/unit/test_api_retry.py tests/unit/test_pubtator_client_retry.py -q`

Expected: FAIL because retry helpers do not exist and the client currently raises immediately.

- [ ] **Step 4: Implement retry helper**

Create `pubtator_link/api/retry.py` with:

```python
from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 10_000
    retry_status_codes: set[int] = field(
        default_factory=lambda: {408, 429, 500, 502, 503, 504}
    )
    respect_retry_after: bool = True


@dataclass(frozen=True)
class RetryAttemptMetadata:
    attempt_count: int
    last_status_code: int | None = None
    retry_after_ms: int | None = None
    backoff_ms: int | None = None
    terminal_reason: str | None = None


def retry_after_ms(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = int(value.strip())
    except ValueError:
        return None
    return max(0, seconds * 1000)


def full_jitter_delay_ms(policy: RetryPolicy, attempt_index: int) -> int:
    cap = min(policy.max_delay_ms, policy.base_delay_ms * (2 ** max(0, attempt_index - 1)))
    return random.randint(0, cap)


async def call_with_retries(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[httpx.Response, RetryAttemptMetadata]:
    attempts = 0
    last_status_code: int | None = None
    last_retry_after_ms: int | None = None
    last_backoff_ms: int | None = None
    while True:
        attempts += 1
        try:
            response = await send()
        except httpx.RequestError:
            if attempts >= policy.max_attempts:
                raise
            last_backoff_ms = full_jitter_delay_ms(policy, attempts)
            await sleep(last_backoff_ms / 1000)
            continue

        last_status_code = response.status_code
        if response.status_code not in policy.retry_status_codes or attempts >= policy.max_attempts:
            return response, RetryAttemptMetadata(
                attempt_count=attempts,
                last_status_code=last_status_code,
                retry_after_ms=last_retry_after_ms,
                backoff_ms=last_backoff_ms,
                terminal_reason="retry_exhausted"
                if response.status_code in policy.retry_status_codes and attempts >= policy.max_attempts
                else None,
            )

        last_retry_after_ms = retry_after_ms(response) if policy.respect_retry_after else None
        last_backoff_ms = last_retry_after_ms if last_retry_after_ms is not None else full_jitter_delay_ms(policy, attempts)
        await sleep(last_backoff_ms / 1000)
```

- [ ] **Step 5: Wire retry into `PubTator3Client._make_request`**

Only use retries for idempotent calls. Add a `retry: bool = True` parameter and call `_make_request(..., retry=False)` for text annotation POST methods. Keep existing returned JSON/content behavior.

- [ ] **Step 6: Run focused retry tests**

Run: `uv run pytest tests/unit/test_api_retry.py tests/unit/test_pubtator_client_retry.py -q`

Expected: PASS.

- [ ] **Step 7: Run API/client related tests**

Run: `uv run pytest tests/test_routes tests/unit/test_publication_passage_service.py tests/unit/mcp/test_mcp_service_adapters.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/api/retry.py pubtator_link/api/client.py tests/unit/test_api_retry.py tests/unit/test_pubtator_client_retry.py
git commit -m "feat: add upstream retry backoff"
```

## Task 3: Source Preflight Service And Public Tool

**Files:**
- Create: `pubtator_link/services/source_preflight.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/unit/test_source_preflight.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write preflight service tests**

Create tests using fake clients for:

- PMCID returned by ID Converter and BioC-PMC available -> `expected_coverage == "full_text"`, `pmc_fallback_available is True`.
- No PMCID and PubTator abstract available -> `expected_coverage == "abstract_only"`, `coverage_reason == "no_pmcid"`.
- Upstream timeout -> one failed resolver attempt and `expected_coverage == "unknown"`.

- [ ] **Step 2: Write MCP and route tests**

Add tests that `pubtator.preflight_review_sources` is registered with flat `pmids`, and that the REST route returns `coverage_hints`.

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_source_preflight.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py -q`

Expected: FAIL because the service, tool, and route do not exist.

- [ ] **Step 4: Implement service with injected clients**

Create `SourcePreflightService` that accepts injectable async callables for ID conversion and availability probes. Keep real HTTP clients thin and test the orchestration with fakes.

Required method:

```python
async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
    indexed_pmids = list(dict.fromkeys(pmids))
    results: list[tuple[int, SourceCoverageHint]] = []
    for index, pmid in enumerate(indexed_pmids):
        hint = await self._preflight_one_pmid(pmid)
        results.append((index, hint))
    return [hint for _, hint in sorted(results, key=lambda item: item[0])]
```

The method must preserve input order and isolate per-PMID failures.

- [ ] **Step 5: Add MCP adapter and tool**

Add `preflight_review_sources_impl(pmids: list[str]) -> dict[str, object]` returning:

```python
{
    "success": True,
    "coverage_hints": [hint.model_dump(mode="json") for hint in hints],
}
```

Register MCP tool name `pubtator.preflight_review_sources`.

- [ ] **Step 6: Add REST route**

Follow existing review route style. Add a route such as:

```python
@router.post("/reviews/source-preflight")
async def preflight_review_sources(request: PreflightReviewSourcesRequest) -> PreflightReviewSourcesResponse:
    service = SourcePreflightService.from_settings(settings)
    hints = await service.preflight_pmids(request.pmids)
    return PreflightReviewSourcesResponse(coverage_hints=hints)
```

Add Pydantic request/response models in `pubtator_link/models/review_rerag.py` if the route file imports review route models from there.

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_source_preflight.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/services/source_preflight.py pubtator_link/mcp pubtator_link/api/routes/reviews.py tests/unit/test_source_preflight.py tests/unit/mcp tests/test_routes/test_reviews.py
git commit -m "feat: add review source preflight"
```

## Task 4: Preparation Resolver Cascade And Inspection Fields

**Files:**
- Modify: `pubtator_link/services/full_text_preparation.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Test: `tests/unit/test_full_text_preparation.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing preparation tests**

Extend `tests/unit/test_full_text_preparation.py` so `prepare_pmid` records:

- PubTator full attempt even when it falls back to abstract.
- Abstract fallback attempt with `coverage_reason == "abstract_fallback_used"`.
- PMCID/DOI from preflight metadata when supplied.
- Retry metadata when the client exposes it.

- [ ] **Step 2: Write failing inspection tests**

Add tests that `inspect_review_index` returns source summaries with:

```python
coverage_reason
pmcid
doi
license_or_access_hint
pmc_fallback_available
resolver_attempts
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_full_text_preparation.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py -q`

Expected: FAIL because the extra attempts and fields are not persisted/mapped.

- [ ] **Step 4: Update repository write path**

Extend `record_retrieval_attempt` with optional keyword-only parameters:

```python
attempt_count: int = 1,
last_status_code: int | None = None,
retry_after_ms: int | None = None,
backoff_ms: int | None = None,
terminal_reason: str | None = None,
pmcid: str | None = None,
doi: str | None = None,
license_or_access_hint: str | None = None,
coverage_reason: str = "unknown",
pmc_fallback_available: bool = False,
```

Keep all existing callers valid.

- [ ] **Step 5: Update preparation flow**

Record the full PubTator attempt before falling back. Record the final attempt separately. If BioC-PMC support was added in Task 3, insert it between PubTator full and abstract fallback. Preserve current successful passage IDs and source kinds.

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/unit/test_full_text_preparation.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/full_text_preparation.py pubtator_link/repositories pubtator_link/models/review_rerag.py tests/unit/test_full_text_preparation.py tests/unit/test_review_rerag_repository.py tests/test_routes/test_reviews.py
git commit -m "feat: record review resolver audit trail"
```

## Task 5: Bounded Parallel Batch Retrieval And Preflight

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/services/source_preflight.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/test_source_preflight.py`
- Test: `tests/unit/test_review_rerag_config.py`

- [ ] **Step 1: Write failing config tests**

Assert new settings default low:

```python
assert settings.review_retrieval_concurrency == 4
assert settings.review_preflight_concurrency == 3
```

Use the repo's existing settings test pattern.

- [ ] **Step 2: Write deterministic retrieval concurrency test**

Use fake delayed repository search methods to prove three queries start before the first one finishes when concurrency allows it, but `query_summaries` and merged processing still follow original query order.

- [ ] **Step 3: Write preflight concurrency test**

Use fake probe methods that record in-flight count and assert it never exceeds configured preflight concurrency.

- [ ] **Step 4: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_source_preflight.py tests/unit/test_review_rerag_config.py -q`

Expected: FAIL because retrieval and preflight still run sequentially or lack config.

- [ ] **Step 5: Add config fields**

Add settings and config fields:

```python
review_retrieval_concurrency: int = Field(default=4, ge=1, le=10)
review_preflight_concurrency: int = Field(default=3, ge=1, le=10)
```

Thread them into the relevant service constructors without changing existing default behavior for callers that do not pass config.

- [ ] **Step 6: Implement bounded retrieval scheduling**

In `retrieve_context_batch`, create tasks for each query under `asyncio.Semaphore(concurrency)`, return `(query_index, result)`, sort by `query_index`, then call `merge_batch_context` with ordered `query_results`.

- [ ] **Step 7: Implement bounded preflight scheduling**

In `SourcePreflightService.preflight_pmids`, wrap per-PMID probes in a semaphore and return results sorted by input index.

- [ ] **Step 8: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_source_preflight.py tests/unit/test_review_rerag_config.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/config.py pubtator_link/services/review_context_service.py pubtator_link/services/source_preflight.py tests/unit/test_review_context_service.py tests/unit/test_source_preflight.py tests/unit/test_review_rerag_config.py
git commit -m "feat: add bounded review concurrency"
```

## Task 6: Passage Addressability Tools

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/unit/test_review_context_service.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing repository/service tests**

Cover:

- Exact passage lookup returns requested order.
- Missing IDs appear in `not_found`.
- Neighbor lookup honors `before`, `after`, and `same_section`.
- Text truncation respects `max_chars_per_passage`.

- [ ] **Step 2: Write failing MCP and route tests**

Assert tools exist:

- `pubtator.get_review_passages_by_id`
- `pubtator.get_neighboring_review_passages`

Assert route responses include `passages` and `not_found`.

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp tests/test_routes/test_reviews.py -q`

Expected: FAIL because addressability methods and tools are absent.

- [ ] **Step 4: Add models**

Add request/response models for exact passage lookup and neighboring lookup. Reuse `ContextPassage` for returned passages.

- [ ] **Step 5: Add repository methods**

Implement:

```python
async def get_passages_by_id(
    self,
    review_id: str,
    passage_ids: Sequence[str],
) -> list[ReviewPassageRow]:
    rows = await self._fetch_passage_rows_by_ids(review_id, passage_ids)
    row_by_id = {row.passage_id: row for row in rows}
    return [row_by_id[passage_id] for passage_id in passage_ids if passage_id in row_by_id]


async def neighboring_passages(
    self,
    review_id: str,
    passage_id: str,
    before: int,
    after: int,
    same_section: bool,
) -> list[ReviewPassageRow]:
    anchor = await self._fetch_passage_row(review_id, passage_id)
    if anchor is None:
        return []
    return await self._fetch_neighbor_rows(
        review_id=review_id,
        anchor=anchor,
        before=before,
        after=after,
        same_section=same_section,
    )
```

Order exact lookup results by requested `passage_ids`.

- [ ] **Step 6: Add service methods**

Convert rows to `ContextPassage`, apply truncation using existing packing helpers where possible, and return not-found diagnostics.

- [ ] **Step 7: Add MCP and REST surfaces**

Expose flat MCP arguments and matching REST routes. These surfaces must only read the review index and must not call PubTator or other upstream APIs.

- [ ] **Step 8: Run focused tests**

Run: `uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_rerag_repository.py tests/unit/mcp tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/repositories pubtator_link/services/review_context_service.py pubtator_link/mcp pubtator_link/api/routes/reviews.py tests/unit tests/test_routes/test_reviews.py
git commit -m "feat: add review passage addressability"
```

## Task 7: Audit Bundle Export

**Files:**
- Create: `pubtator_link/services/review_audit.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/unit/test_review_audit.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing audit service test**

Create a fake repository with sources, failed sources, totals, and retrieval-like passage rows. Assert exported JSON contains:

```python
assert bundle.review_id == "review-1"
assert bundle.generated_at is not None
assert bundle.preparation_status.complete == 1
assert bundle.totals.passage_count == 2
assert bundle.sources[0].coverage_reason == "full_text_available"
assert bundle.coverage_distribution["full_text"] == 1
assert bundle.resolver_attempts[0].source_kind == "pubtator_full_bioc"
assert bundle.search_runs[0].query == "MEFV colchicine"
assert bundle.retrieval_runs[0].queries == ["MEFV diagnosis", "colchicine response"]
assert bundle.passage_ids == ["PMID:1:title:0", "PMID:1:abstract:1"]
assert bundle.stable_citation_keys["PMID:1:title:0"].startswith("c_")
```

- [ ] **Step 2: Write failing MCP and route tests**

Assert `pubtator.export_review_audit_bundle` exists and returns `audit_bundle`.

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_audit.py tests/unit/mcp tests/test_routes/test_reviews.py -q`

Expected: FAIL because audit export does not exist.

- [ ] **Step 4: Add audit models**

Add models to `review_rerag.py`:

```python
class ReviewSearchRun(BaseModel):
    query: str
    filters: dict[str, object] = Field(default_factory=dict)
    source: str = "pubtator"
    returned_count: int = Field(default=0, ge=0)
    created_at: str | None = None


class ReviewRetrievalRun(BaseModel):
    queries: list[str]
    passage_ids: list[str] = Field(default_factory=list)
    created_at: str | None = None


class ReviewAuditBundle(BaseModel):
    success: bool = True
    review_id: str
    generated_at: str
    preparation_status: PreparationStatus
    totals: ReviewIndexTotals
    sources: list[ReviewSourceSummary]
    failed_sources: list[FailedSourceSummary]
    coverage_distribution: dict[str, int]
    resolver_attempts: list[ResolverAttemptSummary]
    search_runs: list[ReviewSearchRun] = Field(default_factory=list)
    retrieval_runs: list[ReviewRetrievalRun] = Field(default_factory=list)
    passage_ids: list[str]
    stable_citation_keys: dict[str, str]
```

- [ ] **Step 5: Add audit persistence**

Add a small append-only audit table to the review schema:

```sql
create table if not exists review_audit_events (
    review_id text not null,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists review_audit_events_review_id_idx
    on review_audit_events(review_id, created_at);
```

Add repository methods:

```python
async def record_review_audit_event(
    self,
    review_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> None:
    async with self._pool.acquire() as connection:
        await connection.execute(
            """
            insert into review_audit_events (review_id, event_type, payload)
            values ($1, $2, $3::jsonb)
            """,
            review_id,
            event_type,
            json.dumps(payload),
        )


async def list_review_audit_events(self, review_id: str) -> list[Mapping[str, object]]:
    async with self._pool.acquire() as connection:
        rows = await connection.fetch(
            """
            select event_type, payload, created_at
            from review_audit_events
            where review_id = $1
            order by created_at asc
            """,
            review_id,
        )
    return [
        {
            "event_type": row["event_type"],
            "payload": row["payload"],
            "created_at": row["created_at"].isoformat(),
        }
        for row in rows
    ]
```

Add `import json` and `from collections.abc import Mapping` if they are not already present in `pubtator_link/repositories/review_rerag.py`.

- [ ] **Step 6: Record search and retrieval events**

Record an audit event when review indexing is requested and when batch retrieval completes:

```python
await repository.record_review_audit_event(
    review_id,
    "retrieval_run",
    {
        "queries": request.queries,
        "passage_ids": [passage.passage_id for passage in response.merged_context_pack.passages],
    },
)
```

If search-result recording is not naturally attached to a `review_id` yet, record only review-scoped index/retrieval events in this task and leave `search_runs=[]` in the bundle with a code comment explaining that search runs require review-bound search initiation.

- [ ] **Step 7: Add audit service**

Implement `ReviewAuditService.export_bundle(review_id: str)` using repository data. Compute `coverage_distribution` from `ReviewSourceSummary.coverage`, flatten resolver attempts from sources and failed sources, list passage IDs from the index, and compute stable citation keys with `stable_citation_key_for_passage`.

- [ ] **Step 8: Add MCP and REST surfaces**

Expose `pubtator.export_review_audit_bundle` and a REST route consistent with existing review routes.

- [ ] **Step 9: Run focused tests**

Run: `uv run pytest tests/unit/test_review_audit.py tests/unit/mcp tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pubtator_link/services/review_audit.py pubtator_link/models/review_rerag.py pubtator_link/repositories pubtator_link/mcp pubtator_link/api/routes/reviews.py tests/unit/test_review_audit.py tests/unit/mcp tests/test_routes/test_reviews.py
git commit -m "feat: export review audit bundle"
```

## Task 8: Documentation, Review Memo Completion Markers, And Final Verification

**Files:**
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/development/operations-runbook.md`
- Modify: `docs/superpowers/plans/2026-05-01-scientific-auditability-source-resilience-implementation.md`

- [ ] **Step 1: Update MCP usage docs**

Document the new tools and recommended workflow:

1. `pubtator.search_literature`
2. `pubtator.preflight_review_sources`
3. `pubtator.index_review_evidence`
4. `pubtator.inspect_review_index`
5. `pubtator.retrieve_review_context_batch`
6. `pubtator.get_review_passages_by_id` or `pubtator.get_neighboring_review_passages`
7. `pubtator.export_review_audit_bundle`

- [ ] **Step 2: Update operations notes**

Add a short section explaining retry/backoff behavior, conservative concurrency defaults, and how to interpret source coverage failures.

- [ ] **Step 3: Update the scientific review memo**

In `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`, add a section near the top:

```markdown
## Implementation Status

Updated: 2026-05-01

- [x] Coverage preflight, resolver attempts, and coverage reasons.
- [x] Retry/backoff and transient failure transparency.
- [x] Bounded async parallelism for batch retrieval and source preflight.
- [x] Passage-by-ID and neighboring passage tools.
- [ ] Typed MCP output schemas for high-use tools.
- [ ] Review index inventory and TTL cleanup.
- [x] PRISMA-style audit bundle foundation.
- [ ] GRADE-style evidence certainty storage.
- [ ] Optional Europe PMC fallback.
- [ ] Real `candidate_fast` prepare mode or public removal.
```

If any item from this implementation plan was not completed, leave it unchecked and add a one-sentence note explaining the gap.

- [ ] **Step 4: Mark this implementation plan as completed task-by-task**

As each task is completed, update this plan's checkboxes for the completed task before committing that task or in the final docs commit. Do not mark tasks complete before their verification command passes.

- [ ] **Step 5: Run full verification**

Run: `make ci-local`

Expected: formatting check, lint, typecheck, and test suite all pass.

- [ ] **Step 6: Run coverage verification**

Run: `make test-cov`

Expected: coverage remains at or above the current threshold and the command passes.

- [ ] **Step 7: Commit docs and completion markers**

```bash
git add docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md docs/MCP_CONNECTION_GUIDE.md docs/development/operations-runbook.md docs/superpowers/plans/2026-05-01-scientific-auditability-source-resilience-implementation.md
git commit -m "docs: document review auditability workflow"
```

## Final Verification

- [ ] Run `make ci-local`.
- [ ] Run `make test-cov`.
- [ ] Confirm MCP tools list includes the new tools.
- [ ] Confirm `inspect_review_index` reports resolver attempts and coverage reasons.
- [ ] Confirm `export_review_audit_bundle` includes passage IDs and stable citation keys.
- [ ] Confirm the scientific review memo's implementation status checkboxes reflect the actual completed work.
