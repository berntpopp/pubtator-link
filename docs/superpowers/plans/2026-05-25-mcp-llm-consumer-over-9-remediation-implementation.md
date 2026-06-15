# MCP LLM Consumer Over 9 Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the live MCP regressions and payload-shaping issues identified in the Claude MCP test report so every advertised PubTator-Link MCP workflow is reliable and LLM-budgeted.

**Architecture:** Work from live reproductions inward: add focused failing tests for each reported regression, fix the nearest client/service/adapter layer, then add a bounded MCP smoke script to prevent recurrence. Keep public tool names stable and reuse existing response vocabulary such as `response_size_class`, `omitted_counts`, `next_commands`, and coverage fields.

**Tech Stack:** Python 3.11+, FastMCP, Pydantic, httpx, pytest, Ruff, mypy, uv, Makefile.

---

## Mandatory Reading

- `AGENTS.md` and `CLAUDE.md`, especially file-size discipline and `uv`/Makefile conventions.
- `.loc-allowlist`; do not grow grandfathered files past their ceiling.
- `pubtator_link/mcp/errors.py`
- `pubtator_link/services/ncbi_discovery.py`
- `pubtator_link/services/source_preflight.py`
- `pubtator_link/api/client.py`
- `pubtator_link/mcp/service_adapters.py`
- `pubtator_link/services/review_audit.py`
- `pubtator_link/mcp/tools/literature.py`
- `pubtator_link/mcp/tools/review/research.py`

## File Structure

- Modify: `pubtator_link/services/ncbi_discovery.py`
  - Make article ID conversion robust for mixed identifiers and per-ID upstream 400s.
  - Add relaxed citation fallback using PubTator/PubMed title search when ECitMatch misses.
- Modify: `pubtator_link/services/source_preflight.py`
  - Treat PubTator PMC BioC HTTP 400/not-found as `pmc_not_open_access` or abstract fallback, not fatal.
- Modify: `pubtator_link/api/client.py`
  - Parse text annotation session IDs from JSON `id`, legacy text `content`, and bytes bodies.
- Modify: `pubtator_link/mcp/service_adapters.py`
  - Add budgeted relation response shaping.
  - Honor quickstart `wait_until_ready`.
  - Add natural-language search query extraction warning for `ground_question`.
- Modify: `pubtator_link/mcp/tools/literature.py`
  - Add `limit`, `response_mode`, and `max_response_chars` to `find_entity_relations`.
- Modify: `pubtator_link/models/responses.py`
  - Add optional relation response budget metadata.
- Modify: `pubtator_link/services/review_audit.py`
  - Safely parse audit event payloads.
- Modify: `pubtator_link/mcp/errors.py`
  - Replace default stale-schema recovery with typed, tool-specific recovery.
- Modify: `pubtator_link/mcp/tools/review/research.py`
  - Keep quickstart schema honest and progress-aware.
- Create: `scripts/smoke_mcp_tool_surface.py`
  - Live local MCP smoke harness for the 43-tool high-risk subset.
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: `tests/unit/test_source_preflight.py`
- Test: `tests/unit/test_pubtator_client_text_annotation.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_review_audit_service.py`
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/integration/test_mcp_live_surface_contract.py`

---

### Task 1: Add Live Regression Smoke Harness

**Files:**
- Create: `scripts/smoke_mcp_tool_surface.py`
- Test: `tests/integration/test_mcp_live_surface_contract.py`

- [ ] **Step 1: Write the failing smoke-contract test**

Add `tests/integration/test_mcp_live_surface_contract.py`:

```python
from pathlib import Path


def test_live_surface_smoke_script_exists() -> None:
    script = Path("scripts/smoke_mcp_tool_surface.py")
    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "convert_article_ids" in text
    assert "find_entity_relations" in text
    assert "max_response_chars" in text
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/integration/test_mcp_live_surface_contract.py -q`

Expected: FAIL because the script does not exist.

- [ ] **Step 3: Create the smoke script**

Create `scripts/smoke_mcp_tool_surface.py` with:

```python
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


