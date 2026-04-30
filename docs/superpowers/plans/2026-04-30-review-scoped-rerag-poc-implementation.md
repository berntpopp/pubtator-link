# Review-Scoped Re-RAG POC Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a fast proof of concept for review-scoped background evidence preparation and per-request PostgreSQL full-text re-RAG context retrieval.

**Architecture:** The POC stores review identities, preparation jobs, retrieval attempts, and normalized passages in PostgreSQL. Full-text preparation runs through a bounded in-process asyncio queue with PostgreSQL advisory locks, source-attempt auditing, URL fetch safety, and abstract fallback. Retrieval uses PostgreSQL FTS for candidate selection and deterministic Python reranking/packing; Docling is a disabled-by-default PDF fallback path.

**Tech Stack:** FastAPI, FastMCP, Pydantic v2, asyncpg, PostgreSQL FTS, httpx, asyncio, Ruff, mypy, pytest, respx.

---

## Source Spec

Implement from:

- `docs/superpowers/specs/2026-04-30-review-scoped-rerag-poc-design.md`

Keep the parent broad workflow plan unchanged unless a task explicitly says to edit it:

- `docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md`

## Parallel Execution Strategy

For maximum speed, execute in this order:

1. Task 1 first. It adds dependencies and config needed by all other code.
2. Task 2 second. It locks models and schema names used by later tasks.
3. After Task 2, these can run in parallel with disjoint write sets:
   - Task 3 URL safety.
   - Task 4 repository.
   - Task 5 full-text preparation source normalization.
   - Task 7 retrieval/reranking.
4. Task 6 background queue depends on Task 4 and Task 5.
5. Task 8 routes depends on Tasks 4, 6, and 7.
6. Task 9 MCP depends on Task 8 service contracts.
7. Task 10 is final integration and verification.

Workers must not revert edits made by other workers. Each task owns the files listed in that task.

## File Structure

- Create `pubtator_link/models/review_rerag.py`
  - Pydantic request/response models, internal row models, status literals, and context-pack models.
- Create `pubtator_link/db/review_schema.sql`
  - PostgreSQL schema for reviews, preparation jobs, retrieval attempts, and review passages.
- Create `pubtator_link/repositories/review_rerag.py`
  - Repository protocol plus asyncpg implementation.
- Create `pubtator_link/services/url_safety.py`
  - SSRF-safe URL validation and bounded fetch helpers for curated URLs and PDF downloads.
- Create `pubtator_link/services/full_text_preparation.py`
  - Source cascade, BioC normalization, PDF detection, Docling boundary, and source-attempt recording.
- Create `pubtator_link/services/review_preparation_queue.py`
  - In-process asyncio queue, startup repair, deduplication, advisory lock execution, and status summaries.
- Create `pubtator_link/services/review_context_service.py`
  - PostgreSQL FTS request mapping, deterministic reranking, diversity, and context packing.
- Create `pubtator_link/api/routes/reviews.py`
  - REST endpoints for `index_review_evidence` and `retrieve_review_context`.
- Modify `pubtator_link/api/routes/__init__.py`
  - Export `reviews_router`.
- Modify `pubtator_link/api/routes/dependencies.py`
  - Add repository, queue, full-text, and context service dependencies with cleanup.
- Modify `pubtator_link/server_manager.py`
  - Include reviews router and start/stop the review preparation queue.
- Modify `pubtator_link/mcp/tools.py`
  - Add MCP request models.
- Modify `pubtator_link/mcp/service_adapters.py`
  - Add adapter functions for review indexing and context retrieval.
- Modify `pubtator_link/mcp/facade.py`
  - Expose `pubtator.index_review_evidence` and `pubtator.retrieve_review_context`.
- Modify `pubtator_link/mcp/resources.py`
  - Include review re-RAG tools in capabilities.
- Modify `pubtator_link/config.py`
  - Add database and review preparation settings.
- Modify `Makefile`
  - Add `db-init`.
- Modify `pyproject.toml` and `uv.lock`
  - Add `asyncpg`; keep Docling out of required dependencies for the POC unless the user explicitly enables it later.
- Create tests under `tests/unit/`, `tests/test_routes/`, and `tests/integration/`.

## Task 1: Add Configuration and Dependency Lock

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `pubtator_link/config.py`
- Test: `tests/unit/test_review_rerag_config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/unit/test_review_rerag_config.py`:

```python
from pubtator_link.config import ReviewReragConfig, ServerSettings


def test_review_rerag_config_defaults_are_fast_poc_values() -> None:
    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)

    assert config.database_url is None
    assert config.prep_concurrency == 2
    assert config.document_timeout_seconds == 60
    assert config.source_timeout_seconds == 20
    assert config.pdf_max_bytes == 50 * 1024 * 1024
    assert config.text_max_bytes == 10 * 1024 * 1024
    assert config.allow_http_urls is False
    assert config.enable_docling is False


def test_review_rerag_config_reads_prefixed_env(monkeypatch) -> None:
    monkeypatch.setenv("PUBTATOR_LINK_DATABASE_URL", "postgresql://user:pass@localhost/db")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_CONCURRENCY", "4")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_DOCUMENT_TIMEOUT_SECONDS", "30")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_SOURCE_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_PDF_MAX_BYTES", "12345")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_PREP_TEXT_MAX_BYTES", "6789")
    monkeypatch.setenv("PUBTATOR_LINK_ALLOW_HTTP_URLS", "true")
    monkeypatch.setenv("PUBTATOR_LINK_ENABLE_DOCLING", "true")

    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)

    assert config.database_url == "postgresql://user:pass@localhost/db"
    assert config.prep_concurrency == 4
    assert config.document_timeout_seconds == 30
    assert config.source_timeout_seconds == 10
    assert config.pdf_max_bytes == 12345
    assert config.text_max_bytes == 6789
    assert config.allow_http_urls is True
    assert config.enable_docling is True
```

- [ ] **Step 2: Run config tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_config.py -q
```

Expected: FAIL with `ImportError` or `AttributeError` because `ReviewReragConfig` does not exist.

- [ ] **Step 3: Add config fields and dataclass**

Modify `pubtator_link/config.py` by adding fields to `ServerSettings` after feature flags:

```python
    # Review-scoped re-RAG POC
    database_url: str | None = Field(default=None, description="PostgreSQL database URL")
    review_prep_concurrency: int = Field(
        default=2, ge=1, le=8, description="Concurrent review evidence preparation jobs"
    )
    review_prep_document_timeout_seconds: int = Field(
        default=60, ge=5, le=600, description="Per-document preparation timeout"
    )
    review_prep_source_timeout_seconds: int = Field(
        default=20, ge=2, le=120, description="Per-source retrieval timeout"
    )
    review_prep_pdf_max_bytes: int = Field(
        default=50 * 1024 * 1024, ge=1024, description="Maximum downloaded PDF bytes"
    )
    review_prep_text_max_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, description="Maximum downloaded text/XML/HTML bytes"
    )
    allow_http_urls: bool = Field(
        default=False, description="Allow http URLs for local curated URL development"
    )
    enable_docling: bool = Field(default=False, description="Enable Docling PDF fallback")
```

Add this dataclass after `CacheConfig`:

```python
@dataclass(frozen=True)
class ReviewReragConfig:
    """Review-scoped re-RAG POC configuration."""

    database_url: str | None
    prep_concurrency: int
    document_timeout_seconds: int
    source_timeout_seconds: int
    pdf_max_bytes: int
    text_max_bytes: int
    allow_http_urls: bool
    enable_docling: bool

    @classmethod
    def from_settings(cls, server_settings: ServerSettings) -> "ReviewReragConfig":
        return cls(
            database_url=server_settings.database_url,
            prep_concurrency=server_settings.review_prep_concurrency,
            document_timeout_seconds=server_settings.review_prep_document_timeout_seconds,
            source_timeout_seconds=server_settings.review_prep_source_timeout_seconds,
            pdf_max_bytes=server_settings.review_prep_pdf_max_bytes,
            text_max_bytes=server_settings.review_prep_text_max_bytes,
            allow_http_urls=server_settings.allow_http_urls,
            enable_docling=server_settings.enable_docling,
        )
```

Add this global instance near `cache_config`:

```python
review_rerag_config = ReviewReragConfig.from_settings(settings)
```

- [ ] **Step 4: Add asyncpg dependency**

Modify `pyproject.toml` dependencies:

```toml
    "asyncpg>=0.30.0,<1.0.0",
```

Run:

```bash
uv lock
```

Expected: `uv.lock` updates successfully.

- [ ] **Step 5: Run config tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_config.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock pubtator_link/config.py tests/unit/test_review_rerag_config.py
git commit -m "feat: add review rerag configuration"
```

## Task 2: Add Models, Schema, and DB Init Target

