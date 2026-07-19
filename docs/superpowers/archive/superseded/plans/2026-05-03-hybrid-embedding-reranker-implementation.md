# Hybrid Embedding Reranker Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional local BGE-small embedding reranker over top-50 lexical review candidates, fused with lexical ranking by RRF and protected by evidence-section guardrails.

**Architecture:** Keep Postgres full-text search as the recall stage, store BGE-small `vector(384)` passage embeddings in a separate `review_passage_embeddings` table, and add a review-context reranking service between candidate search and passage packing. The feature is disabled by default, degrades to lexical ranking on any embedding/schema/provider problem, and reports diagnostics when dense reranking is requested or active.

**Tech Stack:** Python 3.12, FastAPI/FastMCP, Pydantic v2, asyncpg, pgvector, optional Sentence Transformers/Torch runtime, pytest, Ruff, mypy, existing Makefile targets.

---

## Working Rules

- Start from an isolated worktree/branch before implementation.
- Do not edit anything under `benchmarks/`.
- Do not revert unrelated user changes.
- Use TDD for every task: write focused failing tests first, run them, implement the minimum code, rerun them, commit.
- Keep ML dependencies optional. Default CI and default Docker behavior must work when dense reranking is disabled.
- Prefer deterministic fake embedding providers in unit tests.
- Run `make ci-local` before claiming completion.

## File Map

- Modify: `pyproject.toml`
  - Add optional dependency extra for local embedding rerank runtime.
- Modify: `docker/docker-compose.yml`
  - Use a pgvector-capable Postgres 18 image.
- Modify: `tests/unit/docker/test_docker_compose_postgres.py`
  - Assert the compose file uses a pgvector image.
- Create: `pubtator_link/db/migrations/0005_review_passage_embeddings.sql`
  - Enable `vector` and create `review_passage_embeddings`.
- Modify: `pubtator_link/db/migrate.py`
  - Require the embedding table when schema-current checks run after the migration.
- Modify: `tests/unit/test_db_migrations.py`
  - Cover migration ordering and required schema diagnostics.
- Modify: `pubtator_link/config.py`
  - Add review embedding rerank settings to `ServerSettings` and `ReviewReragConfig`.
- Modify: `tests/unit/test_review_rerag_config.py`
  - Cover default-disabled config and env parsing.
- Create: `pubtator_link/services/review_context/embeddings.py`
  - Define embedding provider protocol, local BGE provider, fake provider helpers, text hashing, and provider errors.
- Create: `tests/unit/test_review_context_embeddings.py`
  - Cover hash stability, BGE instruction formatting, missing dependency behavior, and fake provider dimensions.
- Create: `pubtator_link/services/review_context/embedding_rerank.py`
  - Implement guarded dense ranking, RRF fusion, and diagnostics payload creation.
- Create: `tests/unit/test_review_context_embedding_rerank.py`
  - Cover evidence-section guardrails, RRF ordering, missing embeddings, and fallback reasons.
- Modify: `pubtator_link/models/review_rerag.py`
  - Add `EmbeddingRerankDiagnostics` and optional field on retrieval diagnostics.
- Modify: `pubtator_link/repositories/review_rerag.py`
  - Add embedding table read/write methods.
- Modify: `tests/unit/test_review_rerag_repository.py`
  - Cover repository embedding upsert/fetch with fake async connection or existing repository test pattern.
- Modify: `pubtator_link/services/full_text_preparation.py`
  - Generate embeddings for newly indexed passages when enabled.
- Modify: `tests/unit/test_full_text_preparation.py`
  - Cover embedding generation success and non-fatal embedding failure.
- Create: `pubtator_link/services/review_context/embedding_backfill.py`
  - Backfill missing or stale passage embeddings for existing review indexes.
- Create: `tests/unit/test_review_context_embedding_backfill.py`
  - Cover bounded backfill, stale hash refresh, and non-fatal provider errors.
- Modify: `pubtator_link/services/review_context_service.py`
  - Inject reranker/provider and use dense RRF before packing.
- Modify: `pubtator_link/api/routes/dependencies.py`
  - Build the optional embedding provider and pass reranker dependencies into `ReviewContextService`.
- Modify: `tests/unit/test_review_context_service.py`
  - Cover dense RRF order and lexical fallback.