CALLS: list[tuple[str, dict[str, Any], int]] = [
    (
        "convert_article_ids",
        {"ids": ["24166952", "PMC12758588", "10.1038/s41431-022-01127-3"], "source": "auto"},
        12000,
    ),
    ("preflight_review_sources", {"pmids": ["24166952", "42135612"]}, 12000),
    (
        "submit_text_annotation",
        {
            "text": "Familial Mediterranean fever is associated with MEFV variants and colchicine.",
            "bioconcepts": "Gene,Disease,Chemical",
        },
        12000,
    ),
    (
        "find_entity_relations",
        {"entity_id": "@GENE_MEFV", "limit": 10, "response_mode": "compact", "max_response_chars": 12000},
        12000,
    ),
    ("export_review_audit_bundle", {"review_id": "mefv-vus-smoke", "fallback_inline": True}, 20000),
]


def call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = httpx.post(
        f"{base_url.rstrip('/')}/mcp",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": name,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        timeout=60,
    )
    response.raise_for_status()
    envelope = response.json()
    if "error" in envelope:
        return {"success": False, "transport_error": envelope["error"]}
    text = envelope["result"]["content"][0]["text"]
    payload = json.loads(text)
    payload["_response_chars"] = len(text)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    args = parser.parse_args()

    failed = False
    for name, arguments, max_chars in CALLS:
        payload = call_tool(args.base_url, name, arguments)
        summary = {
            "tool": name,
            "success": payload.get("success"),
            "error_code": payload.get("error_code"),
            "response_chars": payload.get("_response_chars"),
        }
        print(json.dumps(summary, sort_keys=True))
        if payload.get("success") is not True or int(payload.get("_response_chars") or 0) > max_chars:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/integration/test_mcp_live_surface_contract.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_mcp_tool_surface.py tests/integration/test_mcp_live_surface_contract.py
git commit -m "test(mcp): add live tool surface smoke harness"
```

---

### Task 2: Robust Mixed Article ID Conversion

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Write failing tests**

Add tests covering a mixed batch where the combined request raises `httpx.HTTPStatusError`
but per-ID requests succeed for resolvable IDs and mark only the DOI unresolved.

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_ncbi_discovery_service.py -q -k "convert_article_ids"`

Expected: FAIL on mixed-batch fallback.

- [ ] **Step 3: Implement per-ID fallback**

In `NcbiDiscoveryClient.convert_article_ids`, catch `httpx.HTTPStatusError` for the
batch request. Retry each requested identifier individually, preserving order. If an
individual request also fails with 400, return an `ArticleIdConversionRecord` with
`status="failed"` and `reason="upstream_rejected_identifier"` for that input.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q -k "convert_article_ids"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/ncbi_discovery.py tests/unit/test_ncbi_discovery_service.py
git commit -m "fix(discovery): tolerate mixed article id conversion batches"
```

---

### Task 3: Preflight PMC Probe Degradation

**Files:**
- Modify: `pubtator_link/services/source_preflight.py`
- Test: `tests/unit/test_source_preflight.py`

- [ ] **Step 1: Write failing test**

Add a test where ID conversion returns a PMCID, the PMC BioC probe raises a
PubTator API 400/not-found error, and the abstract probe succeeds. Assert the
result is `expected_coverage="abstract_only"` with a resolver attempt showing
PMC probe unavailable.

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/unit/test_source_preflight.py -q`

Expected: FAIL because the PubTator API exception aborts preflight.

- [ ] **Step 3: Implement degradation**

Catch PubTator API 400/not-retrievable failures around `_pmc_bioc_available`.
Record a failed `pmc_bioc` resolver attempt and continue to Europe PMC and
abstract probes.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_source_preflight.py -q
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q -k preflight
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/source_preflight.py tests/unit/test_source_preflight.py
git commit -m "fix(preflight): degrade unavailable PMC probes to abstract coverage"
```

---

### Task 4: Text Annotation Session ID Parsing

**Files:**
- Modify: `pubtator_link/api/client.py`
- Test: `tests/unit/test_pubtator_client_text_annotation.py`

- [ ] **Step 1: Write failing tests**

Add tests for three upstream response shapes:

- `{"id":"632A7A61D4B815989FB2"}`
- `{"content":"632A7A61D4B815989FB2"}`
- `{"content": b"632A7A61D4B815989FB2"}`

Each must return the session ID string.

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_pubtator_client_text_annotation.py -q`

Expected: FAIL for JSON `id`.

- [ ] **Step 3: Implement parser**

Add a private helper near `submit_text_annotation`:

```python
def _text_annotation_session_id(response: dict[str, Any]) -> str:
    candidate = response.get("id", response.get("content", ""))
    if isinstance(candidate, bytes):
        candidate = candidate.decode("utf-8", errors="replace")
    return str(candidate).strip()
```

Use this helper in `submit_text_annotation`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_pubtator_client_text_annotation.py tests/unit/mcp/test_mcp_service_adapters.py -q -k "text_annotation or submit_text_annotation"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/api/client.py tests/unit/test_pubtator_client_text_annotation.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "fix(client): parse text annotation JSON session ids"
```

---

### Task 5: Audit Bundle Payload Tolerance

**Files:**
- Modify: `pubtator_link/services/review_audit.py`
- Test: `tests/unit/test_review_audit_service.py`

- [ ] **Step 1: Write failing test**

Add a test where `list_review_audit_events` returns events with payload values
`"not-json"`, `["bad"]`, and a valid JSON object string. Assert export does not
raise, ignores malformed payloads, and parses the JSON object string.

- [ ] **Step 2: Run failing test**

Run: `uv run pytest tests/unit/test_review_audit_service.py -q`

Expected: FAIL with `ValueError` from `dict(...)`.

- [ ] **Step 3: Implement safe payload parser**

Add:

```python
def _event_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}
```

Use `_event_payload(event.get("payload"))` in `_runs_from_events`.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_review_audit_service.py tests/unit/mcp/test_mcp_service_adapters.py -q -k "audit_bundle or audit"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/review_audit.py tests/unit/test_review_audit_service.py
git commit -m "fix(audit): tolerate malformed recorded event payloads"
```

---

### Task 6: Budget `find_entity_relations`

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/models/responses.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing schema and adapter tests**

Assert `find_entity_relations` exposes:

- `limit` with default 20 and max 100
- `response_mode` enum `compact|standard|full`
- `max_response_chars` default 12000

Assert compact mode returns no more than `limit` entities and includes
`omitted_count` and `response_size_class`.

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q -k find_entity_relations
```

Expected: FAIL because the schema and adapter do not expose budget controls.

- [ ] **Step 3: Implement budget controls**

Add keyword args to `find_entity_relations_impl` and tool registration:

```python
limit: int = 20
response_mode: Literal["compact", "standard", "full"] = "compact"
max_response_chars: int = 12000
```

Sort or preserve upstream order, slice to `limit`, omit heavy fields such as
large PMID lists in compact mode, and include:

```python
"omitted_count": max(0, len(related_entities) - len(emitted_entities)),
"response_size_class": "compact" if serialized_chars <= max_response_chars else "truncated",
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q -k find_entity_relations
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/tools/literature.py pubtator_link/mcp/service_adapters.py pubtator_link/models/responses.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "fix(mcp): add budget controls to entity relations"
```

---

### Task 7: Error Recovery Taxonomy

**Files:**
- Modify: `pubtator_link/mcp/errors.py`
- Test: `tests/unit/test_mcp_errors.py`

- [ ] **Step 1: Write failing tests**

Add tests proving generic `RuntimeError` no longer says "review schema is
stale", while `ReviewSchemaStaleError` still does. Add tool-specific recovery
for `convert_article_ids`, `submit_text_annotation`, and
`export_review_audit_bundle`.

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/unit/test_mcp_errors.py -q`

Expected: FAIL because the default recovery still points to stale schema.

- [ ] **Step 3: Implement specific recovery text**

Keep stale-schema recovery only for `review_schema_not_current`. For unknown
internal errors use:

```text
Inspect recent_mcp_errors in diagnostics and retry with the documented fallback if available.
```

For discovery/text/audit tools, include direct retry/fallback guidance.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_mcp_errors.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/errors.py tests/unit/test_mcp_errors.py
git commit -m "fix(mcp): make generic tool recovery diagnosis-specific"
```

---

### Task 8: Honor `review_quickstart.wait_until_ready`

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review/research.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing test**

Add a quickstart adapter test where `wait_until_ready=True` and `timeout_ms>0`.
Assert the indexing service is called with `wait_for_completion=True` and
`wait_for_status="complete_or_partial"`, and the response does not include
`quickstart does not block on indexing`.

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q -k quickstart
```

Expected: FAIL because quickstart currently warns that it does not block.

- [ ] **Step 3: Implement blocking path**