**Files:**
- Create: `pubtator_link/models/review_rerag.py`
- Create: `pubtator_link/db/review_schema.sql`
- Modify: `Makefile`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_schema_sql.py`

- [ ] **Step 1: Write failing model tests**

Create `tests/unit/test_review_rerag_models.py`:

```python
from pydantic import ValidationError
import pytest

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    IndexReviewEvidenceRequest,
    PreparationStatus,
    RetrieveReviewContextRequest,
    normalize_section,
    passage_id_for_pmid,
)


def test_index_request_rejects_screened_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="screened")


def test_context_request_defaults_are_poc_values() -> None:
    request = RetrieveReviewContextRequest(question="Should colchicine treat FMF?")

    assert request.max_passages == 8
    assert request.max_chars == 6000
    assert request.max_passages_per_pmid == 2


def test_passage_id_generation_is_deterministic() -> None:
    assert normalize_section("Methods & Results") == "methods_results"
    assert passage_id_for_pmid("40234174", "Methods & Results", 3) == (
        "PMID:40234174:methods_results:3"
    )


def test_context_pack_citation_map_uses_passage_ids() -> None:
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:40234174:abstract:0",
        pmid="40234174",
        section="abstract",
        text="Colchicine should start after clinical diagnosis.",
    )
    pack = ContextPack(
        question="When should colchicine start?",
        passages=[passage],
        citation_map={"S1": "PMID:40234174:abstract:0"},
    )

    assert pack.citation_map["S1"] == pack.passages[0].passage_id


def test_preparation_status_counts_terms() -> None:
    status = PreparationStatus(queued=1, running=2, complete=3, partial=4, failed=5)

    assert status.running == 2
    assert status.partial == 4
```

- [ ] **Step 2: Write failing schema tests**

Create `tests/unit/test_review_schema_sql.py`:

```python
from pathlib import Path


SCHEMA = Path("pubtator_link/db/review_schema.sql").read_text()


def test_schema_defines_required_tables_and_constraints() -> None:
    assert "create table if not exists reviews" in SCHEMA
    assert "review_id text primary key" in SCHEMA
    assert "create table if not exists review_preparation_jobs" in SCHEMA
    assert "unique(review_id, source_id)" in SCHEMA
    assert "create table if not exists full_text_retrieval_attempts" in SCHEMA
    assert "attempt_id uuid primary key" in SCHEMA
    assert "create table if not exists review_passages" in SCHEMA
    assert "primary key(review_id, passage_id)" in SCHEMA


def test_schema_defines_generated_search_vector_and_indexes() -> None:
    assert "search_vector tsvector generated always as" in SCHEMA
    assert "to_tsvector('english'" in SCHEMA
    assert "using gin(search_vector)" in SCHEMA
    assert "using gin(entity_ids)" in SCHEMA
    assert "review_passages_review_id_pmid_idx" in SCHEMA
    assert "review_attempts_audit_idx" in SCHEMA
```

- [ ] **Step 3: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q
```

Expected: FAIL because the model and schema files do not exist.

- [ ] **Step 4: Implement models**

Create `pubtator_link/models/review_rerag.py`:

```python
"""Models for review-scoped evidence preparation and re-RAG retrieval."""

import hashlib
import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


PrepareMode = Literal["selected", "candidate_fast"]
JobStatus = Literal["queued", "running", "complete", "partial", "failed"]
AttemptStatus = Literal["success", "not_available", "blocked", "failed"]
SourceKind = Literal[
    "pubtator_full_bioc",
    "pmc_bioc",
    "europe_pmc_jats",
    "curated_pdf",
    "curated_html",
    "docling_pdf",
    "pubtator_abstract",
]


class McpToolKind(StrEnum):
    """MCP-facing tool names for the POC."""

    index_review_evidence = "pubtator.index_review_evidence"
    retrieve_review_context = "pubtator.retrieve_review_context"


class PreparationStatus(BaseModel):
    """Aggregated preparation status counts for one review."""

    queued: int = Field(default=0, ge=0)
    running: int = Field(default=0, ge=0)
    complete: int = Field(default=0, ge=0)
    partial: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class IndexReviewEvidenceRequest(BaseModel):
    """Request to enqueue review-scoped evidence preparation."""

    pmids: list[str] = Field(default_factory=list)
    curated_urls: list[str] = Field(default_factory=list)
    prepare_mode: PrepareMode = "selected"


class IndexReviewEvidenceResponse(BaseModel):
    """Response after queueing or deduplicating preparation jobs."""

    success: bool = True
    review_id: str
    queued: int
    already_prepared: int
    preparation_status: PreparationStatus


class RetrieveReviewContextRequest(BaseModel):
    """Request for a fresh review-scoped context pack."""

    question: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages: int = Field(default=8, ge=1, le=30)
    max_chars: int = Field(default=6000, ge=500, le=30000)
    max_passages_per_pmid: int = Field(default=2, ge=1, le=10)


class ContextPassage(BaseModel):
    """One citable passage returned in a context pack."""

    citation_key: str
    passage_id: str
    pmid: str | None = None
    pmcid: str | None = None
    section: str
    text: str
    source_kind: str | None = None


class ContextPack(BaseModel):
    """Fresh per-request retrieval result."""

    question: str
    passages: list[ContextPassage]
    citation_map: dict[str, str]


class RetrieveReviewContextResponse(BaseModel):
    """Response for context retrieval."""

    success: bool = True
    review_id: str
    context_pack: ContextPack
    preparation_status: PreparationStatus


class ReviewPassageRow(BaseModel):
    """Repository row for a review passage candidate."""

    passage_id: str
    review_id: str
    source_id: str
    source_kind: str
    section: str
    text: str
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    url: str | None = None
    heading_path: str | None = None
    page: int | None = None
    entity_ids: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    screening_status: str = "candidate"
    source_metadata: dict[str, object] = Field(default_factory=dict)
    lexical_rank: float = 0.0


def normalize_section(section: str) -> str:
    """Normalize a section name for stable passage IDs."""
    lowered = section.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", lowered)
    return normalized.strip("_") or "body"


def passage_id_for_pmid(pmid: str, section: str, index: int) -> str:
    """Build deterministic PMID passage ID."""
    return f"PMID:{pmid}:{normalize_section(section)}:{index}"


def passage_id_for_pmcid(pmcid: str, section: str, index: int) -> str:
    """Build deterministic PMCID passage ID."""
    return f"PMCID:{pmcid}:{normalize_section(section)}:{index}"


def source_hash_for_url(url: str) -> str:
    """Build stable short URL source hash."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def passage_id_for_url(url: str, section_or_page: str, index: int) -> str:
    """Build deterministic URL passage ID."""
    return f"URL:{source_hash_for_url(url)}:{normalize_section(section_or_page)}:{index}"
```

- [ ] **Step 5: Implement schema**

Create `pubtator_link/db/review_schema.sql`:

```sql
create table if not exists reviews (
    review_id text primary key,
    created_at timestamptz not null default now()
);

create table if not exists review_preparation_jobs (
    job_id uuid primary key,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    status text not null,
    queued_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    error text,
    unique(review_id, source_id)
);

create index if not exists review_preparation_jobs_status_idx
    on review_preparation_jobs(status);

create table if not exists full_text_retrieval_attempts (
    attempt_id uuid primary key,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    status text not null,
    url text,
    reason text,
    content_type text,
    content_length bigint,
    created_at timestamptz not null default now()
);

create index if not exists review_attempts_audit_idx
    on full_text_retrieval_attempts(review_id, source_id, source_kind, created_at);

create table if not exists review_passages (
    passage_id text not null,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    pmid text,
    pmcid text,
    doi text,
    url text,
    section text not null,
    heading_path text,
    page integer,
    text text not null,
    entity_ids text[] not null default '{}',
    relation_types text[] not null default '{}',
    screening_status text not null default 'candidate',
    source_metadata jsonb not null default '{}',
    search_vector tsvector generated always as (
        to_tsvector('english', coalesce(heading_path, '') || ' ' || section || ' ' || text)
    ) stored,
    created_at timestamptz not null default now(),
    primary key(review_id, passage_id)
);

create index if not exists review_passages_search_vector_idx
    on review_passages using gin(search_vector);

create index if not exists review_passages_entity_ids_idx
    on review_passages using gin(entity_ids);

create index if not exists review_passages_review_id_idx
    on review_passages(review_id);

create index if not exists review_passages_review_id_pmid_idx
    on review_passages(review_id, pmid);

create index if not exists review_passages_review_id_source_id_idx
    on review_passages(review_id, source_id);

create index if not exists review_passages_review_id_section_idx
    on review_passages(review_id, section);
```

- [ ] **Step 6: Add db-init target**

Modify `Makefile` `.PHONY` line to include `db-init`, then add:

```make
db-init: ## Apply review re-RAG PostgreSQL schema using PUBTATOR_LINK_DATABASE_URL
	test -n "$$PUBTATOR_LINK_DATABASE_URL"
	psql "$$PUBTATOR_LINK_DATABASE_URL" -f pubtator_link/db/review_schema.sql
```

- [ ] **Step 7: Run tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/db/review_schema.sql Makefile tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py
git commit -m "feat: add review rerag models and schema"
```

## Task 3: Add SSRF-Safe URL Fetching

**Files:**
- Create: `pubtator_link/services/url_safety.py`
- Test: `tests/unit/test_url_safety.py`

- [ ] **Step 1: Write failing URL safety tests**

Create `tests/unit/test_url_safety.py`:

```python
import socket
from unittest.mock import Mock

import httpx
import pytest

from pubtator_link.config import ReviewReragConfig
from pubtator_link.services.url_safety import SafeUrlFetcher, UrlSafetyError


def config(*, allow_http_urls: bool = False) -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=60,
        source_timeout_seconds=20,
        pdf_max_bytes=1024,
        text_max_bytes=512,
        allow_http_urls=allow_http_urls,
        enable_docling=False,
    )


def test_rejects_unsupported_scheme() -> None:
    fetcher = SafeUrlFetcher(config())

    with pytest.raises(UrlSafetyError, match="Unsupported URL scheme"):
        fetcher.validate_url("file:///etc/passwd")


def test_rejects_http_unless_enabled() -> None:
    fetcher = SafeUrlFetcher(config())

    with pytest.raises(UrlSafetyError, match="HTTP URLs are disabled"):
        fetcher.validate_url("http://example.org/article.pdf")


def test_rejects_private_and_metadata_ips(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443))]),
    )
    fetcher = SafeUrlFetcher(config())

    with pytest.raises(UrlSafetyError, match="Unsafe resolved IP"):
        fetcher.validate_url("https://metadata.google.internal/latest")


@pytest.mark.asyncio
async def test_streaming_cap_rejects_oversized_response(respx_mock) -> None:
    route = respx_mock.get("https://example.org/large.pdf").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "2048"},
            content=b"%PDF" + b"x" * 2048,
        )
    )
    fetcher = SafeUrlFetcher(config())

    with pytest.raises(UrlSafetyError, match="Content-Length exceeds"):
        await fetcher.fetch_bytes("https://example.org/large.pdf", max_bytes=1024)

    assert route.called


@pytest.mark.asyncio
async def test_fetch_bytes_accepts_small_pdf(respx_mock, monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        Mock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]),
    )
    respx_mock.get("https://example.org/small.pdf").mock(
        return_value=httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7")
    )
    fetcher = SafeUrlFetcher(config())

    body, content_type = await fetcher.fetch_bytes("https://example.org/small.pdf", max_bytes=1024)

    assert body == b"%PDF-1.7"
    assert content_type == "application/pdf"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_url_safety.py -q
```

Expected: FAIL because `pubtator_link.services.url_safety` does not exist.

- [ ] **Step 3: Implement URL safety service**

Create `pubtator_link/services/url_safety.py`:

```python
"""SSRF-safe URL validation and bounded fetching."""

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from ..config import ReviewReragConfig


class UrlSafetyError(ValueError):
    """Raised when a URL cannot be fetched safely."""


class SafeUrlFetcher:
    """Validate URLs and fetch bounded response bodies."""

    def __init__(self, config: ReviewReragConfig):
        self.config = config

    def validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            raise UrlSafetyError(f"Unsupported URL scheme: {parsed.scheme}")
        if parsed.scheme == "http" and not self.config.allow_http_urls:
            raise UrlSafetyError("HTTP URLs are disabled")
        if not parsed.hostname:
            raise UrlSafetyError("URL must include a hostname")
        self._validate_hostname(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))

    async def fetch_bytes(self, url: str, *, max_bytes: int) -> tuple[bytes, str | None]:
        current_url = url
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.source_timeout_seconds),
            follow_redirects=False,
            headers={"User-Agent": "PubTator-Link review evidence preparer"},
        ) as client:
            for _ in range(4):
                self.validate_url(current_url)
                async with client.stream("GET", current_url) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise UrlSafetyError("Redirect response missing Location")
                        current_url = str(httpx.URL(current_url).join(location))
                        continue
                    if response.status_code != 200:
                        raise UrlSafetyError(f"HTTP {response.status_code}")
                    content_length = response.headers.get("content-length")
                    if content_length and int(content_length) > max_bytes:
                        raise UrlSafetyError("Content-Length exceeds configured maximum")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > max_bytes:
                            raise UrlSafetyError("Response body exceeds configured maximum")
                    return bytes(body), response.headers.get("content-type")
            raise UrlSafetyError("Too many redirects")

    def _validate_hostname(self, hostname: str, port: int) -> None:
        for family, kind, proto, _canonname, sockaddr in socket.getaddrinfo(hostname, port):
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
            ):
                raise UrlSafetyError(f"Unsafe resolved IP: {ip}")
```

- [ ] **Step 4: Run URL safety tests**

Run:

```bash
uv run pytest tests/unit/test_url_safety.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/url_safety.py tests/unit/test_url_safety.py
git commit -m "feat: add safe curated url fetching"
```

## Task 4: Add PostgreSQL Repository

**Files:**
- Create: `pubtator_link/repositories/__init__.py`
- Create: `pubtator_link/repositories/review_rerag.py`
- Test: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write repository tests against a fake connection**

Create `tests/unit/test_review_rerag_repository.py`:

```python
from unittest.mock import AsyncMock, Mock

import pytest

from pubtator_link.models.review_rerag import ReviewPassageRow
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository


@pytest.mark.asyncio
async def test_enqueue_preparation_job_creates_review_and_upserts_job() -> None:
    conn = AsyncMock()
    conn.fetchrow.return_value = {"job_id": "00000000-0000-0000-0000-000000000001", "status": "queued"}
    pool = Mock()
    pool.acquire.return_value.__aenter__.return_value = conn
    repo = PostgresReviewReragRepository(pool)

    result = await repo.enqueue_preparation_job(
        review_id="rev_123",
        source_id="PMID:40234174",
        source_kind="pubtator_full_bioc",
    )

    assert result["status"] == "queued"
    assert conn.execute.await_count == 1
    assert conn.fetchrow.await_count == 1


@pytest.mark.asyncio
async def test_upsert_passages_uses_executemany() -> None:
    conn = AsyncMock()
    pool = Mock()
    pool.acquire.return_value.__aenter__.return_value = conn
    repo = PostgresReviewReragRepository(pool)
    passage = ReviewPassageRow(
        passage_id="PMID:40234174:abstract:0",
        review_id="rev_123",
        source_id="PMID:40234174",
        source_kind="pubtator_abstract",
        section="abstract",
        text="Colchicine should start after diagnosis.",
        pmid="40234174",
    )

    await repo.upsert_passages([passage])

    conn.executemany.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_passages_maps_rows() -> None:
    conn = AsyncMock()
    conn.fetch.return_value = [
        {
            "passage_id": "PMID:40234174:abstract:0",
            "review_id": "rev_123",
            "source_id": "PMID:40234174",
            "source_kind": "pubtator_abstract",
            "section": "abstract",
            "text": "Colchicine should start after diagnosis.",
            "pmid": "40234174",
            "pmcid": None,
            "doi": None,
            "url": None,
            "heading_path": None,
            "page": None,
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0.8,
        }
    ]
    pool = Mock()
    pool.acquire.return_value.__aenter__.return_value = conn
    repo = PostgresReviewReragRepository(pool)

    rows = await repo.search_passages(
        review_id="rev_123",
        question="colchicine diagnosis",
        entity_ids=[],
        pmids=[],
        sections=[],
        limit=80,
    )

    assert rows[0].passage_id == "PMID:40234174:abstract:0"
    assert rows[0].lexical_rank == 0.8
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_repository.py -q
```

Expected: FAIL because repository module does not exist.

- [ ] **Step 3: Implement repository**

Create `pubtator_link/repositories/__init__.py`:

```python
"""Repository implementations for PubTator-Link."""
```

Create `pubtator_link/repositories/review_rerag.py` with asyncpg SQL methods:

```python
"""PostgreSQL repository for review-scoped re-RAG."""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import uuid4

import asyncpg

from ..models.review_rerag import PreparationStatus, ReviewPassageRow