- Modify: `tests/unit/test_route_dependencies.py`
  - Cover provider not created when disabled and created when enabled.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Preserve diagnostics in MCP response serialization.
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
  - Assert dense rerank diagnostics survive adapter conversion.
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
  - Document local dense rerank configuration and fallback behavior.

## Task 0: Create Implementation Worktree

**Files:**
- No source files modified.

- [ ] **Step 1: Check current checkout state**

Run:

```bash
git status --short --branch
```

Expected: branch and local changes are visible. If unrelated files are dirty,
leave them alone.

- [ ] **Step 2: Create a feature worktree**

Run:

```bash
git worktree add .worktrees/hybrid-embedding-reranker -b codex/hybrid-embedding-reranker
cd .worktrees/hybrid-embedding-reranker
```

Expected: new branch `codex/hybrid-embedding-reranker` checked out in an
isolated worktree.

- [ ] **Step 3: Establish baseline**

Run:

```bash
make test
```

Expected: the existing test suite passes before feature work starts.

## Task 1: Add pgvector Schema And Docker Support

**Files:**
- Create: `pubtator_link/db/migrations/0005_review_passage_embeddings.sql`
- Modify: `pubtator_link/db/migrate.py`
- Modify: `docker/docker-compose.yml`
- Modify: `tests/unit/test_db_migrations.py`
- Modify: `tests/unit/docker/test_docker_compose_postgres.py`

- [ ] **Step 1: Write failing schema tests**

Add tests asserting:

```python
def test_review_passage_embeddings_migration_is_bundled() -> None:
    migration_names = [path.name for path in iter_sql_migrations()]
    assert "0005_review_passage_embeddings.sql" in migration_names


def test_required_schema_includes_review_passage_embeddings() -> None:
    required_tables = {item.name for item in REQUIRED_SCHEMA_ITEMS if item.kind == "table"}
    assert "review_passage_embeddings" in required_tables
```

Add a Docker compose test asserting:

```python
def test_compose_postgres_uses_pgvector_image() -> None:
    compose = yaml.safe_load(Path("docker/docker-compose.yml").read_text())
    image = compose["services"]["pubtator-postgres"]["image"]
    assert image.startswith("pgvector/pgvector:")
    assert "pg18" in image
```

- [ ] **Step 2: Run failing focused tests**

Run:

```bash
uv run pytest tests/unit/test_db_migrations.py tests/unit/docker/test_docker_compose_postgres.py -q
```

Expected: tests fail because the migration and pgvector image are not present.

- [ ] **Step 3: Add migration**

Create `pubtator_link/db/migrations/0005_review_passage_embeddings.sql`:

```sql
create extension if not exists vector;

create table if not exists review_passage_embeddings (
    review_id text not null,
    passage_id text not null,
    model_name text not null,
    embedding_dim integer not null check (embedding_dim = 384),
    text_hash text not null,
    embedding vector(384) not null,
    created_at timestamptz not null default now(),
    primary key (review_id, passage_id, model_name),
    foreign key (review_id, passage_id)
        references review_passages(review_id, passage_id)
        on delete cascade
);

create index if not exists review_passage_embeddings_lookup_idx
    on review_passage_embeddings(review_id, model_name, passage_id);
```

- [ ] **Step 4: Add schema requirements and Docker image**

In `pubtator_link/db/migrate.py`, add `review_passage_embeddings` to required
tables. In `docker/docker-compose.yml`, change the Postgres image to:

```yaml
image: pgvector/pgvector:0.8.2-pg18-trixie
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_db_migrations.py tests/unit/docker/test_docker_compose_postgres.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/db/migrations/0005_review_passage_embeddings.sql pubtator_link/db/migrate.py docker/docker-compose.yml tests/unit/test_db_migrations.py tests/unit/docker/test_docker_compose_postgres.py
git commit -m "feat: add review passage embedding schema"
```

## Task 2: Add Dense Rerank Configuration

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `tests/unit/test_review_rerag_config.py`

- [ ] **Step 1: Write failing config tests**

Add tests covering:

```python
def test_review_embedding_rerank_defaults_disabled() -> None:
    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)
    assert config.embedding_rerank_enabled is False
    assert config.embedding_model == "BAAI/bge-small-en-v1.5"
    assert config.embedding_dim == 384
    assert config.embedding_top_k == 50
    assert config.embedding_rrf_k == 60
```