Mirror the `ground_question_impl` indexing path: when `wait_until_ready` is true,
pass `wait_for_completion=True`, `wait_for_status="complete_or_partial"`, and
`timeout_ms` to indexing. Preserve non-blocking behavior when the flag is false.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q -k "quickstart or index_review"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/review/research.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "fix(mcp): honor quickstart wait_until_ready"
```

---

### Task 9: Search and Grounding Token Economy

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/models/search.py` or current search response model file
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing tests**

Assert compact `search_literature` omits null/empty optional fields where the
schema allows it, `metadata="with_abstract"` returns bounded abstract snippets,
and `ground_question` returns `query_length_warning` or uses a derived short
query for natural-language inputs over 18 words.

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "search_literature or ground_question"
```

Expected: FAIL because compact search still leaks nulls and ground question has
no explicit long-query handling.

- [ ] **Step 3: Implement compact shaping**

Use `model_dump(exclude_none=True)` and targeted `exclude_defaults` only for
compact mode. Keep standard/full modes backward-compatible. Add bounded abstract
snippet support as a new metadata mode only if the existing model can express it
without breaking clients.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py -q -k "search_literature or ground_question"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools/literature.py pubtator_link/models tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat(mcp): slim compact search and guide long questions"
```

---

### Task 10: Discovery Quality Follow-Ups

**Files:**
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: corpus suggestion and guideline search service files found with `rg`
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: relevant corpus/guideline service tests

- [ ] **Step 1: Write failing characterization tests**

Cover:

- `search_guidelines("familial Mediterranean fever colchicine pediatric")`
  returns at least one EULAR/PRES-like recommendation candidate by relaxing
  publication-type filtering.
- `lookup_citation` falls back from ECitMatch miss to title/PubMed search.
- `find_related_articles(include_metadata=True)` can return title/journal/year.
- `suggest_corpus` boosts entity overlap and demotes candidates lacking
  MEFV/FMF/pediatric/treatment signals.

- [ ] **Step 2: Run failing tests**

Run the focused service tests identified by `rg "search_guidelines|suggest_corpus|lookup_citation|find_related_articles" tests -n`.

Expected: FAIL on at least the new quality cases.

- [ ] **Step 3: Implement ranking and fallback improvements**

Prefer existing metadata/search services. Do not add an LLM dependency. Blend:

- lexical score
- entity overlap
- publication type/guideline hints
- year recency
- title/abstract phrase match

- [ ] **Step 4: Verify**

Run focused discovery/corpus tests and:

```bash
uv run pytest tests/unit/test_ncbi_discovery_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services tests/unit
git commit -m "fix(discovery): improve guideline citation and corpus candidate quality"
```

---

### Task 11: State Sync and Pagination

**Files:**
- Modify: research session service/repository files found with `rg "ResearchSession" pubtator_link/services pubtator_link/repositories -n`
- Modify: `pubtator_link/mcp/tools/review/research.py`
- Test: existing research session tests

- [ ] **Step 1: Write failing tests**

Assert `get_research_session_status` and `list_research_sessions` derive
candidate status from the review index when source indexing has completed.
Assert list supports bounded candidate output or pagination metadata.

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit -q -k "research_session"
```

Expected: FAIL on status derivation/pagination.

- [ ] **Step 3: Implement read-time reconciliation**

At read time, join session candidate PMIDs to review index source status. Do not
rewrite manifests unless there is already an established repository method for
that update.

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit -q -k "research_session or review_index"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link tests/unit
git commit -m "fix(review): reconcile research session status from review index"
```

---

### Task 12: Final Verification

**Files:**
- Modify only if verification reveals a defect.

- [ ] **Step 1: Run formatting and static checks**

Run:

```bash
make format
make lint
make typecheck
make lint-loc
```

Expected: PASS.

- [ ] **Step 2: Run full local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

- [ ] **Step 3: Rebuild local Docker and run live smoke**

Run:

```bash
make docker-build
make docker-down
make docker-up
curl -fsS http://127.0.0.1:8011/health
uv run python scripts/smoke_mcp_tool_surface.py --base-url http://127.0.0.1:8011
```

Expected: health returns `healthy`; smoke script exits 0 and every line has
`"success": true` with response sizes below caps.

- [ ] **Step 4: Commit verification-only changes if needed**

Only commit if Step 1-3 required code edits.

```bash
git status --short
git commit -m "fix(mcp): address final over-9 verification issues"
```

