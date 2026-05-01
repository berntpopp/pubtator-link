# GRADE Certainty, Europe PMC Fallback, And Candidate Fast Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-supplied GRADE-style evidence certainty storage, add opt-in Europe PMC open-access fallback, and remove the misleading public `candidate_fast` prepare mode.

**Architecture:** Extend the existing review model/repository/audit surfaces additively for certainty records, add a disabled-by-default Europe PMC resolver path behind explicit configuration, and tighten the shared `PrepareMode` type so public schemas expose only implemented behavior. Keep hosted MCP behavior research-use scoped and non-destructive by default.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic, asyncpg/PostgreSQL, httpx, pytest, pytest-asyncio, respx or httpx MockTransport, Ruff, mypy, Makefile targets.

---

## File Structure

- Modify `pubtator_link/models/review_rerag.py` for evidence certainty models and `PrepareMode` cleanup.
- Modify `pubtator_link/db/review_schema.sql` for `review_evidence_certainty`.
- Modify `pubtator_link/repositories/review_rerag.py` and `pubtator_link/repositories/review_rerag_mappers.py` for certainty CRUD and audit export data.
- Modify `pubtator_link/services/review_audit.py` to include certainty records in audit bundles.
- Create `pubtator_link/services/europe_pmc.py` for the optional Europe PMC client/resolver helper.
- Modify `pubtator_link/services/full_text_preparation.py` and `pubtator_link/services/source_preflight.py` to use Europe PMC only when enabled.
- Modify `pubtator_link/config.py` for Europe PMC fallback configuration.
- Modify `pubtator_link/api/routes/reviews.py` for certainty routes.
- Modify `pubtator_link/mcp/tools/review.py`, `pubtator_link/mcp/service_adapters.py`, `pubtator_link/mcp/facade.py`, and `pubtator_link/mcp/resources.py` for certainty MCP tools and candidate-fast documentation cleanup.
- Add or extend tests under `tests/unit/`, `tests/unit/mcp/`, and `tests/test_routes/`.

## Task 1: Add GRADE-Style Certainty Models And Schema

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/db/review_schema.sql`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_schema_sql.py`

- [ ] **Step 1: Add failing model tests**

In `tests/unit/test_review_rerag_models.py`, add:

```python
import pytest
from pydantic import ValidationError

from pubtator_link.models.review_rerag import (
    EvidenceCertaintyRecord,
    UpsertEvidenceCertaintyRequest,
)


def test_evidence_certainty_request_stores_grade_domains_without_computing() -> None:
    request = UpsertEvidenceCertaintyRequest(
        outcome="FMF attack recurrence",
        question="Does colchicine reduce attacks in FMF?",
        study_design="randomized trial",
        risk_of_bias_notes="Allocation concealment unclear in one study.",
        inconsistency_notes="Effects point in same direction.",
        indirectness_notes="Population matches review question.",
        imprecision_notes="Confidence interval crosses small benefit threshold.",
        publication_bias_notes="Small-study effects not assessed.",
        overall_certainty="moderate",
        certainty_rationale="Downgraded once for imprecision.",
        passage_ids=["PMID:123:abstract:0"],
        created_by="client:test",
    )

    assert request.overall_certainty == "moderate"
    assert request.passage_ids == ["PMID:123:abstract:0"]


def test_evidence_certainty_rejects_empty_outcome() -> None:
    with pytest.raises(ValidationError):
        UpsertEvidenceCertaintyRequest(outcome="", overall_certainty="not_rated")


def test_evidence_certainty_record_has_stable_identifier() -> None:
    record = EvidenceCertaintyRecord(
        certainty_id="00000000-0000-0000-0000-000000000001",
        review_id="review-1",
        outcome="Mortality",
        overall_certainty="low",
        created_at="2026-05-01T00:00:00Z",
        updated_at="2026-05-01T00:00:00Z",
    )

    assert record.review_id == "review-1"
    assert record.overall_certainty == "low"
```

