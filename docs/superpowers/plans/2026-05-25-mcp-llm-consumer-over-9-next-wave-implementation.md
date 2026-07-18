# MCP LLM Consumer Over 9 Next Wave Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the MCP ergonomics and reliability wave needed for a 9+ LLM-consumer score: canonical aliases, validation-error discoverability, metadata-budget controls, and targeted sub-9 tool improvements.

**Architecture:** Add compatibility and response-budget behavior at shared MCP boundaries first, then fix per-tool gaps with focused service/adapter changes. Keep public tool names and existing canonical parameters stable while documenting `query` and `pmid` as preferred LLM-facing inputs.

**Tech Stack:** Python 3.11, FastMCP, Pydantic, FastAPI dependency providers, pytest, Ruff, mypy, uv, Makefile.

---

## Mandatory Reading

- `AGENTS.md` and `CLAUDE.md`, especially file-size discipline and `uv`/Makefile conventions.
- `.loc-allowlist`; do not grow grandfathered files past their ceilings.
- `.claude/skills/mcp-tool-change/SKILL.md`; all tasks change MCP schemas or responses.
- `pubtator_link/mcp/tools/literature.py`
- `pubtator_link/mcp/tools/discovery.py`
- `pubtator_link/mcp/tools/publications.py`
- `pubtator_link/mcp/tools/review/research.py`
- `pubtator_link/mcp/tools/review/retrieval.py`
- `pubtator_link/mcp/errors.py`
- `pubtator_link/mcp/input_normalization.py`
- `pubtator_link/mcp/service_adapters.py`
- `pubtator_link/services/search_shaping.py`
- `pubtator_link/services/ncbi_discovery.py`
- `pubtator_link/services/corpus_suggestion.py`
- `pubtator_link/services/related_evidence.py`

## File Structure

- Create: `pubtator_link/mcp/argument_aliases.py`
  - Shared helpers for query aliases, PMID scalar/list merging, and schema-facing alias docs.
- Create: `pubtator_link/mcp/validation_errors.py`
  - Extract valid params and enum/literal values from tool schemas and validation exceptions.
- Create: `pubtator_link/mcp/meta_budget.py`
  - Strip `_meta` and diagnostic ranking/provider fields when `include_meta=false`.
- Modify: `pubtator_link/mcp/errors.py`
  - Include enriched validation details in the MCP error envelope.
- Modify: `pubtator_link/mcp/tools/*.py`
  - Add alias parameters and `include_meta` knobs without renaming tools.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Pass normalized args to services and call meta-budget helpers.
- Modify: `pubtator_link/services/search_shaping.py`
  - Support guideline reranking and metadata/ranking stripping.
- Modify: `pubtator_link/services/ncbi_discovery.py`
  - Enrich citation lookup and related article results with metadata.
- Modify: `pubtator_link/services/corpus_suggestion.py`
  - Add relevance threshold plus `matched_terms` and `matched_intents`.
- Modify: `pubtator_link/services/related_evidence.py`
  - Fast-fail metadata enrichment and expose `metadata_status`.
- Modify: `pubtator_link/models/*.py`
  - Add optional response fields for budget advice, freshness notes, metadata status, note event type, and compact meta controls.
- Modify: `docs/mcp-tool-catalog.md`
  - Regenerate after schema changes.
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: `tests/unit/test_corpus_suggestion_service.py`
- Test: `tests/unit/test_related_evidence_service.py`
- Test: `tests/unit/test_search_shaping.py`

---

### Task 1: Canonical Query and PMID Aliases

**Files:**
- Create: `pubtator_link/mcp/argument_aliases.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/tools/discovery.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/tools/review/research.py`
- Modify: `pubtator_link/mcp/tools/review/retrieval.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing schema and invocation tests**

Add tests proving these calls do not schema-fail and normalize to canonical service inputs:

```python
@pytest.mark.asyncio
async def test_search_guidelines_accepts_query_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_impl(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"success": True, "query": kwargs["text"], "results": []}

    monkeypatch.setattr(literature_tools, "search_literature_impl", fake_impl)
    tool = create_pubtator_mcp(profile="full")._tool_manager._tools["search_guidelines"]
    await tool.run({"query": "familial mediterranean fever pediatric"})
    assert captured["text"] == "familial mediterranean fever pediatric"