```python
def test_review_embedding_rerank_env_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_EMBEDDING_RERANK_ENABLED", "true")
    monkeypatch.setenv("PUBTATOR_LINK_REVIEW_EMBEDDING_TOP_K", "40")
    settings = ServerSettings()
    config = ReviewReragConfig.from_settings(settings)
    assert config.embedding_rerank_enabled is True
    assert config.embedding_top_k == 40
```

- [ ] **Step 2: Run failing focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_config.py -q
```

Expected: tests fail because the fields are missing.

- [ ] **Step 3: Implement config fields**

Add `ServerSettings` fields:

```python
review_embedding_rerank_enabled: bool = False
review_embedding_model: str = "BAAI/bge-small-en-v1.5"
review_embedding_dim: int = Field(default=384, ge=1, le=2000)
review_embedding_top_k: int = Field(default=50, ge=1, le=100)
review_embedding_rrf_k: int = Field(default=60, ge=1, le=1000)
review_embedding_batch_size: int = Field(default=32, ge=1, le=256)
review_embedding_device: str = "auto"
```

Add matching frozen dataclass fields to `ReviewReragConfig` and map them in
`from_settings()`.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_config.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/config.py tests/unit/test_review_rerag_config.py
git commit -m "feat: configure review embedding rerank"
```

## Task 3: Add Embedding Provider Boundary

**Files:**
- Modify: `pyproject.toml`
- Create: `pubtator_link/services/review_context/embeddings.py`
- Create: `tests/unit/test_review_context_embeddings.py`

- [ ] **Step 1: Write failing provider tests**

Create tests for:

```python
def test_text_hash_is_stable_for_same_text() -> None:
    assert text_hash("a passage") == text_hash("a passage")
    assert text_hash("a passage") != text_hash("another passage")
```

```python
async def test_fake_embedding_provider_returns_expected_dimension() -> None:
    provider = FakeEmbeddingProvider(dim=384)
    vectors = await provider.embed_passages(["alpha", "beta"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 384
```

```python
def test_bge_query_instruction_is_applied_only_to_query() -> None:
    assert bge_query_text("dose escalation").startswith(
        "Represent this sentence for searching relevant passages: "
    )
    assert bge_passage_text("dose escalation") == "dose escalation"
```

- [ ] **Step 2: Run failing focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embeddings.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Add optional dependencies**

Add this optional dependency group to `pyproject.toml`:

```toml
[project.optional-dependencies]
embeddings = [
    "sentence-transformers>=5.0.0,<6.0.0",
    "torch>=2.5.0",
    "numpy>=2.0.0,<3.0.0",
]
```

- [ ] **Step 4: Implement provider module**

Create `pubtator_link/services/review_context/embeddings.py` with:

```python
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Protocol


class EmbeddingProviderUnavailableError(RuntimeError):
    """Raised when optional local embedding dependencies are unavailable."""


class EmbeddingProvider(Protocol):
    model_name: str
    dim: int

    async def embed_query(self, text: str) -> list[float]:
        """Embed one query."""

    async def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passage texts."""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bge_query_text(text: str) -> str:
    return f"Represent this sentence for searching relevant passages: {text}"


def bge_passage_text(text: str) -> str:
    return text
```

Then add a deterministic `FakeEmbeddingProvider` and a lazy
`SentenceTransformerEmbeddingProvider` that imports `sentence_transformers` and
`numpy` inside its constructor or first use. If imports fail, raise
`EmbeddingProviderUnavailableError`.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embeddings.py -q
```

Expected: tests pass without installing optional ML dependencies.

- [ ] **Step 6: Commit**

Run:

```bash
git add pyproject.toml pubtator_link/services/review_context/embeddings.py tests/unit/test_review_context_embeddings.py
git commit -m "feat: add review embedding provider boundary"
```

## Task 4: Add Guarded Dense RRF Ranking

**Files:**
- Create: `pubtator_link/services/review_context/embedding_rerank.py`
- Create: `tests/unit/test_review_context_embedding_rerank.py`
- Modify: `pubtator_link/models/review_rerag.py`

- [ ] **Step 1: Write failing rerank tests**

Create tests proving:

```python
def test_guarded_dense_rerank_does_not_promote_references() -> None:
    rows = [
        row("lexical-evidence", section="DISCUSS", lexical_rank=4.0),
        row("semantic-ref", section="REF", lexical_rank=1.0),
    ]
    result = rerank_with_embeddings(
        rows,
        dense_scores={"lexical-evidence": 0.50, "semantic-ref": 0.99},
        rrf_k=60,
    )
    assert [item.row.passage_id for item in result.ranked] == [
        "lexical-evidence",
        "semantic-ref",
    ]