- [ ] **Step 2: Add failing schema tests**

In `tests/unit/test_review_schema_sql.py`, add:

```python
def test_schema_defines_review_evidence_certainty_table() -> None:
    assert "create table if not exists review_evidence_certainty" in SCHEMA
    assert "certainty_id uuid primary key" in SCHEMA
    assert "overall_certainty text not null" in SCHEMA
    assert "passage_ids text[] not null default '{}'" in SCHEMA
    assert "review_evidence_certainty_review_id_idx" in SCHEMA
```

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q`

Expected: FAIL because certainty models and schema are missing.

- [ ] **Step 4: Add certainty models**

In `pubtator_link/models/review_rerag.py`, add:

```python
EvidenceCertaintyLabel = Literal["high", "moderate", "low", "very_low", "not_rated"]


class UpsertEvidenceCertaintyRequest(BaseModel):
    """User/client-supplied GRADE-style certainty judgment."""

    outcome: str = Field(min_length=1)
    question: str | None = None
    study_design: str | None = None
    risk_of_bias_notes: str | None = None
    inconsistency_notes: str | None = None
    indirectness_notes: str | None = None
    imprecision_notes: str | None = None
    publication_bias_notes: str | None = None
    overall_certainty: EvidenceCertaintyLabel = "not_rated"
    certainty_rationale: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    validate_passages: bool = False


class EvidenceCertaintyRecord(BaseModel):
    certainty_id: str
    review_id: str
    outcome: str
    question: str | None = None
    study_design: str | None = None
    risk_of_bias_notes: str | None = None
    inconsistency_notes: str | None = None
    indirectness_notes: str | None = None
    imprecision_notes: str | None = None
    publication_bias_notes: str | None = None
    overall_certainty: EvidenceCertaintyLabel = "not_rated"
    certainty_rationale: str | None = None
    passage_ids: list[str] = Field(default_factory=list)
    unresolved_passage_ids: list[str] = Field(default_factory=list)
    created_by: str | None = None
    created_at: str
    updated_at: str


class EvidenceCertaintyResponse(BaseModel):
    success: bool = True
    record: EvidenceCertaintyRecord


class ListEvidenceCertaintyResponse(BaseModel):
    success: bool = True
    records: list[EvidenceCertaintyRecord] = Field(default_factory=list)