def test_pmid_list_tools_expose_scalar_pmid_alias() -> None:
    tools = create_pubtator_mcp(profile="full")._tool_manager._tools
    for name in (
        "preflight_review_sources",
        "get_publication_metadata",
        "estimate_publication_context",
        "find_related_articles",
    ):
        assert "pmid" in tools[name].parameters["properties"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py -q -k "query_alias or scalar_pmid_alias"`

Expected: FAIL because several tools do not expose `query` or `pmid` aliases yet.

- [ ] **Step 3: Add shared alias helpers**

Create `pubtator_link/mcp/argument_aliases.py`:

```python
from __future__ import annotations

from collections.abc import Iterable


def coalesce_query(*values: str | None) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    msg = "Provide query."
    raise ValueError(msg)


def merge_pmids(pmids: Iterable[str] | None = None, pmid: str | None = None) -> list[str]:
    merged: list[str] = []
    for value in [*(pmids or []), pmid or ""]:
        stripped = str(value).strip()
        if stripped and stripped not in merged:
            merged.append(stripped)
    if not merged:
        msg = "Provide pmids or pmid."
        raise ValueError(msg)
    return merged
```

- [ ] **Step 4: Add aliases at tool boundaries**

Use `coalesce_query(query, text, question, topic)` and `merge_pmids(pmids, pmid)` in affected tools. Keep existing parameters, add aliases as optional parameters, and pass only canonical values to service adapters.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q -k "query_alias or scalar_pmid_alias"
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q -k "search_literature or passages or preflight"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/argument_aliases.py pubtator_link/mcp/tools tests/unit/mcp/test_mcp_facade.py
git commit -m "feat(mcp): converge query and PMID aliases"
```

---

### Task 2: Validation Error Discovery Envelope

**Files:**
- Create: `pubtator_link/mcp/validation_errors.py`
- Modify: `pubtator_link/mcp/errors.py`
- Modify: `pubtator_link/mcp/facade.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing validation UX tests**

Add tests that call a tool with an unknown argument and a bad enum, then assert:

```python
assert payload["error_code"] == "validation_failed"
assert "valid_params" in payload
assert "valid_values_for" in payload
assert payload["valid_values_for"]["response_mode"] == ["compact", "standard", "full"]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py -q -k "validation"`

Expected: FAIL because validation envelopes do not consistently include valid params and enum values.

- [ ] **Step 3: Implement schema extraction**

Create `pubtator_link/mcp/validation_errors.py` with helpers:

```python
from __future__ import annotations

from typing import Any


def valid_params_from_schema(schema: dict[str, Any]) -> list[str]:
    properties = schema.get("properties", {})
    return sorted(properties) if isinstance(properties, dict) else []


def enum_values_from_schema(schema: dict[str, Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for field, spec in schema.get("properties", {}).items():
        if isinstance(spec, dict) and isinstance(spec.get("enum"), list):
            values[field] = [str(item) for item in spec["enum"]]
    return values
```

- [ ] **Step 4: Attach details to validation failures**

When a tool invocation fails validation, enrich the existing `ToolError` payload with:

```python
payload["valid_params"] = valid_params_from_schema(tool_schema)
payload["valid_values_for"] = enum_values_from_schema(tool_schema)
payload["recovery"] = "Retry with one of valid_params and documented enum values."
```

Keep existing `_meta.next_commands` and safety flags.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py -q -k "validation"
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/validation_errors.py pubtator_link/mcp/errors.py pubtator_link/mcp/facade.py tests/unit/test_mcp_errors.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat(mcp): expose validation recovery details"
```

---

### Task 3: Shared `include_meta` Budget Control

**Files:**
- Create: `pubtator_link/mcp/meta_budget.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review/research.py`
- Modify: `pubtator_link/mcp/tools/review/retrieval.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing compact-meta tests**

Add a representative adapter test:

```python
def test_strip_meta_removes_workflow_and_ranking_diagnostics() -> None:
    payload = {
        "_meta": {"workflow": "search -> retrieve"},
        "results": [{"pmid": "1", "rrf_score": 1.0, "title": "A"}],
    }
    assert strip_meta_for_repeated_call(payload) == {"results": [{"pmid": "1", "title": "A"}]}
```

Add schema tests asserting `include_meta` appears on repeated-call search/retrieval/staging tools.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "include_meta or strip_meta"`

Expected: FAIL because only search literature supports this knob.

- [ ] **Step 3: Implement shared stripper**

Create `pubtator_link/mcp/meta_budget.py`:

```python
from __future__ import annotations

from copy import deepcopy
from typing import Any

DIAGNOSTIC_FIELDS = {
    "_meta",
    "rrf_score",
    "lexical_rank_position",
    "dense_rank_position",
    "rank_features",
    "provider_status",
}


def strip_meta_for_repeated_call(payload: dict[str, Any]) -> dict[str, Any]:
    stripped = deepcopy(payload)
    stripped.pop("_meta", None)
    for key in ("results", "candidates", "related_articles", "sessions"):
        items = stripped.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    for field in DIAGNOSTIC_FIELDS:
                        item.pop(field, None)
    return stripped
```

- [ ] **Step 4: Wire `include_meta`**

Add `include_meta: bool = True` to the selected tools and call
`strip_meta_for_repeated_call(result)` before returning when false. Do not strip
citation fields, coverage fields, passage IDs, or safety flags.

- [ ] **Step 5: Verify payload reduction**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "include_meta or strip_meta"
uv run python scripts/smoke_mcp_tool_surface.py --base-url http://127.0.0.1:8011
```

Expected: tests PASS; smoke responses remain successful. If Docker is not running, skip only the smoke command and record that in the commit status.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/meta_budget.py pubtator_link/mcp/tools pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat(mcp): add shared metadata budget control"
```

---

### Task 4: Discovery Metadata and Ranking Polish

**Files:**
- Modify: `pubtator_link/services/search_shaping.py`
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: `pubtator_link/services/corpus_suggestion.py`
- Modify: `pubtator_link/mcp/tools/discovery.py`
- Test: `tests/unit/test_search_shaping.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: `tests/unit/test_corpus_suggestion_service.py`

- [ ] **Step 1: Write failing tests**

Add tests asserting:

```python
def test_guideline_boost_reranks_without_hard_filtering() -> None:
    items = [{"pmid": "1", "title": "EULAR recommendations", "publication_types": []}]
    assert selected_search_items(items, guideline_boost=True, limit=5)[0]["pmid"] == "1"


async def test_lookup_citation_enriches_matched_metadata() -> None:
    response = await service.lookup_citation(["Known title. Journal. 2026."])
    record = response.records[0]
    assert record.title == "Known title"
    assert record.journal == "Journal"
    assert record.year == 2026


def test_suggest_corpus_discloses_relevance_reasons() -> None:
    candidate = response.candidates[0]
    assert candidate.matched_terms
    assert candidate.matched_intents
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py tests/unit/test_ncbi_discovery_service.py tests/unit/test_corpus_suggestion_service.py -q -k "guideline or citation or relevance"
```

Expected: FAIL for missing enrichment/relevance fields where not already implemented.

- [ ] **Step 3: Implement discovery polish**

Use existing PubMed metadata fetch paths to enrich citation lookup and related records. Add relevance thresholding to corpus suggestion so off-topic candidates are demoted or omitted, and include `matched_terms`/`matched_intents` on returned candidates.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_search_shaping.py tests/unit/test_ncbi_discovery_service.py tests/unit/test_corpus_suggestion_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/search_shaping.py pubtator_link/services/ncbi_discovery.py pubtator_link/services/corpus_suggestion.py pubtator_link/mcp/tools/discovery.py tests/unit/test_search_shaping.py tests/unit/test_ncbi_discovery_service.py tests/unit/test_corpus_suggestion_service.py
git commit -m "fix(discovery): enrich and rerank MCP candidates"
```

---

### Task 5: Publication Graph and Context Budget Advice

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/models/publication_passages.py`
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing tests**

Add assertions for:

```python
assert estimate["recommended_max_chars"] >= estimate["estimated_chars"]
assert graph["freshness_note"].startswith("Citation graph providers typically lag")
assert candidate["metadata_status"] in {"success", "timeout", "partial"}
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_related_evidence_service.py -q -k "recommended_max_chars or freshness_note or metadata_status"`

Expected: FAIL for missing fields.

- [ ] **Step 3: Implement fields**

Add:

- `recommended_max_chars` to publication context estimates, computed as estimated chars plus a small safety margin capped by the tool maximum.
- `freshness_note` when citation graph providers return no references and no cited-by records for a recent publication.
- `metadata_status` on related evidence candidates when metadata enrichment succeeds, partially succeeds, or times out.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_related_evidence_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/models/publication_passages.py pubtator_link/models/literature_graph.py pubtator_link/services/related_evidence.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_related_evidence_service.py
git commit -m "feat(publications): expose budget and freshness hints"
```

---

### Task 6: Review Workflow Ergonomics

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/tools/review/research.py`
- Modify: `pubtator_link/mcp/tools/review/retrieval.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/services/research_session.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_research_session_service.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:

```python
assert "note" in ReviewLlmContextEventType.__args__
await quickstart_tool.run({"question": "MEFV VUS pediatric"})
await list_sessions_tool.run({})
await status_tool.run({"session_id": "known-session"})
```

For `ground_question`, add a long natural-language query fixture and assert the adapter attempts keyword query variants before returning zero-result recovery.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_research_session_service.py -q -k "note or quickstart or session or ground_question"`

Expected: FAIL for missing note event, missing aliases, and session lookup scope gaps.

- [ ] **Step 3: Implement review ergonomics**

Add:

- `note` to `ReviewLlmContextEventType`.
- `question` alias for `review_quickstart(topic=...)`.
- Optional `review_id` for `list_research_sessions`; when omitted, return a global bounded list ordered by update time.
- Optional `review_id` for `get_research_session_status`; when omitted, resolve by globally unique `session_id`.
- Long-query decomposition in `ground_question_impl`: derive a short keyword query from biomedical entities and high-signal nouns, search variants, and report `query_variants_attempted`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_research_session_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/mcp/tools/review pubtator_link/mcp/service_adapters.py pubtator_link/services/research_session.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_research_session_service.py
git commit -m "feat(review): smooth research workflow ergonomics"
```

---

### Task 7: Text Annotation Wait Mode and Retry

**Files:**
- Modify: `pubtator_link/mcp/tools/text_annotations.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/api/client.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_pubtator_client_text_annotation.py`

- [ ] **Step 1: Write failing tests**

Add tests for:

```python
result = await submit_text_annotation_tool.run({"text": "MEFV and colchicine", "wait": True})
assert result["success"] is True
assert "annotations" in result or result["status"] in {"complete", "pending"}
```

Add client tests showing `get_text_annotation_results` retries transient upstream failures with bounded backoff.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_pubtator_client_text_annotation.py -q -k "text_annotation"`

Expected: FAIL because submit does not support wait mode and result polling is fragile.

- [ ] **Step 3: Implement wait mode**

Add `wait: bool = False` and `timeout_ms: int = 30000` to `submit_text_annotation`. When `wait=true`, submit the job, poll `get_text_annotation_results` server-side with bounded backoff, and return either the final annotation result or a pending envelope with retry instructions.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_pubtator_client_text_annotation.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/tools/text_annotations.py pubtator_link/mcp/service_adapters.py pubtator_link/api/client.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/test_pubtator_client_text_annotation.py
git commit -m "feat(mcp): add text annotation wait mode"
```

---

### Task 8: Catalog, Smoke, and Full Verification

**Files:**
- Modify: `docs/mcp-tool-catalog.md`
- Modify: runtime generated catalog source if the repo generator updates one.
- Test: existing focused tests and local smoke scripts.

- [ ] **Step 1: Regenerate MCP catalog**

Run the repo’s existing catalog generation command. If no Make target exists, use the existing script referenced by prior commits and do not invent a new generator.

Run: `rg -n "mcp-tool-catalog|catalog" Makefile scripts docs -g '*.*'`

Expected: locate the existing catalog update path.

- [ ] **Step 2: Run focused MCP tests**

Run:

```bash
uv run pytest tests/unit/mcp tests/unit/test_mcp_errors.py tests/unit/test_search_shaping.py tests/unit/test_ncbi_discovery_service.py tests/unit/test_corpus_suggestion_service.py tests/unit/test_related_evidence_service.py tests/unit/test_pubtator_client_text_annotation.py -q
```

Expected: PASS.

- [ ] **Step 3: Run local CI**

Run:

```bash
make ci-local
```

Expected: formatting, lint, typecheck, loc lint, and tests all PASS.

- [ ] **Step 4: Rebuild and smoke local Docker**

Run:

```bash
make docker-build
make docker-down
make docker-up
curl -fsS http://127.0.0.1:8011/health
uv run python scripts/smoke_mcp_tool_surface.py --base-url http://127.0.0.1:8011
```

Expected: health returns `{"status":"healthy",...}` and smoke script reports `success:true` for each high-risk tool.

- [ ] **Step 5: Measure payload reduction**

Run a 10-call representative comparison with and without `include_meta=false` for search/retrieval/staging tools. Record total response bytes in the PR comment.

Expected: `include_meta=false` total bytes are at least 20% lower while preserving PMIDs, titles, citations, passage IDs, and coverage fields.

- [ ] **Step 6: Commit and update PR**

```bash
git add docs/mcp-tool-catalog.md
git commit -m "docs(mcp): refresh tool catalog for ergonomics wave"
git push
gh pr comment 44 --body-file /tmp/mcp-over-9-next-wave-verification.md
```

Expected: PR comment includes commit list, `make ci-local` output, Docker health, smoke output, and payload-reduction numbers.

---

## Plan Self-Review

- Spec coverage: each cross-cutting requirement maps to Tasks 1-3; each listed sub-9 tool maps to Tasks 4-7; catalog and verification map to Task 8.
- Placeholder scan: no task uses placeholder language; any unavailable generator must be discovered by `rg` before use.
- Type consistency: `query` and `pmid` are aliases, not replacements; canonical service calls continue to receive existing `text`, `question`, `topic`, or `pmids` values for each tool.
- File-size risk: new helper modules carry shared behavior so oversized grandfathered files do not absorb the whole wave.