```

```python
def test_rrf_combines_lexical_and_dense_rank() -> None:
    rows = [
        row("lexical-first", section="DISCUSS", lexical_rank=10.0),
        row("semantic-first", section="DISCUSS", lexical_rank=1.0),
    ]
    result = rerank_with_embeddings(
        rows,
        dense_scores={"lexical-first": 0.60, "semantic-first": 0.99},
        rrf_k=60,
    )
    assert result.diagnostics.strategy == "lexical_top_k_dense_rrf"
    assert {item.row.passage_id for item in result.ranked} == {
        "lexical-first",
        "semantic-first",
    }
```

- [ ] **Step 2: Run failing focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embedding_rerank.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Add diagnostics model**

In `pubtator_link/models/review_rerag.py`, add:

```python
class EmbeddingRerankDiagnostics(BaseModel):
    enabled: bool = False
    active: bool = False
    model_name: str | None = None
    embedding_dim: int | None = None
    candidate_count: int = Field(default=0, ge=0)
    embedded_candidate_count: int = Field(default=0, ge=0)
    missing_embedding_count: int = Field(default=0, ge=0)
    strategy: str | None = None
    fallback_reason: str | None = None
```

Add `embedding_rerank: EmbeddingRerankDiagnostics | None = None` to the
existing retrieval diagnostics model used by review context responses.

- [ ] **Step 4: Implement rerank module**

Implement `rerank_with_embeddings()` so it:

- sorts lexical rank with existing `rerank_key`
- ranks evidence sections by dense score
- appends `ref`, `references`, and `abbr` after evidence sections
- computes RRF score with `1 / (rrf_k + rank)`
- returns ranked rows plus `EmbeddingRerankDiagnostics`

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embedding_rerank.py tests/unit/test_review_rerag_models.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/review_context/embedding_rerank.py pubtator_link/models/review_rerag.py tests/unit/test_review_context_embedding_rerank.py tests/unit/test_review_rerag_models.py
git commit -m "feat: add guarded embedding rrf ranking"
```

## Task 5: Add Embedding Repository Methods

**Files:**
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `tests/unit/test_review_rerag_repository.py`

- [ ] **Step 1: Write failing repository tests**

Add tests covering:

- `upsert_passage_embeddings()` writes `review_id`, `passage_id`,
  `model_name`, `embedding_dim`, `text_hash`, and vector values.
- `get_passage_embeddings()` returns a `dict[str, list[float]]` keyed by
  `passage_id`.
- `list_passages_missing_embeddings()` returns passages with no embedding row
  or a stale `text_hash`.
- stale `text_hash` values are not returned when the caller passes current
  passage hashes.

- [ ] **Step 2: Run focused repository tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_repository.py -q
```

Expected: tests fail because repository methods do not exist.

- [ ] **Step 3: Implement repository methods**

Add a small dataclass near repository protocols:

```python
@dataclass(frozen=True)
class ReviewPassageEmbeddingRecord:
    review_id: str
    passage_id: str
    model_name: str
    embedding_dim: int
    text_hash: str
    embedding: list[float]
```

Implement methods on `PostgresReviewReragRepository` using asyncpg `executemany`
for upsert and filtered `select` queries for reads. Follow the existing fake
pool/fake connection pattern already used in `tests/unit/test_review_rerag_repository.py`.
`list_passages_missing_embeddings()` should compute the current passage
`text_hash` in Python after loading candidate rows and return rows whose stored
hash is absent or different.

- [ ] **Step 4: Run focused repository tests**

Run:

```bash
uv run pytest tests/unit/test_review_rerag_repository.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/repositories/review_rerag.py tests/unit/test_review_rerag_repository.py
git commit -m "feat: persist review passage embeddings"
```

## Task 6: Integrate Embeddings Into Preparation

**Files:**
- Modify: `pubtator_link/services/full_text_preparation.py`
- Modify: `tests/unit/test_full_text_preparation.py`

- [ ] **Step 1: Write failing preparation tests**

Add tests proving:

- when embedding rerank is enabled and a provider is injected, newly indexed
  passages are embedded and upserted
- when provider embedding raises `EmbeddingProviderUnavailableError`, passage
  indexing still succeeds and the source is not marked failed

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_full_text_preparation.py -q
```