```

Extend `ReviewAuditBundle` with:

```python
evidence_certainty: list[EvidenceCertaintyRecord] = Field(default_factory=list)
```

- [ ] **Step 5: Add certainty schema**

In `pubtator_link/db/review_schema.sql`, add:

```sql
create table if not exists review_evidence_certainty (
    certainty_id uuid primary key,
    review_id text not null references reviews(review_id),
    outcome text not null,
    question text,
    study_design text,
    risk_of_bias_notes text,
    inconsistency_notes text,
    indirectness_notes text,
    imprecision_notes text,
    publication_bias_notes text,
    overall_certainty text not null,
    certainty_rationale text,
    passage_ids text[] not null default '{}',
    unresolved_passage_ids text[] not null default '{}',
    created_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists review_evidence_certainty_review_id_idx
    on review_evidence_certainty(review_id, updated_at);
```

- [ ] **Step 6: Run model and schema tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q`

Expected: PASS.

- [ ] **Step 7: Commit certainty models and schema**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/db/review_schema.sql tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py
git commit -m "feat: add evidence certainty models"
```

## Task 2: Add Certainty Repository, Service, REST, MCP, And Audit Export

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag_mappers.py`
- Modify: `pubtator_link/services/review_audit.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Test: `tests/unit/test_review_rerag_mappers.py`
- Test: `tests/unit/test_review_rerag_repository.py`
- Test: `tests/unit/test_review_audit.py`
- Test: `tests/test_routes/test_reviews.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Add failing mapper and audit tests**

In `tests/unit/test_review_rerag_mappers.py`, add:

```python
from pubtator_link.repositories.review_rerag_mappers import _evidence_certainty_from_row


def test_evidence_certainty_mapper_preserves_grade_notes() -> None:
    row = {
        "certainty_id": "00000000-0000-0000-0000-000000000001",
        "review_id": "review-1",
        "outcome": "Mortality",
        "question": "Question",
        "study_design": "observational",
        "risk_of_bias_notes": "Serious",
        "inconsistency_notes": None,
        "indirectness_notes": None,
        "imprecision_notes": None,
        "publication_bias_notes": None,
        "overall_certainty": "low",
        "certainty_rationale": "Downgraded twice.",
        "passage_ids": ["PMID:1:abstract:0"],
        "unresolved_passage_ids": [],
        "created_by": "client:test",
        "created_at": "2026-05-01T00:00:00Z",
        "updated_at": "2026-05-01T00:00:00Z",
    }

    record = _evidence_certainty_from_row(row)

    assert record.overall_certainty == "low"
    assert record.risk_of_bias_notes == "Serious"
    assert record.passage_ids == ["PMID:1:abstract:0"]
```

In `tests/unit/test_review_audit.py`, extend the fake repository with
`list_evidence_certainty` and assert exported bundles include
`evidence_certainty`.

- [ ] **Step 2: Add failing route and MCP tests**

In `tests/test_routes/test_reviews.py`, add route tests for:

```python
client.post("/api/reviews/review-1/certainty", json={...})
client.get("/api/reviews/review-1/certainty")
client.get("/api/reviews/review-1/certainty/00000000-0000-0000-0000-000000000001")
```

In `tests/unit/mcp/test_mcp_facade.py`, add public tools:

```python
"pubtator.add_evidence_certainty",
"pubtator.list_evidence_certainty",
"pubtator.get_evidence_certainty",
```

Assert `pubtator.delete_evidence_certainty` is absent by default.

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_mappers.py tests/unit/test_review_audit.py tests/test_routes/test_reviews.py tests/unit/mcp/test_mcp_facade.py -q`

Expected: FAIL because certainty persistence and public surfaces are missing.

- [ ] **Step 4: Add repository mapper and methods**

In `review_rerag_mappers.py`, add `_evidence_certainty_from_row`.

In `ReviewReragRepository`, add:

```python
async def upsert_evidence_certainty(
    self,
    review_id: str,
    request: UpsertEvidenceCertaintyRequest,
    *,
    certainty_id: str | None = None,
) -> EvidenceCertaintyRecord:
    ...

async def list_evidence_certainty(self, review_id: str) -> list[EvidenceCertaintyRecord]:
    ...

async def get_evidence_certainty(
    self,
    review_id: str,
    certainty_id: str,
) -> EvidenceCertaintyRecord | None:
    ...

async def delete_evidence_certainty(self, review_id: str, certainty_id: str) -> bool:
    ...
```

When `request.validate_passages` is true, query existing `review_passages` and
put missing IDs into `unresolved_passage_ids` while still storing the record.

- [ ] **Step 5: Add service adapter and routes**

Use repository methods directly from route dependencies or add a small
`ReviewEvidenceCertaintyService` if route logic grows beyond validation and
permission checks. Route responses must use `EvidenceCertaintyResponse` and
`ListEvidenceCertaintyResponse`.

Add MCP adapters:

```python
async def add_evidence_certainty_impl(... ) -> dict[str, Any]:
    response = await service.add_or_update(...)
    return response.model_dump(mode="json")

async def list_evidence_certainty_impl(... ) -> dict[str, Any]:
    response = await service.list(...)
    return response.model_dump(mode="json")
```

- [ ] **Step 6: Include certainty records in audit bundle**

In `ReviewAuditService.export_bundle`, fetch:

```python
certainty_records = await self.repository.list_evidence_certainty(review_id)
```

and pass `evidence_certainty=certainty_records` to `ReviewAuditBundle`.

- [ ] **Step 7: Run certainty focused tests**

Run: `uv run pytest tests/unit/test_review_rerag_mappers.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_audit.py tests/test_routes/test_reviews.py tests/unit/mcp -q`

Expected: PASS.

- [ ] **Step 8: Commit certainty persistence and surfaces**

```bash
git add pubtator_link/repositories pubtator_link/services pubtator_link/api/routes pubtator_link/mcp tests/unit tests/test_routes
git commit -m "feat: add review evidence certainty storage"
```

## Task 3: Add Disabled-By-Default Europe PMC Configuration And Client

**Files:**
- Modify: `pubtator_link/config.py`
- Create: `pubtator_link/services/europe_pmc.py`
- Test: `tests/unit/test_review_rerag_config.py`
- Test: `tests/unit/test_europe_pmc.py`

- [ ] **Step 1: Add failing config tests**

In `tests/unit/test_review_rerag_config.py`, add:

```python
from pubtator_link.config import ReviewReragConfig, ServerSettings


def test_europe_pmc_fallback_is_disabled_by_default() -> None:
    config = ReviewReragConfig.from_settings(ServerSettings())

    assert config.enable_europe_pmc_fallback is False
    assert config.europe_pmc_rate_limit_per_second <= 1.0
    assert config.europe_pmc_max_concurrency == 1
```

- [ ] **Step 2: Add failing Europe PMC client tests**

Create `tests/unit/test_europe_pmc.py` using `httpx.MockTransport`:

```python
import httpx
import pytest

from pubtator_link.services.europe_pmc import EuropePmcClient


@pytest.mark.asyncio
async def test_europe_pmc_client_returns_open_access_xml() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "PMC123" in str(request.url)
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {
                            "pmcid": "PMC123",
                            "isOpenAccess": "Y",
                            "license": "CC BY",
                            "fullTextUrlList": {
                                "fullTextUrl": [
                                    {"availability": "Open access", "url": "https://example.org/full.xml"}
                                ]
                            },
                        }
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = EuropePmcClient(http_client=http_client, base_url="https://example.org")
        result = await client.lookup_open_access_record("PMC123")

    assert result.available is True
    assert result.pmcid == "PMC123"
    assert result.license_or_access_hint == "CC BY"
```

Add tests for not open access, not found, and transient `503` retry if the shared retry helper is available.

- [ ] **Step 3: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_config.py tests/unit/test_europe_pmc.py -q`

Expected: FAIL because config and client are missing.

- [ ] **Step 4: Add config fields**

In `ServerSettings`, add:

```python
enable_europe_pmc_fallback: bool = Field(
    default=False,
    description="Enable opt-in Europe PMC open-access fallback for review preparation",
)
europe_pmc_base_url: str = Field(default="https://www.ebi.ac.uk/europepmc/webservices/rest")
europe_pmc_rate_limit_per_second: float = Field(default=1.0, gt=0, le=5)
europe_pmc_timeout_seconds: int = Field(default=20, ge=2, le=120)
europe_pmc_max_concurrency: int = Field(default=1, ge=1, le=5)
```

Mirror the fields in `ReviewReragConfig.from_settings`.

- [ ] **Step 5: Add Europe PMC client**

Create `pubtator_link/services/europe_pmc.py`:

```python
from __future__ import annotations

from pydantic import BaseModel
import httpx


class EuropePmcLookupResult(BaseModel):
    available: bool
    pmcid: str | None = None
    doi: str | None = None
    license_or_access_hint: str | None = None
    full_text_url: str | None = None
    reason: str = "unknown"


class EuropePmcClient:
    def __init__(self, *, http_client: httpx.AsyncClient, base_url: str) -> None:
        self.http_client = http_client
        self.base_url = base_url.rstrip("/")

    async def lookup_open_access_record(self, pmcid_or_pmid: str) -> EuropePmcLookupResult:
        response = await self.http_client.get(
            f"{self.base_url}/search",
            params={"query": pmcid_or_pmid, "format": "json", "resultType": "core"},
        )
        if response.status_code == 404:
            return EuropePmcLookupResult(available=False, reason="upstream_404")
        response.raise_for_status()
        payload = response.json()
        records = payload.get("resultList", {}).get("result", [])
        if not records:
            return EuropePmcLookupResult(available=False, reason="not_found")
        record = records[0]
        if str(record.get("isOpenAccess", "")).upper() != "Y":
            return EuropePmcLookupResult(
                available=False,
                pmcid=record.get("pmcid"),
                doi=record.get("doi"),
                reason="license_reuse_unavailable",
            )
        urls = record.get("fullTextUrlList", {}).get("fullTextUrl", [])
        full_text_url = next((item.get("url") for item in urls if item.get("url")), None)
        return EuropePmcLookupResult(
            available=full_text_url is not None,
            pmcid=record.get("pmcid"),
            doi=record.get("doi"),
            license_or_access_hint=record.get("license") or "open_access",
            full_text_url=full_text_url,
            reason="full_text_available" if full_text_url else "parser_unsupported",
        )
```

- [ ] **Step 6: Run config and client tests**

Run: `uv run pytest tests/unit/test_review_rerag_config.py tests/unit/test_europe_pmc.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Europe PMC config and client**

```bash
git add pubtator_link/config.py pubtator_link/services/europe_pmc.py tests/unit/test_review_rerag_config.py tests/unit/test_europe_pmc.py
git commit -m "feat: add europe pmc fallback client"
```

## Task 4: Wire Optional Europe PMC Fallback Into Preflight And Preparation

**Files:**
- Modify: `pubtator_link/services/source_preflight.py`
- Modify: `pubtator_link/services/full_text_preparation.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/mcp/resources.py`
- Test: `tests/unit/test_source_preflight.py`
- Test: `tests/unit/test_full_text_preparation.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add failing preflight and preparation tests**

In `tests/unit/test_source_preflight.py`, add a fake Europe PMC client and assert:

```python
assert hint.pmc_fallback_available is True
assert any(attempt.source_kind == "europe_pmc_jats" for attempt in hint.resolver_attempts)
```

when `enable_europe_pmc_fallback=True`. Add a paired test proving no Europe PMC
attempt is made when the flag is false.

In `tests/unit/test_full_text_preparation.py`, add a test where PubTator/PMC
paths fail, Europe PMC returns open-access XML, and the repository records a
successful `source_kind="europe_pmc_jats"` attempt.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_source_preflight.py tests/unit/test_full_text_preparation.py -q`

Expected: FAIL because Europe PMC is not wired into preflight or preparation.

- [ ] **Step 3: Inject Europe PMC dependencies**

In `api/routes/dependencies.py`, create Europe PMC client/service only when
`review_rerag_config.enable_europe_pmc_fallback` is true. Pass `None` otherwise.
The preparation and preflight services should accept an optional Europe PMC
client and branch only when it is present and enabled.

- [ ] **Step 4: Add preflight Europe PMC attempt**

In `SourcePreflightService`, after PMC/BioC-PMC probes and before final
abstract-only classification, call `EuropePmcClient.lookup_open_access_record`
when enabled. Add `ResolverAttemptSummary(source_kind="europe_pmc_jats", ...)`
with `coverage_reason` and license metadata.

- [ ] **Step 5: Add preparation Europe PMC fallback**

In `FullTextPreparationService.prepare_pmid`, after PubTator/PMC fallbacks fail
and before PubTator abstract fallback, call Europe PMC. If XML parsing support is
not already available, parse enough JATS section text to create
`ReviewPassageRow` values with `source_kind="europe_pmc_jats"` and
`coverage="full_text"` in inspection. If parsing fails, record
`terminal_reason="parser_unsupported"` and continue to abstract fallback.

- [ ] **Step 6: Update capability resource**

In `pubtator_link/mcp/resources.py`, include a capability field:

```python
"europe_pmc_fallback": {
    "enabled": review_rerag_config.enable_europe_pmc_fallback,
    "default": "disabled",
    "scope": "open_access_records_only",
}
```

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_source_preflight.py tests/unit/test_full_text_preparation.py tests/unit/mcp/test_mcp_facade.py -q`

Expected: PASS.

- [ ] **Step 8: Commit Europe PMC wiring**

```bash
git add pubtator_link/services pubtator_link/api/routes/dependencies.py pubtator_link/mcp/resources.py tests/unit/test_source_preflight.py tests/unit/test_full_text_preparation.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: enable optional europe pmc fallback"
```

## Task 5: Remove Public `candidate_fast` Prepare Mode

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/prompts.py`
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Add failing candidate-fast removal tests**

In `tests/unit/test_review_rerag_models.py`, change or add:

```python
import pytest
from pydantic import ValidationError

from pubtator_link.models.review_rerag import IndexReviewEvidenceRequest


def test_index_review_evidence_rejects_candidate_fast_prepare_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="candidate_fast")
```

In `tests/unit/mcp/test_review_rerag_mcp.py`, add:

```python
def test_index_review_evidence_mcp_schema_does_not_advertise_candidate_fast() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    schema = mcp._tool_manager._tools["pubtator.index_review_evidence"].parameters
    prepare_mode_schema = schema["properties"]["prepare_mode"]

    assert "candidate_fast" not in str(prepare_mode_schema)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py tests/test_routes/test_reviews.py -q`

Expected: FAIL because `candidate_fast` is currently accepted.

- [ ] **Step 3: Tighten PrepareMode**

In `pubtator_link/models/review_rerag.py`, change:

```python
PrepareMode = Literal["selected", "candidate_fast"]
```

to:

```python
PrepareMode = Literal["selected"]
```

Keep `prepare_mode: PrepareMode = "selected"` for one release so clients receive
a precise enum validation error instead of an unknown-field behavior change.

- [ ] **Step 4: Remove candidate-fast documentation**

Search and update docs/resources/prompts:

```bash
rg -n "candidate_fast|prepare_mode" pubtator_link docs tests
```

Remove public references that imply `candidate_fast` is available. In the review
memo, mark only the `candidate_fast` decision item complete after this code
change is verified.

Add a note that the no-op public mode was removed and a future fast-candidate
workflow should be designed as a separate search-candidate endpoint.

- [ ] **Step 5: Run focused tests**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 6: Commit candidate-fast cleanup**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/mcp pubtator_link/api docs tests/unit/test_review_rerag_models.py tests/unit/mcp/test_review_rerag_mcp.py tests/test_routes/test_reviews.py
git commit -m "feat: remove public candidate fast prepare mode"
```

## Task 6: Final Verification And Review Memo Update

**Files:**
- Modify: `docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`

- [ ] **Step 1: Update review memo implementation status**

Only after the relevant code tasks pass, update the review memo so the
GRADE-style evidence certainty storage, optional Europe PMC fallback, and public
`candidate_fast` removal items are marked complete.

Do not mark typed MCP output schemas or review index lifecycle complete from this
plan unless the Phase 1 plan has already been implemented and verified.

- [ ] **Step 2: Run focused verification**

Run: `uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/unit/test_review_audit.py tests/unit/test_source_preflight.py tests/unit/test_europe_pmc.py tests/test_routes/test_reviews.py tests/unit/mcp -q`

Expected: PASS.

- [ ] **Step 3: Run required repo verification**

Run: `make ci-local`

Expected: PASS.

- [ ] **Step 4: Commit final docs update**

```bash
git add docs/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md
git commit -m "docs: mark remaining scientific roadmap items complete"
```