class ReviewReragRepository(Protocol):
    async def enqueue_preparation_job(
        self, *, review_id: str, source_id: str, source_kind: str
    ) -> dict[str, Any]: ...
    async def record_retrieval_attempt(
        self,
        *,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        url: str | None,
        reason: str | None,
        content_type: str | None,
        content_length: int | None,
    ) -> None: ...
    async def mark_running_jobs_failed_on_startup(self) -> int: ...
    async def preparation_status(self, review_id: str) -> PreparationStatus: ...
    async def upsert_passages(self, passages: list[ReviewPassageRow]) -> None: ...
    async def search_passages(
        self,
        *,
        review_id: str,
        question: str,
        entity_ids: list[str],
        pmids: list[str],
        sections: list[str],
        limit: int,
    ) -> list[ReviewPassageRow]: ...


class PostgresReviewReragRepository:
    """asyncpg implementation for review-scoped re-RAG storage."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def ensure_review(self, review_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "insert into reviews(review_id) values($1) on conflict do nothing",
                review_id,
            )

    async def enqueue_preparation_job(
        self, *, review_id: str, source_id: str, source_kind: str
    ) -> dict[str, Any]:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "insert into reviews(review_id) values($1) on conflict do nothing",
                review_id,
            )
            row = await conn.fetchrow(
                """
                insert into review_preparation_jobs(job_id, review_id, source_id, source_kind, status)
                values($1, $2, $3, $4, 'queued')
                on conflict(review_id, source_id) do update
                set source_kind = excluded.source_kind
                returning job_id::text as job_id, status
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
            )
            return dict(row)

    async def record_retrieval_attempt(
        self,
        *,
        review_id: str,
        source_id: str,
        source_kind: str,
        status: str,
        url: str | None,
        reason: str | None,
        content_type: str | None,
        content_length: int | None,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                insert into full_text_retrieval_attempts(
                    attempt_id, review_id, source_id, source_kind, status,
                    url, reason, content_type, content_length
                )
                values($1,$2,$3,$4,$5,$6,$7,$8,$9)
                """,
                uuid4(),
                review_id,
                source_id,
                source_kind,
                status,
                url,
                reason,
                content_type,
                content_length,
            )

    async def mark_running_jobs_failed_on_startup(self) -> int:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                update review_preparation_jobs
                set status = 'failed', finished_at = now(), error = 'process_restarted'
                where status = 'running'
                """
            )
        return int(result.split()[-1])

    async def preparation_status(self, review_id: str) -> PreparationStatus:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select status, count(*)::int as count
                from review_preparation_jobs
                where review_id = $1
                group by status
                """,
                review_id,
            )
        counts = {row["status"]: row["count"] for row in rows}
        return PreparationStatus(**counts)

    async def upsert_passages(self, passages: list[ReviewPassageRow]) -> None:
        if not passages:
            return
        values = [
            (
                p.passage_id,
                p.review_id,
                p.source_id,
                p.source_kind,
                p.pmid,
                p.pmcid,
                p.doi,
                p.url,
                p.section,
                p.heading_path,
                p.page,
                p.text,
                p.entity_ids,
                p.relation_types,
                p.screening_status,
                p.source_metadata,
            )
            for p in passages
        ]
        async with self.pool.acquire() as conn:
            await conn.executemany(
                """
                insert into review_passages(
                    passage_id, review_id, source_id, source_kind, pmid, pmcid, doi, url,
                    section, heading_path, page, text, entity_ids, relation_types,
                    screening_status, source_metadata
                )
                values($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                on conflict(review_id, passage_id) do update
                set text = excluded.text,
                    section = excluded.section,
                    heading_path = excluded.heading_path,
                    entity_ids = excluded.entity_ids,
                    relation_types = excluded.relation_types,
                    source_metadata = excluded.source_metadata
                """,
                values,
            )

    async def search_passages(
        self,
        *,
        review_id: str,
        question: str,
        entity_ids: list[str],
        pmids: list[str],
        sections: list[str],
        limit: int,
    ) -> list[ReviewPassageRow]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select passage_id, review_id, source_id, source_kind, pmid, pmcid, doi, url,
                       section, heading_path, page, text, entity_ids, relation_types,
                       screening_status, source_metadata,
                       ts_rank_cd(search_vector, websearch_to_tsquery('english', $2))::float8
                           as lexical_rank
                from review_passages
                where review_id = $1
                  and search_vector @@ websearch_to_tsquery('english', $2)
                  and ($3::text[] is null or entity_ids && $3::text[])
                  and ($4::text[] is null or pmid = any($4::text[]))
                  and ($5::text[] is null or section = any($5::text[]))
                order by lexical_rank desc, passage_id asc
                limit $6
                """,
                review_id,
                question,
                entity_ids or None,
                pmids or None,
                sections or None,
                limit,
            )
        return [ReviewPassageRow(**dict(row)) for row in rows]
```

- [ ] **Step 4: Run repository tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_repository.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/repositories tests/unit/test_review_rerag_repository.py
git commit -m "feat: add review rerag repository"
```

## Task 5: Add Full-Text Preparation Service

**Files:**
- Create: `pubtator_link/services/full_text_preparation.py`
- Test: `tests/unit/test_full_text_preparation.py`

- [ ] **Step 1: Write failing preparation tests**

Create `tests/unit/test_full_text_preparation.py`:

```python
from unittest.mock import AsyncMock

import pytest

from pubtator_link.config import ReviewReragConfig
from pubtator_link.services.full_text_preparation import FullTextPreparationService


def config() -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=60,
        source_timeout_seconds=20,
        pdf_max_bytes=1024,
        text_max_bytes=1024,
        allow_http_urls=False,
        enable_docling=False,
    )


def test_looks_like_pdf_accepts_only_pdf_bytes() -> None:
    service = FullTextPreparationService(config=config(), repository=AsyncMock(), pubtator_client=AsyncMock())

    assert service.looks_like_pdf(b"%PDF-1.7\n") is True
    assert service.looks_like_pdf(b"<!doctype html>") is False


def test_normalize_bioc_document_builds_review_passages() -> None:
    service = FullTextPreparationService(config=config(), repository=AsyncMock(), pubtator_client=AsyncMock())
    document = {
        "id": "40234174",
        "passages": [
            {"infons": {"type": "title"}, "text": "FMF treatment", "offset": 0},
            {"infons": {"type": "abstract"}, "text": "Colchicine should start after diagnosis.", "offset": 15},
        ],
    }

    passages = service.passages_from_bioc_document(
        review_id="rev_123",
        source_id="PMID:40234174",
        source_kind="pubtator_full_bioc",
        document=document,
    )

    assert passages[0].passage_id == "PMID:40234174:title:0"
    assert passages[1].passage_id == "PMID:40234174:abstract:1"
    assert passages[1].pmid == "40234174"


@pytest.mark.asyncio
async def test_prepare_pmid_uses_abstract_fallback_when_no_full_text() -> None:
    repository = AsyncMock()
    pubtator_client = AsyncMock()
    pubtator_client.export_publications.return_value = {
        "PubTator3": [
            {
                "id": "40234174",
                "passages": [
                    {"infons": {"type": "abstract"}, "text": "Abstract fallback text.", "offset": 0}
                ],
            }
        ]
    }
    service = FullTextPreparationService(
        config=config(),
        repository=repository,
        pubtator_client=pubtator_client,
    )

    result = await service.prepare_pmid(review_id="rev_123", pmid="40234174")

    assert result in {"complete", "partial"}
    repository.upsert_passages.assert_awaited_once()
    repository.record_retrieval_attempt.assert_awaited()


@pytest.mark.asyncio
async def test_prepare_curated_url_records_blocked_html() -> None:
    repository = AsyncMock()
    fetcher = AsyncMock()
    fetcher.fetch_bytes.return_value = (b"<!doctype html>", "text/html")
    service = FullTextPreparationService(
        config=config(),
        repository=repository,
        pubtator_client=AsyncMock(),
        url_fetcher=fetcher,
    )

    result = await service.prepare_curated_url(review_id="rev_123", url="https://example.org/paper.pdf")

    assert result == "failed"
    repository.record_retrieval_attempt.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_full_text_preparation.py -q
```

Expected: FAIL because service module does not exist.

- [ ] **Step 3: Implement full-text preparation service**

Create `pubtator_link/services/full_text_preparation.py`:

```python
"""Full-text source cascade and passage normalization for review re-RAG."""

from typing import Any

from structlog.typing import FilteringBoundLogger

from ..api.client import PubTator3Client
from ..config import ReviewReragConfig
from ..models.review_rerag import ReviewPassageRow, passage_id_for_pmid
from ..repositories.review_rerag import ReviewReragRepository
from .url_safety import SafeUrlFetcher, UrlSafetyError


class FullTextPreparationService:
    """Prepare review-scoped passages from PubTator, PMC, curated URLs, and PDF fallbacks."""

    def __init__(
        self,
        *,
        config: ReviewReragConfig,
        repository: ReviewReragRepository,
        pubtator_client: PubTator3Client,
        logger: FilteringBoundLogger | None = None,
        url_fetcher: SafeUrlFetcher | None = None,
    ):
        self.config = config
        self.repository = repository
        self.pubtator_client = pubtator_client
        self.logger = logger
        self.url_fetcher = url_fetcher or SafeUrlFetcher(config)

    async def prepare_pmid(self, *, review_id: str, pmid: str) -> str:
        source_id = f"PMID:{pmid}"
        raw = await self.pubtator_client.export_publications([pmid], format="biocjson", full=True)
        documents = self._extract_documents(raw)
        passages: list[ReviewPassageRow] = []
        for document in documents:
            passages.extend(
                self.passages_from_bioc_document(
                    review_id=review_id,
                    source_id=source_id,
                    source_kind="pubtator_full_bioc",
                    document=document,
                )
            )
        if not passages:
            fallback_raw = await self.pubtator_client.export_publications(
                [pmid], format="biocjson", full=False
            )
            for document in self._extract_documents(fallback_raw):
                passages.extend(
                    self.passages_from_bioc_document(
                        review_id=review_id,
                        source_id=source_id,
                        source_kind="pubtator_abstract",
                        document=document,
                    )
                )
        await self.repository.upsert_passages(passages)
        await self.repository.record_retrieval_attempt(
            review_id=review_id,
            source_id=source_id,
            source_kind="pubtator_full_bioc" if passages else "pubtator_abstract",
            status="success" if passages else "failed",
            url=None,
            reason=None if passages else "No PubTator passages returned",
            content_type="application/json",
            content_length=None,
        )
        return "complete" if passages else "failed"

    async def prepare_curated_url(self, *, review_id: str, url: str) -> str:
        source_id = f"URL:{url}"
        try:
            body, content_type = await self.url_fetcher.fetch_bytes(
                url, max_bytes=self.config.pdf_max_bytes
            )
        except UrlSafetyError as exc:
            await self.repository.record_retrieval_attempt(
                review_id=review_id,
                source_id=source_id,
                source_kind="curated_pdf",
                status="blocked",
                url=url,
                reason=str(exc),
                content_type=None,
                content_length=None,
            )
            return "failed"
        if not self.looks_like_pdf(body):
            await self.repository.record_retrieval_attempt(
                review_id=review_id,
                source_id=source_id,
                source_kind="curated_pdf",
                status="blocked",
                url=url,
                reason="Non-PDF response",
                content_type=content_type,
                content_length=len(body),
            )
            return "failed"
        if not self.config.enable_docling:
            await self.repository.record_retrieval_attempt(
                review_id=review_id,
                source_id=source_id,
                source_kind="curated_pdf",
                status="not_available",
                url=url,
                reason="Docling disabled",
                content_type=content_type,
                content_length=len(body),
            )
            return "failed"
        return "failed"

    def passages_from_bioc_document(
        self,
        *,
        review_id: str,
        source_id: str,
        source_kind: str,
        document: dict[str, Any],
    ) -> list[ReviewPassageRow]:
        pmid = str(document.get("id") or "").strip() or None
        passages: list[ReviewPassageRow] = []
        for index, passage in enumerate(document.get("passages", []) or []):
            text = str(passage.get("text", "")).strip()
            if not text:
                continue
            infons = passage.get("infons", {}) or {}
            section = str(infons.get("section_type") or infons.get("type") or "body")
            passage_id = passage_id_for_pmid(pmid or "unknown", section, index)
            passages.append(
                ReviewPassageRow(
                    passage_id=passage_id,
                    review_id=review_id,
                    source_id=source_id,
                    source_kind=source_kind,
                    section=section,
                    text=text,
                    pmid=pmid,
                    source_metadata={"offset": passage.get("offset", 0)},
                )
            )
        return passages

    def looks_like_pdf(self, content: bytes) -> bool:
        return content.startswith(b"%PDF")

    def _extract_documents(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        if "PubTator3" in raw and isinstance(raw["PubTator3"], list):
            return raw["PubTator3"]
        if "documents" in raw and isinstance(raw["documents"], list):
            return raw["documents"]
        return []
```

This first implementation proves the internal normalization path. Add PMC/JATS/Europe PMC source adapters in later implementation steps only after the POC route is passing end-to-end.

- [ ] **Step 4: Run preparation tests**

Run:

```bash
uv run pytest tests/unit/test_full_text_preparation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/full_text_preparation.py tests/unit/test_full_text_preparation.py
git commit -m "feat: add review evidence preparation service"
```

## Task 6: Add Background Preparation Queue

**Files:**
- Create: `pubtator_link/services/review_preparation_queue.py`
- Test: `tests/unit/test_review_preparation_queue.py`

- [ ] **Step 1: Write failing queue tests**

Create `tests/unit/test_review_preparation_queue.py`:

```python
from unittest.mock import AsyncMock

import pytest

from pubtator_link.config import ReviewReragConfig
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue


def config() -> ReviewReragConfig:
    return ReviewReragConfig(
        database_url=None,
        prep_concurrency=2,
        document_timeout_seconds=1,
        source_timeout_seconds=1,
        pdf_max_bytes=1024,
        text_max_bytes=1024,
        allow_http_urls=False,
        enable_docling=False,
    )


@pytest.mark.asyncio
async def test_enqueue_deduplicates_same_source() -> None:
    repository = AsyncMock()
    repository.enqueue_preparation_job.return_value = {"job_id": "job-1", "status": "queued"}
    preparation = AsyncMock()
    queue = ReviewPreparationQueue(config=config(), repository=repository, preparation=preparation)

    first = await queue.enqueue_pmid("rev_123", "40234174")
    second = await queue.enqueue_pmid("rev_123", "40234174")

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_enqueue_curated_url_uses_url_source_id() -> None:
    repository = AsyncMock()
    repository.enqueue_preparation_job.return_value = {"job_id": "job-1", "status": "queued"}
    preparation = AsyncMock()
    queue = ReviewPreparationQueue(config=config(), repository=repository, preparation=preparation)

    queued = await queue.enqueue_curated_url("rev_123", "https://example.org/paper.pdf")

    assert queued is True
    repository.enqueue_preparation_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_startup_marks_running_failed() -> None:
    repository = AsyncMock()
    repository.mark_running_jobs_failed_on_startup.return_value = 2
    queue = ReviewPreparationQueue(config=config(), repository=repository, preparation=AsyncMock())

    reaped = await queue.repair_startup_jobs()

    assert reaped == 2
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_preparation_queue.py -q
```

Expected: FAIL because queue module does not exist.

- [ ] **Step 3: Implement queue**

Create `pubtator_link/services/review_preparation_queue.py`:

```python
"""In-process background queue for review evidence preparation."""

import asyncio

from structlog.typing import FilteringBoundLogger

from ..config import ReviewReragConfig
from ..repositories.review_rerag import ReviewReragRepository
from .full_text_preparation import FullTextPreparationService


class ReviewPreparationQueue:
    """Bounded in-process preparation queue for the POC."""

    def __init__(
        self,
        *,
        config: ReviewReragConfig,
        repository: ReviewReragRepository,
        preparation: FullTextPreparationService,
        logger: FilteringBoundLogger | None = None,
    ):
        self.config = config
        self.repository = repository
        self.preparation = preparation
        self.logger = logger
        self._queue: asyncio.Queue[tuple[str, str, str, str]] = asyncio.Queue()
        self._queued: set[tuple[str, str]] = set()
        self._workers: list[asyncio.Task[None]] = []

    async def repair_startup_jobs(self) -> int:
        return await self.repository.mark_running_jobs_failed_on_startup()

    async def start(self) -> None:
        await self.repair_startup_jobs()
        for _ in range(self.config.prep_concurrency):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue_pmid(self, review_id: str, pmid: str) -> bool:
        source_id = f"PMID:{pmid}"
        source_key = (review_id, source_id)
        if source_key in self._queued:
            return False
        await self.repository.enqueue_preparation_job(
            review_id=review_id,
            source_id=source_id,
            source_kind="pubtator_full_bioc",
        )
        self._queued.add(source_key)
        await self._queue.put((review_id, source_id, "pmid", pmid))
        return True

    async def enqueue_curated_url(self, review_id: str, url: str) -> bool:
        source_id = f"URL:{url}"
        source_key = (review_id, source_id)
        if source_key in self._queued:
            return False
        await self.repository.enqueue_preparation_job(
            review_id=review_id,
            source_id=source_id,
            source_kind="curated_pdf",
        )
        self._queued.add(source_key)
        await self._queue.put((review_id, source_id, "url", url))
        return True

    async def _worker(self) -> None:
        while True:
            review_id, source_id, item_kind, value = await self._queue.get()
            try:
                if item_kind == "pmid":
                    await asyncio.wait_for(
                        self.preparation.prepare_pmid(review_id=review_id, pmid=value),
                        timeout=self.config.document_timeout_seconds,
                    )
                else:
                    await asyncio.wait_for(
                        self.preparation.prepare_curated_url(review_id=review_id, url=value),
                        timeout=self.config.document_timeout_seconds,
                    )
            finally:
                self._queued.discard((review_id, source_id))
                self._queue.task_done()
```