Expected: tests fail because preparation does not embed passages.

- [ ] **Step 3: Implement minimal integration**

Add optional constructor args to `FullTextPreparationService`:

```python
embedding_provider: EmbeddingProvider | None = None
embedding_model: str = "BAAI/bge-small-en-v1.5"
embedding_dim: int = 384
```

After successful passage upsert, compute raw passage text hashes and call
repository `upsert_passage_embeddings()` when the provider is present. Catch
embedding-provider errors and log a warning without failing preparation.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_full_text_preparation.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/services/full_text_preparation.py tests/unit/test_full_text_preparation.py
git commit -m "feat: embed review passages during preparation"
```

## Task 7: Add Existing-Index Embedding Backfill

**Files:**
- Create: `pubtator_link/services/review_context/embedding_backfill.py`
- Create: `tests/unit/test_review_context_embedding_backfill.py`

- [ ] **Step 1: Write failing backfill tests**

Create tests proving:

```python
async def test_backfill_embeds_missing_passages_in_batches() -> None:
    repository = FakeEmbeddingBackfillRepository(
        missing=[
            ReviewPassageRow(
                passage_id="p1",
                review_id="r1",
                source_id="s1",
                source_kind="pubtator_full_bioc",
                section="DISCUSS",
                text="Colchicine dose adjustment evidence.",
                lexical_rank=1.0,
            )
        ]
    )
    provider = FakeEmbeddingProvider(dim=384)
    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        limit=100,
    )
    assert result.embedded_count == 1
    assert repository.upserted[0].passage_id == "p1"
```

```python
async def test_backfill_reports_provider_failure_without_raising() -> None:
    repository = FakeEmbeddingBackfillRepository(missing=[passage("p1")])
    provider = FailingEmbeddingProvider()
    result = await backfill_review_passage_embeddings(
        repository=repository,
        review_id="r1",
        provider=provider,
        model_name="BAAI/bge-small-en-v1.5",
        embedding_dim=384,
        batch_size=16,
        limit=100,
    )
    assert result.embedded_count == 0
    assert result.failed_count == 1
    assert result.error is not None
```

- [ ] **Step 2: Run failing focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embedding_backfill.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement backfill service**

Create `pubtator_link/services/review_context/embedding_backfill.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass

from pubtator_link.repositories.review_rerag import ReviewPassageEmbeddingRecord
from pubtator_link.services.review_context.embeddings import (
    EmbeddingProvider,
    text_hash,
)


@dataclass(frozen=True)
class EmbeddingBackfillResult:
    review_id: str
    embedded_count: int
    failed_count: int
    error: str | None = None
```

Add `backfill_review_passage_embeddings()` that asks the repository for missing
passages, embeds raw passage text in batches, and upserts
`ReviewPassageEmbeddingRecord` values with current text hashes. Catch provider
exceptions and return `EmbeddingBackfillResult` instead of raising.

- [ ] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embedding_backfill.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add pubtator_link/services/review_context/embedding_backfill.py tests/unit/test_review_context_embedding_backfill.py
git commit -m "feat: add review embedding backfill service"
```

## Task 8: Integrate Dense RRF Into Review Retrieval

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `tests/unit/test_review_context_service.py`
- Modify: `tests/unit/test_route_dependencies.py`

- [ ] **Step 1: Write failing service tests**

Add tests proving:

- dense RRF can move a semantically strong evidence passage above a lexical-only
  table passage
- `REF` remains below evidence even with a higher dense score
- missing embeddings produce lexical fallback with diagnostics
- provider unavailable produces lexical fallback with diagnostics