The repository advisory lock execution and job status transitions are added in Task 10 after route-level behavior is passing. This keeps the first queue slice small and testable.

- [ ] **Step 4: Run queue tests**

Run:

```bash
uv run pytest tests/unit/test_review_preparation_queue.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/review_preparation_queue.py tests/unit/test_review_preparation_queue.py
git commit -m "feat: add review preparation queue"
```

## Task 7: Add Context Retrieval and Reranking

**Files:**
- Create: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing context service tests**

Create `tests/unit/test_review_context_service.py`:

```python
from unittest.mock import AsyncMock

import pytest

from pubtator_link.models.review_rerag import RetrieveReviewContextRequest, ReviewPassageRow
from pubtator_link.services.review_context_service import ReviewContextService


def row(passage_id: str, pmid: str, section: str, text: str, rank: float) -> ReviewPassageRow:
    return ReviewPassageRow(
        passage_id=passage_id,
        review_id="rev_123",
        source_id=f"PMID:{pmid}",
        source_kind="pubtator_full_bioc",
        pmid=pmid,
        section=section,
        text=text,
        lexical_rank=rank,
    )


@pytest.mark.asyncio
async def test_context_pack_is_deterministic_and_diverse() -> None:
    repository = AsyncMock()
    repository.search_passages.return_value = [
        row("PMID:1:abstract:0", "1", "abstract", "Colchicine diagnosis one.", 1.0),
        row("PMID:1:results:1", "1", "results", "Colchicine diagnosis two.", 0.9),
        row("PMID:1:body:2", "1", "body", "Colchicine diagnosis three.", 0.8),
        row("PMID:2:abstract:0", "2", "abstract", "FMF diagnosis.", 0.7),
    ]
    repository.preparation_status.return_value = {"complete": 2}
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context(
        review_id="rev_123",
        request=RetrieveReviewContextRequest(question="colchicine diagnosis", max_passages=3),
    )

    assert [p.passage_id for p in response.context_pack.passages] == [
        "PMID:1:abstract:0",
        "PMID:1:results:1",
        "PMID:2:abstract:0",
    ]
    assert response.context_pack.citation_map["S1"] == "PMID:1:abstract:0"


@pytest.mark.asyncio
async def test_max_chars_drops_passage_instead_of_truncating() -> None:
    repository = AsyncMock()
    repository.search_passages.return_value = [
        row("PMID:1:abstract:0", "1", "abstract", "short text", 1.0),
        row("PMID:2:abstract:0", "2", "abstract", "x" * 1000, 0.9),
    ]
    service = ReviewContextService(repository=repository)

    response = await service.retrieve_context(
        review_id="rev_123",
        request=RetrieveReviewContextRequest(question="short", max_chars=500),
    )

    assert len(response.context_pack.passages) == 1
    assert response.context_pack.passages[0].text == "short text"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: FAIL because service module does not exist.

- [ ] **Step 3: Implement context service**

Create `pubtator_link/services/review_context_service.py`:

```python
"""Review-scoped PostgreSQL FTS retrieval and context packing."""

from collections import defaultdict

from ..models.review_rerag import (
    ContextPack,
    ContextPassage,
    PreparationStatus,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
    ReviewPassageRow,
)
from ..repositories.review_rerag import ReviewReragRepository


SECTION_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "results": 2,
    "recommendations": 3,
    "discussion": 4,
    "methods": 5,
    "body": 6,
}

SOURCE_PRIORITY = {
    "pubtator_full_bioc": 0,
    "pmc_bioc": 0,
    "europe_pmc_jats": 1,
    "docling_pdf": 2,
    "pubtator_abstract": 3,
}


class ReviewContextService:
    """Build fresh context packs from review-scoped passages."""

    def __init__(self, repository: ReviewReragRepository):
        self.repository = repository

    async def retrieve_context(
        self, *, review_id: str, request: RetrieveReviewContextRequest
    ) -> RetrieveReviewContextResponse:
        candidates = await self.repository.search_passages(
            review_id=review_id,
            question=request.question,
            entity_ids=request.entity_ids,
            pmids=request.pmids,
            sections=request.sections,
            limit=80,
        )
        ranked = self.rerank(candidates)
        selected = self.pack(
            ranked,
            max_passages=request.max_passages,
            max_chars=request.max_chars,
            max_passages_per_pmid=1000 if len(request.pmids) == 1 else request.max_passages_per_pmid,
        )
        passages = [
            ContextPassage(
                citation_key=f"S{index + 1}",
                passage_id=passage.passage_id,
                pmid=passage.pmid,
                pmcid=passage.pmcid,
                section=passage.section,
                text=passage.text,
                source_kind=passage.source_kind,
            )
            for index, passage in enumerate(selected)
        ]
        citation_map = {passage.citation_key: passage.passage_id for passage in passages}
        status = await self.repository.preparation_status(review_id)
        if isinstance(status, dict):
            status = PreparationStatus(**status)
        return RetrieveReviewContextResponse(
            review_id=review_id,
            context_pack=ContextPack(
                question=request.question,
                passages=passages,
                citation_map=citation_map,
            ),
            preparation_status=status,
        )

    def rerank(self, candidates: list[ReviewPassageRow]) -> list[ReviewPassageRow]:
        return sorted(
            candidates,
            key=lambda row: (
                -row.lexical_rank,
                SECTION_PRIORITY.get(row.section, 99),
                SOURCE_PRIORITY.get(row.source_kind, 99),
                row.pmid or "",
                row.passage_id,
            ),
        )

    def pack(
        self,
        candidates: list[ReviewPassageRow],
        *,
        max_passages: int,
        max_chars: int,
        max_passages_per_pmid: int,
    ) -> list[ReviewPassageRow]:
        selected: list[ReviewPassageRow] = []
        used_chars = 0
        per_pmid: defaultdict[str, int] = defaultdict(int)
        for passage in candidates:
            pmid_key = passage.pmid or passage.source_id
            if per_pmid[pmid_key] >= max_passages_per_pmid:
                continue
            if used_chars + len(passage.text) > max_chars:
                continue
            selected.append(passage)
            used_chars += len(passage.text)
            per_pmid[pmid_key] += 1
            if len(selected) >= max_passages:
                break
        return selected
```

- [ ] **Step 4: Run context service tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: add review context retrieval service"
```

## Task 8: Add FastAPI Routes and Dependencies

**Files:**
- Create: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/api/routes/__init__.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write failing route tests**

Create `tests/test_routes/test_reviews.py`:

```python
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_review_context_service, get_review_queue
from pubtator_link.models.review_rerag import (
    ContextPack,
    IndexReviewEvidenceResponse,
    PreparationStatus,
    RetrieveReviewContextResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


@pytest.mark.asyncio
async def test_index_review_evidence_returns_queue_status() -> None:
    app = UnifiedServerManager().create_app()
    queue = AsyncMock()
    queue.enqueue_pmid.return_value = True
    queue.repository.preparation_status.return_value = PreparationStatus(queued=1)
    app.dependency_overrides[get_review_queue] = lambda: queue

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/evidence/index",
            json={"pmids": ["40234174"], "prepare_mode": "selected"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["review_id"] == "rev_123"
    assert data["queued"] == 1


@pytest.mark.asyncio
async def test_retrieve_review_context_returns_pack() -> None:
    app = UnifiedServerManager().create_app()
    service = AsyncMock()
    service.retrieve_context.return_value = RetrieveReviewContextResponse(
        review_id="rev_123",
        context_pack=ContextPack(
            question="colchicine diagnosis",
            passages=[],
            citation_map={},
        ),
        preparation_status=PreparationStatus(complete=1),
    )
    app.dependency_overrides[get_review_context_service] = lambda: service

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/reviews/rev_123/context",
            json={"question": "colchicine diagnosis"},
        )

    assert response.status_code == 200
    assert response.json()["preparation_status"]["complete"] == 1
```

- [ ] **Step 2: Run route tests to verify failure**

Run:

```bash
uv run pytest tests/test_routes/test_reviews.py -q
```

Expected: FAIL because review route dependencies do not exist.

- [ ] **Step 3: Add review routes**

Create `pubtator_link/api/routes/reviews.py`:

```python
"""Review-scoped evidence preparation and context retrieval routes."""

from fastapi import APIRouter

from ...models.review_rerag import (
    IndexReviewEvidenceRequest,
    IndexReviewEvidenceResponse,
    RetrieveReviewContextRequest,
    RetrieveReviewContextResponse,
)
from .dependencies import ReviewContextServiceDep, ReviewQueueDep, handle_api_errors

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])


@router.post(
    "/{review_id}/evidence/index",
    response_model=IndexReviewEvidenceResponse,
    operation_id="index_review_evidence",
    summary="Queue review-scoped evidence preparation",
)
@handle_api_errors
async def index_review_evidence(
    review_id: str,
    request: IndexReviewEvidenceRequest,
    queue: ReviewQueueDep,
) -> IndexReviewEvidenceResponse:
    queued = 0
    already_prepared = 0
    for pmid in request.pmids:
        if await queue.enqueue_pmid(review_id, pmid):
            queued += 1
        else:
            already_prepared += 1
    for url in request.curated_urls:
        if await queue.enqueue_curated_url(review_id, url):
            queued += 1
        else:
            already_prepared += 1
    status = await queue.repository.preparation_status(review_id)
    return IndexReviewEvidenceResponse(
        review_id=review_id,
        queued=queued,
        already_prepared=already_prepared,
        preparation_status=status,
    )


@router.post(
    "/{review_id}/context",
    response_model=RetrieveReviewContextResponse,
    operation_id="retrieve_review_context",
    summary="Retrieve a compact review-scoped context pack",
)
@handle_api_errors
async def retrieve_review_context(
    review_id: str,
    request: RetrieveReviewContextRequest,
    service: ReviewContextServiceDep,
) -> RetrieveReviewContextResponse:
    return await service.retrieve_context(review_id=review_id, request=request)
```

- [ ] **Step 4: Register route module**

Modify `pubtator_link/api/routes/__init__.py`:

```python
from .reviews import router as reviews_router
```

Add `reviews_router` to `__all__` and `ROUTE_MODULES`.

Modify `pubtator_link/server_manager.py` imports to include `reviews_router`, then add:

```python
        app.include_router(reviews_router)
```

Also import `get_review_queue` from `pubtator_link.api.routes.dependencies`. In the lifespan startup block, after `PublicationService` is initialized, add:

```python
        if settings.database_url is not None:
            review_queue = await get_review_queue()
            await review_queue.start()
```

In the lifespan shutdown block, before `cleanup_dependencies()`, add:

```python
        if settings.database_url is not None:
            review_queue = await get_review_queue()
            await review_queue.stop()
```

- [ ] **Step 5: Add dependency providers**

Modify `pubtator_link/api/routes/dependencies.py` imports:

```python
import asyncpg

from ...config import review_rerag_config
from ...repositories.review_rerag import PostgresReviewReragRepository
from ...services.full_text_preparation import FullTextPreparationService
from ...services.review_context_service import ReviewContextService
from ...services.review_preparation_queue import ReviewPreparationQueue
```

Add globals:

```python
_review_pool: asyncpg.Pool | None = None
_review_repository: PostgresReviewReragRepository | None = None
_review_queue: ReviewPreparationQueue | None = None
_review_context_service: ReviewContextService | None = None
```

Add providers:

```python
async def get_review_pool() -> asyncpg.Pool:
    global _review_pool
    if review_rerag_config.database_url is None:
        raise RuntimeError("PUBTATOR_LINK_DATABASE_URL is required for review re-RAG")
    if _review_pool is None:
        _review_pool = await asyncpg.create_pool(review_rerag_config.database_url)
    return _review_pool


async def get_review_repository() -> PostgresReviewReragRepository:
    global _review_repository
    if _review_repository is None:
        _review_repository = PostgresReviewReragRepository(await get_review_pool())
    return _review_repository


async def get_review_queue() -> ReviewPreparationQueue:
    global _review_queue
    if _review_queue is None:
        repository = await get_review_repository()
        client = await get_api_client()
        logger_instance = await get_logger()
        preparation = FullTextPreparationService(
            config=review_rerag_config,
            repository=repository,
            pubtator_client=client,
            logger=logger_instance,
        )
        _review_queue = ReviewPreparationQueue(
            config=review_rerag_config,
            repository=repository,
            preparation=preparation,
            logger=logger_instance,
        )
    return _review_queue


async def get_review_context_service() -> ReviewContextService:
    global _review_context_service
    if _review_context_service is None:
        _review_context_service = ReviewContextService(repository=await get_review_repository())
    return _review_context_service
```

Add aliases:

```python
ReviewQueueDep = Annotated[ReviewPreparationQueue, Depends(get_review_queue)]
ReviewContextServiceDep = Annotated[ReviewContextService, Depends(get_review_context_service)]
```

Extend `cleanup_dependencies` to close `_review_pool` and reset review globals.

- [ ] **Step 6: Run route tests**

Run:

```bash
uv run pytest tests/test_routes/test_reviews.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/api/routes/reviews.py pubtator_link/api/routes/__init__.py pubtator_link/api/routes/dependencies.py pubtator_link/server_manager.py tests/test_routes/test_reviews.py
git commit -m "feat: expose review rerag routes"
```

## Task 9: Add MCP Tools

**Files:**
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/resources.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing MCP tests**

Create `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
from pubtator_link.mcp.facade import create_pubtator_mcp


def test_review_rerag_tools_are_exposed_with_expected_names() -> None:
    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools)

    assert "pubtator.index_review_evidence" in tool_names
    assert "pubtator.retrieve_review_context" in tool_names
```

- [ ] **Step 2: Run MCP test to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: FAIL because tools are not registered.

- [ ] **Step 3: Add MCP request models**

Modify `pubtator_link/mcp/tools.py`:

```python
class IndexReviewEvidenceMcpRequest(BaseModel):
    """Queue review-scoped evidence preparation. Research use only."""

    review_id: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    curated_urls: list[str] = Field(default_factory=list)
    prepare_mode: str = "selected"


class RetrieveReviewContextMcpRequest(BaseModel):
    """Retrieve a compact review-scoped context pack. Research use only."""

    review_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    pmids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    max_passages: int = 8
    max_chars: int = 6000
```

- [ ] **Step 4: Add MCP adapter functions**

Modify `pubtator_link/mcp/service_adapters.py`:

```python
from pubtator_link.models.review_rerag import (
    IndexReviewEvidenceRequest,
    RetrieveReviewContextRequest,
)
from pubtator_link.services.review_context_service import ReviewContextService
from pubtator_link.services.review_preparation_queue import ReviewPreparationQueue
```

Add:

```python
async def index_review_evidence_impl(
    request: IndexReviewEvidenceMcpRequest,
    *,
    queue: ReviewPreparationQueue,
) -> dict[str, Any]:
    queued = 0
    already_prepared = 0
    api_request = IndexReviewEvidenceRequest(
        pmids=request.pmids,
        curated_urls=request.curated_urls,
        prepare_mode=request.prepare_mode,  # type: ignore[arg-type]
    )
    for pmid in api_request.pmids:
        if await queue.enqueue_pmid(request.review_id, pmid):
            queued += 1
        else:
            already_prepared += 1
    for url in api_request.curated_urls:
        if await queue.enqueue_curated_url(request.review_id, url):
            queued += 1
        else:
            already_prepared += 1
    status = await queue.repository.preparation_status(request.review_id)
    return {
        "success": True,
        "review_id": request.review_id,
        "queued": queued,
        "already_prepared": already_prepared,
        "preparation_status": status.model_dump(),
    }


async def retrieve_review_context_impl(
    request: RetrieveReviewContextMcpRequest,
    *,
    service: ReviewContextService,
) -> dict[str, Any]:
    response = await service.retrieve_context(
        review_id=request.review_id,
        request=RetrieveReviewContextRequest(
            question=request.question,
            pmids=request.pmids,
            entity_ids=request.entity_ids,
            sections=request.sections,
            max_passages=request.max_passages,
            max_chars=request.max_chars,
        ),
    )
    return response.model_dump()
```

- [ ] **Step 5: Register MCP tools**

Modify `pubtator_link/mcp/facade.py` imports for new request models and adapters. Add tool annotations:

```python
REVIEW_WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
```

Add tools inside `create_pubtator_mcp`:

```python
    @mcp.tool(
        name="pubtator.index_review_evidence",
        title="Index Review Evidence",
        annotations=REVIEW_WRITE_ANNOTATIONS,
    )
    async def index_review_evidence(request: IndexReviewEvidenceMcpRequest) -> dict[str, Any]:
        """Queue review-scoped evidence preparation. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        queue = await get_review_queue()
        return await index_review_evidence_impl(request, queue=queue)

    @mcp.tool(
        name="pubtator.retrieve_review_context",
        title="Retrieve Review Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def retrieve_review_context(request: RetrieveReviewContextMcpRequest) -> dict[str, Any]:
        """Retrieve a compact context pack from prepared review passages. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        service = await get_review_context_service()
        return await retrieve_review_context_impl(request, service=service)
```

Import dependency providers:

```python
from pubtator_link.api.routes.dependencies import get_review_context_service, get_review_queue
```

- [ ] **Step 6: Update capabilities resource**

Modify `pubtator_link/mcp/resources.py` to include:

```python
"review_rerag": {
    "tools": ["pubtator.index_review_evidence", "pubtator.retrieve_review_context"],
    "scope": "research-use review-scoped evidence preparation and retrieval",
    "limitations": ["single-tenant trusted POC", "no backend LLM", "no clinical decision support"],
}
```

- [ ] **Step 7: Run MCP tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/mcp/tools.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/facade.py pubtator_link/mcp/resources.py tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: expose review rerag mcp tools"
```

## Task 10: Integration Hardening and Verification

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/services/review_preparation_queue.py`
- Create: `tests/integration/test_review_schema_postgres.py`
- Test: existing touched tests

- [ ] **Step 1: Add repository job transition methods**

Add tests to `tests/unit/test_review_rerag_repository.py`:

```python
@pytest.mark.asyncio
async def test_job_status_methods_execute_expected_sql() -> None:
    conn = AsyncMock()
    pool = Mock()
    pool.acquire.return_value.__aenter__.return_value = conn
    repo = PostgresReviewReragRepository(pool)

    await repo.mark_job_running(review_id="rev_123", source_id="PMID:40234174")
    await repo.mark_job_finished(
        review_id="rev_123",
        source_id="PMID:40234174",
        status="complete",
        error=None,
    )

    assert conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_advisory_lock_wraps_preparation_callback() -> None:
    conn = AsyncMock()
    pool = Mock()
    pool.acquire.return_value.__aenter__.return_value = conn
    repo = PostgresReviewReragRepository(pool)
    callback = AsyncMock(return_value="complete")

    result = await repo.with_preparation_lock(
        review_id="rev_123",
        source_id="PMID:40234174",
        callback=callback,
    )

    assert result == "complete"
    assert conn.execute.await_count == 2
    callback.assert_awaited_once()
```

Implement in `PostgresReviewReragRepository`:

```python
    async def mark_job_running(self, *, review_id: str, source_id: str) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                update review_preparation_jobs
                set status = 'running', started_at = now(), error = null
                where review_id = $1 and source_id = $2
                """,
                review_id,
                source_id,
            )

    async def mark_job_finished(
        self, *, review_id: str, source_id: str, status: str, error: str | None
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                update review_preparation_jobs
                set status = $3, finished_at = now(), error = $4
                where review_id = $1 and source_id = $2
                """,
                review_id,
                source_id,
                status,
                error,
            )

    async def with_preparation_lock(
        self,
        *,
        review_id: str,
        source_id: str,
        callback: Callable[[], Awaitable[str]],
    ) -> str:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "select pg_advisory_xact_lock(hashtextextended($1, 0))",
                    f"{review_id}:{source_id}",
                )
                return await callback()
```

- [ ] **Step 2: Add queue status transitions**

Modify `_worker` in `pubtator_link/services/review_preparation_queue.py`:

```python
            try:
                await self.repository.mark_job_running(review_id=review_id, source_id=source_id)
                async def run_preparation() -> str:
                    if item_kind == "pmid":
                        return await asyncio.wait_for(
                            self.preparation.prepare_pmid(review_id=review_id, pmid=value),
                            timeout=self.config.document_timeout_seconds,
                        )
                    return await asyncio.wait_for(
                        self.preparation.prepare_curated_url(review_id=review_id, url=value),
                        timeout=self.config.document_timeout_seconds,
                    )

                result = await self.repository.with_preparation_lock(
                    review_id=review_id,
                    source_id=source_id,
                    callback=run_preparation,
                )
                await self.repository.mark_job_finished(
                    review_id=review_id,
                    source_id=source_id,
                    status=result,
                    error=None,
                )
            except Exception as exc:
                await self.repository.mark_job_finished(
                    review_id=review_id,
                    source_id=source_id,
                    status="failed",
                    error=str(exc)[:500],
                )
```

- [ ] **Step 3: Add real PostgreSQL integration schema test**

Create `tests/integration/test_review_schema_postgres.py`:

```python
import os
from pathlib import Path

import asyncpg
import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_review_schema_applies_to_postgres() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/review_schema.sql").read_text()
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(schema)
        rows = await conn.fetch(
            """
            select tablename
            from pg_tables
            where schemaname = 'public'
              and tablename in (
                'reviews',
                'review_preparation_jobs',
                'full_text_retrieval_attempts',
                'review_passages'
              )
            """
        )
    finally:
        await conn.close()

    assert {row["tablename"] for row in rows} == {
        "reviews",
        "review_preparation_jobs",
        "full_text_retrieval_attempts",
        "review_passages",
    }
```

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_repository.py tests/unit/test_review_preparation_queue.py tests/test_routes/test_reviews.py -q
```

Expected: PASS.

- [ ] **Step 5: Run all review POC tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_config.py tests/unit/test_review_rerag_models.py tests/unit/test_review_schema_sql.py tests/unit/test_url_safety.py tests/unit/test_review_rerag_repository.py tests/unit/test_full_text_preparation.py tests/unit/test_review_preparation_queue.py tests/unit/test_review_context_service.py tests/test_routes/test_reviews.py tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: PASS.

- [ ] **Step 6: Run required repository checks**

Run:

```bash
make ci-local
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/repositories/review_rerag.py pubtator_link/services/review_preparation_queue.py tests/integration/test_review_schema_postgres.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: harden review rerag preparation jobs"
```

## Task 11: Update POC Documentation and Backlog

**Files:**
- Modify: `docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md`
- Create: `docs/REVIEW_RERAG_POC.md`

- [ ] **Step 1: Add POC usage documentation**

Create `docs/REVIEW_RERAG_POC.md`:

```markdown
# Review Re-RAG POC

This POC prepares review-scoped evidence passages and retrieves compact context packs. It is research-use only and is not for diagnosis, treatment, triage, patient management, or clinical decision support.

## Setup

Set a PostgreSQL URL:

```bash
export PUBTATOR_LINK_DATABASE_URL=postgresql://user:pass@localhost:5432/pubtator_link
make db-init
```

Start the server with one worker for the POC:

```bash
make dev
```

## Queue Evidence Preparation

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/evidence/index \
  -H 'content-type: application/json' \
  -d '{"pmids":["40234174"],"prepare_mode":"selected"}'
```

The endpoint returns after queueing. Preparation continues in the background.

## Retrieve Context

```bash
curl -s http://127.0.0.1:8000/api/reviews/rev_123/context \
  -H 'content-type: application/json' \
  -d '{"question":"Should colchicine start after clinical diagnosis of FMF?","max_passages":8,"max_chars":6000}'
```

The context pack is generated fresh for each request. It can change as more passages are prepared.
```

- [ ] **Step 2: Add backlog note to parent plan**

Append a short note near the top of `docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md`:

```markdown
> **POC split:** The fast review-scoped re-RAG POC is specified in `docs/superpowers/specs/2026-04-30-review-scoped-rerag-poc-design.md` and implemented by `docs/superpowers/plans/2026-04-30-review-scoped-rerag-poc-implementation.md`. Keep deferred items from that POC backlog tracked before continuing the broader workflow plan.
```

- [ ] **Step 3: Run doc checks**

Run:

```bash
rg -n "Review Re-RAG POC|review-scoped re-RAG POC" docs/REVIEW_RERAG_POC.md docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md
```

Expected: finds both files.

- [ ] **Step 4: Commit**

```bash
git add docs/REVIEW_RERAG_POC.md docs/superpowers/plans/2026-04-30-pubtator-evidence-review-workflow.md
git commit -m "docs: document review rerag poc"
```

## Final Verification

After all tasks are complete, run:

```bash
make ci-local
git status --short
```

Expected:

- `make ci-local` passes.
- `git status --short` shows no uncommitted implementation changes.

If Docker or local PostgreSQL is available, also run:

```bash
PUBTATOR_LINK_TEST_DATABASE_URL="$PUBTATOR_LINK_DATABASE_URL" uv run pytest tests/integration/test_review_schema_postgres.py -q
```

Expected: PASS or SKIP only when `PUBTATOR_LINK_TEST_DATABASE_URL` is not set.

## Plan Self-Review Notes

- Spec coverage: URL safety, single-worker queue semantics, advisory-lock hardening, startup repair, schema constraints, generated FTS vector, entity filters, deterministic reranking, MCP exposure, trust boundary, config, observability, and testing are represented in tasks.
- Speed strategy: Tasks 3, 4, 5, and 7 can run in parallel after Task 2 because their write sets are disjoint.
- Known implementation caveat: Docling conversion is intentionally not implemented beyond a guarded disabled path in the POC. The backlog keeps richer Docling extraction and sandboxing as follow-up work.