- [ ] **Step 2: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_route_dependencies.py -q
```

Expected: tests fail because retrieval does not use embeddings.

- [ ] **Step 3: Inject optional rerank dependencies**

Extend `ReviewContextService.__init__()` with:

```python
embedding_provider: EmbeddingProvider | None = None
embedding_rerank_enabled: bool = False
embedding_model: str = "BAAI/bge-small-en-v1.5"
embedding_dim: int = 384
embedding_top_k: int = 50
embedding_rrf_k: int = 60
```

When enabled, search with `limit=embedding_top_k`, fetch candidate embeddings,
embed the query, call `rerank_with_embeddings()`, and pack the fused order.
When disabled or failed, preserve the current `sorted(candidates, key=rerank_key)`
behavior.

- [ ] **Step 4: Build provider in dependencies**

In `pubtator_link/api/routes/dependencies.py`, create the local provider only
when `review_rerag_config.embedding_rerank_enabled` is true. If optional
dependencies are unavailable, log and pass `None` so retrieval falls back.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_route_dependencies.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/services/review_context_service.py pubtator_link/api/routes/dependencies.py tests/unit/test_review_context_service.py tests/unit/test_route_dependencies.py
git commit -m "feat: rerank review context with embeddings"
```

## Task 9: Surface MCP Diagnostics And Documentation

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`

- [ ] **Step 1: Write failing adapter test**

Add a test asserting that `embedding_rerank` diagnostics appear in the serialized
`retrieve_review_context_batch` MCP response when the service response contains
them.

- [ ] **Step 2: Run focused adapter tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: test fails if diagnostics are dropped.

- [ ] **Step 3: Preserve diagnostics**

Update adapter serialization only if needed so `embedding_rerank` survives
existing model dumping and response shaping. Do not add a new MCP parameter for
the MVP; the feature is deployment-configured.

- [ ] **Step 4: Document local configuration**

Add a section to `docs/MCP_CONNECTION_GUIDE.md` with:

````markdown
### Optional Local Embedding Rerank

Private deployments can enable local dense reranking for review retrieval:

```bash
PUBTATOR_LINK_REVIEW_EMBEDDING_RERANK_ENABLED=true
PUBTATOR_LINK_REVIEW_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
PUBTATOR_LINK_REVIEW_EMBEDDING_DIM=384
```

The server keeps lexical retrieval as the fallback when embeddings are missing,
the model is unavailable, or `pgvector` is not installed.
````

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py docs/MCP_CONNECTION_GUIDE.md
git commit -m "docs: document embedding rerank diagnostics"
```

## Task 10: Final Verification

**Files:**
- No planned source edits.

- [ ] **Step 1: Run focused feature tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_embedding_rerank.py tests/unit/test_review_context_embeddings.py tests/unit/test_review_context_embedding_backfill.py tests/unit/test_review_context_service.py tests/unit/test_full_text_preparation.py tests/unit/test_review_rerag_repository.py tests/unit/test_db_migrations.py tests/unit/docker/test_docker_compose_postgres.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full local CI**

Run:

```bash
make ci-local
```

Expected: format, lint, typecheck, and tests all pass.

- [ ] **Step 3: Rebuild/restart Docker when CI passes**

Run:

```bash
PUBTATOR_LINK_PORT=8011 PUBTATOR_LINK_POSTGRES_PORT=55432 docker compose -f docker/docker-compose.yml up -d --build --force-recreate
```

Expected: Postgres and server containers are healthy on the same ports.

- [ ] **Step 4: Smoke test lexical fallback**

Run an MCP `pubtator.retrieve_review_context_batch` call with dense rerank
disabled. Expected: existing compact retrieval still works and no dense rerank
diagnostic claims active reranking.

- [ ] **Step 5: Smoke test dense rerank**

Enable dense rerank locally, index or backfill embeddings for a small review,
then call `pubtator.retrieve_review_context_batch`. Expected:

- response succeeds
- diagnostics show `embedding_rerank.active=true`
- `model_name` is `BAAI/bge-small-en-v1.5`
- `strategy` is `lexical_top_k_dense_rrf`
- `REF` and `ABBR` passages are not promoted above evidence sections

- [ ] **Step 6: Smoke test fallback diagnostics**

Temporarily configure an unavailable embedding model and call retrieval.
Expected: response still succeeds with lexical ordering and
`embedding_rerank.fallback_reason="provider_unavailable"` or
`"query_embedding_failed"`.

## Self-Review Checklist

- [ ] Dense rerank is disabled by default.
- [ ] No files under `benchmarks/` are edited.
- [ ] `REF`, `references`, and `ABBR` are guarded from dense promotion.
- [ ] Existing lexical ranking remains the fallback.
- [ ] Optional ML dependencies are not required for default CI.
- [ ] Docker Postgres supports `create extension vector`.
- [ ] `make ci-local` passes before completion is claimed.
