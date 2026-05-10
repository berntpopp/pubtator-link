# MCP Experience Over 9 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise every measured LLM MCP-consumer experience dimension above 9.0 while preserving deterministic benchmark separation between scoring and diagnostics.

**Architecture:** Improve the MCP at the source of the sub-9 ratings: actionable tool errors, clearer coverage states, safer passage retrieval defaults, full-text-specific benchmark coverage, and richer benchmark reporting. Keep deterministic answer scoring separate from LLM self-assessment and judge diagnostics; use ignored raw artifacts only for local run evidence.

**Tech Stack:** Python 3.11+, FastMCP, Pydantic, Ruff, mypy, uv, pytest, existing benchmark scripts and YAML configs.

---

## Evidence From Runs

### 51-Case PubMedQA Delta

| Dimension | Mean Rating | Target |
| --- | ---: | ---: |
| context_size_control | 8.41 | >9.0 |
| latency | 8.25 | >9.0 |
| context_quality | 8.22 | >9.0 |
| workflow_ergonomics | 8.08 | >9.0 |
| tool_discoverability | 8.00 | >9.0 |
| citation_support | 7.65 | >9.0 |
| error_recovery | 6.78 | >9.0 |

### 10-Case Smoke Findings To Preserve

- `get_publication_passages` returned clean passage structures with PMIDs, passage IDs, and sections.
- Citation discipline worked: 10/10 retrieved PMIDs and 10/10 cited PMIDs.
- Context size control was already good, but not above target.
- Abstract fallback was clear when preflight succeeded.
- `preflight_review_sources` failed with `internal_error` on 2/10 cases.
- Recovery was manual: Claude had to infer that it should call `get_publication_passages` directly.
- All smoke cases were `abstract_only`, so full-text value was not tested.
- One abstract was truncated by default `max_passages_per_pmid=6`; the model needed a second call.
- Error recovery was the weakest smoke rating at 6.5/10.
- Minor schema discovery friction appeared once.
- One abstract contained HTML entity noise like `&lt;`.

## Acceptance Criteria

- Every MCP experience dimension in the default focused diagnostic report is greater than 9.0:
  - `tool_discoverability`
  - `context_quality`
  - `context_size_control`
  - `citation_support`
  - `latency`
  - `error_recovery`
  - `workflow_ergonomics`
- Full-text benchmark coverage is visible separately from abstract-only coverage.
- `preflight_review_sources` errors include an actionable fallback command to `pubtator_get_publication_passages`.
- Article-local PubMedQA retrieval can request all title and abstract passages without guessing passage limits.
- Reports show source coverage counts and decisive-overcall rate on gold `maybe` cases.
- Raw benchmark outputs remain ignored under `benchmarks/results/` and `benchmarks/logs/`.

## File Structure

- Modify: `pubtator_link/mcp/errors.py`
  - Add review-preflight-specific fallback behavior and recovery text.
- Modify: `pubtator_link/mcp/tools/review.py`
  - Pass explicit fallback metadata into `run_mcp_tool` for `pubtator_preflight_review_sources`.
- Modify: `pubtator_link/mcp/tools/publications.py`
  - Improve `get_publication_passages` description and expose `full_abstract` mode.
- Modify: `pubtator_link/models/publication_passages.py`
  - Add `full_abstract` to `PublicationPassageMode`; add optional response fields for source coverage clarity if needed.
- Modify: `pubtator_link/services/publication_passage_service.py`
  - Implement `full_abstract` mode, HTML entity cleanup, and clearer abstract/full-text coverage warnings.
- Modify: `pubtator_link/models/review_rerag.py`
  - Add coverage reasons or metadata fields only if existing values cannot express `abstract_only`, `not_open_access`, and `fallback_recommended` cleanly.
- Modify: `pubtator_link/services/source_preflight.py`
  - Ensure no-PMC/abstract-available cases get explicit `abstract_only` coverage with moderate or high confidence.
- Modify: `scripts/analyze_focused_benchmark.py`
  - Add source coverage counts, decisive-overcall rate on gold `maybe`, and rating-threshold summary.
- Modify: `pubtator_link/benchmarks/summaries.py`
  - Surface source coverage counts prominently in generated benchmark summaries.
- Create: `benchmarks/cases/pubmedqa/full_text_smoke.jsonl`
  - Small, hand-vetted full-text-available PubMedQA-like diagnostic set without gold labels in prompts.
- Create: `benchmarks/suites/pubmedqa_full_text_smoke.yaml`
  - Suite metadata for the full-text smoke.
- Modify: `benchmarks/configs/focused_default.yaml`
  - Add optional non-default full-text smoke runs or document a separate full-text config if default runtime is too high.
- Modify: `benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md`
  - Mention `full_abstract` and explicit fallback workflow.
- Test: `tests/unit/test_mcp_errors.py`
- Test: `tests/unit/test_publication_passage_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/benchmarks/test_summaries.py`
- Test: `tests/unit/benchmarks/test_scoring_pubmedqa.py`

---

### Task 1: Preflight Error Recovery That Models Can Act On

**Files:**
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/errors.py`
- Test: `tests/unit/test_mcp_errors.py`

- [ ] **Step 1: Write the failing test for preflight fallback**

Add this test to `tests/unit/test_mcp_errors.py`:

```python
def test_preflight_review_sources_error_points_to_publication_passages() -> None:
    error = mcp_tool_error(
        RuntimeError("temporary preflight failure"),
        McpErrorContext(
            tool_name="pubtator_preflight_review_sources",
            pmids=["10490564", "10927144"],
        ),
    )

    payload = json.loads(str(error))

    assert payload["error_code"] == "internal_error"
    assert payload["fallback_tool"] == "pubtator_get_publication_passages"
    assert payload["fallback_args"] == {
        "pmids": ["10490564", "10927144"],
        "mode": "full_abstract",
    }
    assert payload["recovery"] == (
        "Call pubtator_get_publication_passages with the same PMIDs. "
        "Use mode='full_abstract' for article-local answering; run diagnostics only if "
        "passage retrieval also fails."
    )
    assert payload["_meta"]["next_commands"][0] == {
        "tool": "pubtator_get_publication_passages",
        "arguments": {
            "pmids": ["10490564", "10927144"],
            "mode": "full_abstract",
        },
    }
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py::test_preflight_review_sources_error_points_to_publication_passages -q
```

Expected: FAIL because preflight errors currently do not get publication-passage fallback metadata.

- [ ] **Step 3: Implement fallback selection**

In `pubtator_link/mcp/errors.py`, update `_fallback_for_context` to include preflight:

```python
    if context.tool_name == "pubtator_preflight_review_sources" and context.pmids:
        return (
            "pubtator_get_publication_passages",
            {"pmids": context.pmids, "mode": "full_abstract"},
        )
```

Add this helper:

```python
def _recovery_text_for_context(context: McpErrorContext, fallback_tool: str | None) -> str:
    if context.tool_name == "pubtator_preflight_review_sources" and fallback_tool:
        return (
            "Call pubtator_get_publication_passages with the same PMIDs. "
            "Use mode='full_abstract' for article-local answering; run diagnostics only if "
            "passage retrieval also fails."
        )
    return (
        "Run pubtator_diagnostics. If the review schema is stale, apply database migrations "
        "and retry."
    )
```

Replace the current static `payload["recovery"]` assignment with:

```python
        "recovery": _recovery_text_for_context(context, fallback_tool),
```

- [ ] **Step 4: Pass explicit fallback from the MCP tool wrapper**

In `pubtator_link/mcp/tools/review.py`, update `preflight_review_sources`:

```python
        return await run_mcp_tool(
            "pubtator_preflight_review_sources",
            call,
            pmids=pmids,
            fallback_tool="pubtator_get_publication_passages",
            fallback_args={"pmids": pmids, "mode": "full_abstract"},
        )
```

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py -q
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_preflight_review_sources_adapter_returns_hints -q
```

Expected: PASS.

---

### Task 2: Add `full_abstract` Mode To Prevent Abstract Truncation

**Files:**
- Modify: `pubtator_link/models/publication_passages.py`
- Modify: `pubtator_link/services/publication_passage_service.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/publications.py`
- Test: `tests/unit/test_publication_passage_service.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write the failing service test**

Add this fixture and test to `tests/unit/test_publication_passage_service.py`:

```python
class LongStructuredAbstractService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "documents": [
                {
                    "id": "15053041",
                    "passages": [
                        {"infons": {"section_type": "TITLE"}, "text": "Aortic stiffness title"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Background"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Methods"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Results"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Conclusion"},
                        {"infons": {"section_type": "METHODS"}, "text": "Full text methods"},
                    ],
                }
            ]
        }


@pytest.mark.asyncio
async def test_full_abstract_mode_returns_all_title_and_abstract_passages() -> None:
    service = PublicationPassageService(LongStructuredAbstractService())

    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["15053041"],
            mode="full_abstract",
            max_passages_per_pmid=2,
        )
    )

    assert [passage.text for passage in response.passages] == [
        "Aortic stiffness title",
        "Background",
        "Methods",
        "Results",
        "Conclusion",
    ]
    assert all(passage.section in {"title", "abstract"} for passage in response.passages)
    assert not any(drop.reason == "max_passages_per_pmid_exceeded" for drop in response.dropped)
    assert any(drop.reason == "section_filtered" and drop.section == "methods" for drop in response.dropped)
    assert response.context_estimate.recommended_mode == "full_abstract"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py::test_full_abstract_mode_returns_all_title_and_abstract_passages -q
```

Expected: FAIL because `full_abstract` is not a valid mode.

- [ ] **Step 3: Extend the model type**

In `pubtator_link/models/publication_passages.py`, change:

```python
PublicationPassageMode = Literal["abstracts", "compact_passages", "section_text"]
```

to:

```python
PublicationPassageMode = Literal["abstracts", "full_abstract", "compact_passages", "section_text"]
```

- [ ] **Step 4: Implement mode semantics**

In `pubtator_link/services/publication_passage_service.py`, update `_effective_sections`:

```python
    @staticmethod
    def _effective_sections(mode: PublicationPassageMode, sections: list[str]) -> list[str]:
        if mode in {"abstracts", "full_abstract"} and not sections:
            return ["title", "abstract"]
        return sections
```

Update the max-passage call in `get_passages`:

```python
        passages, dropped = self._compact_export(
            export_data=export_data,
            pmids=request.pmids,
            source=source,
            sections=self._effective_sections(request.mode, request.sections),
            include_tables=request.include_tables,
            include_references=request.include_references,
            max_passages_per_pmid=self._effective_max_passages_per_pmid(request),
        )
```

Add:

```python
    @staticmethod
    def _effective_max_passages_per_pmid(request: PublicationPassageRequest) -> int:
        if request.mode == "full_abstract":
            return 30
        return request.max_passages_per_pmid
```

Apply the same `_effective_max_passages_per_pmid(request)` call in `estimate_context`.

- [ ] **Step 5: Update MCP description**

In `pubtator_link/mcp/tools/publications.py`, update the docstring for `get_publication_passages`:

```python
        """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. For article-local question answering, use mode='full_abstract' first; it returns all title/abstract passages without truncating structured abstracts. If full=True returns only abstracts, inspect coverage_by_pmid and answer from available evidence. Do not use this for prepared review RAG; use pubtator_retrieve_review_context_batch."""
```

- [ ] **Step 6: Verify**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py -q
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_publication_passages_adapter_builds_request_from_flat_args -q
```

Expected: PASS.

---

### Task 3: Clean Abstract Text For LLM Consumption

**Files:**
- Modify: `pubtator_link/services/publication_passage_service.py`
- Test: `tests/unit/test_publication_passage_service.py`

- [ ] **Step 1: Write the failing HTML entity test**

Add this test to `tests/unit/test_publication_passage_service.py`:

```python
@pytest.mark.asyncio
async def test_publication_passages_unescapes_html_entities() -> None:
    class HtmlEntityPublicationService:
        async def export_publications_list(self, pmids: list[str], format: str, full: bool):
            return {
                "documents": [
                    {
                        "id": "11978239",
                        "passages": [
                            {
                                "infons": {"section_type": "ABSTRACT"},
                                "text": "p &lt; 0.05 and CRP &amp; fibrinogen improved.",
                            }
                        ],
                    }
                ]
            }

    service = PublicationPassageService(HtmlEntityPublicationService())
    response = await service.get_passages(PublicationPassageRequest(pmids=["11978239"]))

    assert response.passages[0].text == "p < 0.05 and CRP & fibrinogen improved."
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py::test_publication_passages_unescapes_html_entities -q
```

Expected: FAIL because entity text is currently passed through unchanged.

- [ ] **Step 3: Implement text cleanup**

In `pubtator_link/services/publication_passage_service.py`, import:

```python
from html import unescape
```

Update text extraction inside `_compact_export`:

```python
                text = _string_or_none(raw_passage.get("text"))
                if not text:
                    continue
                text = unescape(text)
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_publication_passage_service.py -q
```

Expected: PASS.

---

### Task 4: Make Source Coverage States Explicit And Less Vague

**Files:**
- Modify: `pubtator_link/services/source_preflight.py`
- Modify: `pubtator_link/models/review_rerag.py` only if a missing enum value blocks explicit reporting.
- Test: `tests/unit/test_review_context_diagnostics.py` or create focused tests in `tests/unit/test_source_preflight.py` if that file already exists locally.

- [ ] **Step 1: Write failing tests for explicit abstract-only coverage**

Create `tests/unit/test_source_preflight.py` if it does not exist:

```python
import pytest

from pubtator_link.services.source_preflight import SourcePreflightService


@pytest.mark.asyncio
async def test_preflight_reports_abstract_only_with_actionable_confidence() -> None:
    async def id_converter(_pmid: str):
        return {"id_resolution_status": "unresolved", "id_resolution_reason": "no_pmcid"}

    async def abstract_available(_pmid: str) -> bool:
        return True

    service = SourcePreflightService(
        id_converter=id_converter,
        pubtator_abstract_available=abstract_available,
    )

    [hint] = await service.preflight_pmids(["15053041"])

    assert hint.expected_coverage == "abstract_only"
    assert hint.expected_coverage_after_index == "abstract_only"
    assert hint.expected_coverage_confidence == "moderate"
    assert hint.coverage_resolution_stage == "preflight_resolver_chain"
    assert hint.coverage_reason in {"no_pmcid", "abstract_fallback_used"}
    assert hint.pmc_fallback_available is False
```

Add a second test:

```python
@pytest.mark.asyncio
async def test_preflight_timeout_recommends_passage_fallback() -> None:
    async def id_converter(_pmid: str):
        raise TimeoutError("converter timed out")

    service = SourcePreflightService(id_converter=id_converter)

    [hint] = await service.preflight_pmids(["15053041"])

    assert hint.expected_coverage == "unknown"
    assert hint.coverage_reason == "upstream_timeout"
    assert hint.resolver_attempts[0].terminal_reason == "upstream_timeout"
```

- [ ] **Step 2: Run the focused tests**

Run:

```bash
uv run pytest tests/unit/test_source_preflight.py -q
```

Expected: first test may already pass partly; failures identify which fields remain vague.

- [ ] **Step 3: Implement explicit coverage behavior**

In `pubtator_link/services/source_preflight.py`, keep successful abstract probes explicit. If the failure is only due to `coverage_reason`, prefer `no_pmcid` when the converter says no PMCID and `abstract_fallback_used` when a PMCID exists but full text was not available.

Use this branch shape:

```python
        try:
            if await self._pubtator_abstract_available(pmid):
                coverage_reason: CoverageReason = "abstract_fallback_used" if pmcid else "no_pmcid"
                if id_resolution_failed and not pmcid:
                    coverage_reason = "pre_resolution_best_guess"
                return SourceCoverageHint(
                    pmid=pmid,
                    expected_coverage="abstract_only",
                    expected_coverage_after_index="abstract_only",
                    expected_coverage_confidence="moderate",
                    coverage_resolution_stage="preflight_resolver_chain",
                    coverage_reason=coverage_reason,
                    pmcid=pmcid,
                    doi=doi,
                    license_or_access_hint=license_or_access_hint,
                    pmc_fallback_available=False,
                    notes=best_guess_notes,
                    resolver_attempts=[
                        *id_resolution_attempts,
                        ResolverAttemptSummary(
                            source_kind="pubtator_abstract",
                            status="success",
                            pmid=pmid,
                            pmcid=pmcid,
                            doi=doi,
                        ),
                    ],
                )
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/test_source_preflight.py -q
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py::test_preflight_review_sources_adapter_returns_hints -q
```

Expected: PASS.

---

### Task 5: Add Full-Text Smoke Suite

**Files:**
- Create: `benchmarks/cases/pubmedqa/full_text_smoke.jsonl`
- Create: `benchmarks/suites/pubmedqa_full_text_smoke.yaml`
- Modify: `benchmarks/configs/focused_default.yaml` or create `benchmarks/configs/focused_full_text_smoke.yaml`
- Test: `tests/unit/benchmarks/test_cases.py`

- [ ] **Step 1: Identify candidate PMIDs with full text**

Run this local probe using the existing MCP-adjacent service through the benchmark runner only if network is available:

```bash
uv run python - <<'PY'
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("benchmarks/cases/pubmedqa/pqa_l_full_1000.jsonl").read_text().splitlines()]
for row in rows:
    metadata = row.get("case_metadata", {})
    pmid = metadata.get("source_pmid") or (row.get("target_pmids") or [""])[0]
    if pmid:
        print(pmid, row["gold_label"], row["question"])
PY
```

Then use a short live preflight/manual check to select 12 cases that expose full text. Keep labels balanced where possible: 4 yes, 4 no, 4 maybe.

- [ ] **Step 2: Create the JSONL case file**

Write `benchmarks/cases/pubmedqa/full_text_smoke.jsonl` with 12 rows copied from `pqa_l_full_1000.jsonl`, preserving:

```json
{"case_id":"pubmedqa_full_text_001","dataset":"pubmedqa","dataset_version":"pqa_l_full_text_smoke_12_v1","question":"...","target_pmids":["..."],"gold_evidence_pmids":["..."],"gold_label":"yes","gold_answer":{"long_answer":"..."},"case_metadata":{"abstract_context":"...","source_pmid":"...","focused_source_case_id":"...","full_text_expected":true}}
```

Do not render `gold_label` or `gold_answer` into answer prompts. The existing `_prompt_payload` must continue to exclude both.

- [ ] **Step 3: Create the suite YAML**

Create `benchmarks/suites/pubmedqa_full_text_smoke.yaml`:

```yaml
name: pubmedqa_full_text_smoke
dataset: pubmedqa
dataset_version: pqa_l_full_text_smoke_12_v1
case_file: benchmarks/cases/pubmedqa/full_text_smoke.jsonl
modes:
  - no_tools
  - mcp_oracle_pmid
sample_seed: 20260509
case_count: 12
sampling_mode: full_text_smoke_balanced
prompt_versions:
  answer: benchmarks/prompts/provider_pubmedqa_single_v4.md
defaults:
  timeout_s: 240
  max_cases_per_run: 12
```

- [ ] **Step 4: Add config entries**

Create `benchmarks/configs/focused_full_text_smoke.yaml`:

```yaml
name: focused_full_text_smoke
artifact_root: benchmarks/results/focused_full_text_smoke
report_path: benchmarks/reports/focused-full-text-smoke-report.md
analysis:
  title: Focused Full-Text Smoke Report
  slowest_case_count: 5
runs:
  - run_name: pubmedqa_full_text_smoke_claude
    suite: benchmarks/suites/pubmedqa_full_text_smoke.yaml
    mode: no_tools
    provider: claude
    model: sonnet
    max_cases: 12
    timeout_s: 180
    prompt: benchmarks/prompts/provider_pubmedqa_single_v4.md
    prompt_version: pubmedqa_no_tools_v4_context_policy
    tool_workflow: none
  - run_name: pubmedqa_full_text_smoke_claude_mcp
    suite: benchmarks/suites/pubmedqa_full_text_smoke.yaml
    mode: mcp_oracle_pmid
    provider: claude
    model: sonnet
    max_cases: 12
    timeout_s: 300
    prompt: benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md
    prompt_version: pubmedqa_mcp_article_local_v1
    tool_workflow: preflight_review_sources>get_publication_passages
```

- [ ] **Step 5: Verify case loading**

Run:

```bash
uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_full_text_smoke.yaml --answer-stack dry_run:deterministic --no-db --dry-run
uv run pytest tests/unit/benchmarks/test_cases.py -q
```

Expected: PASS, no DB required.

---

### Task 6: Surface Source Coverage And Maybe Overcall Diagnostics

**Files:**
- Modify: `scripts/analyze_focused_benchmark.py`
- Modify: `pubtator_link/benchmarks/scoring.py`
- Test: `tests/unit/benchmarks/test_scoring_pubmedqa.py`
- Test: create or modify `tests/unit/benchmarks/test_focused_analysis.py` if script-level tests exist; otherwise add focused helpers to `tests/unit/benchmarks/test_single_case_provider_script.py`.

- [ ] **Step 1: Write failing PubMedQA scoring test**

Add to `tests/unit/benchmarks/test_scoring_pubmedqa.py`:

```python
def test_pubmedqa_scores_decisive_overcall_rate_for_maybe_cases() -> None:
    cases = [
        BenchmarkCase(case_id="c1", dataset="pubmedqa", question="q", gold_label="maybe"),
        BenchmarkCase(case_id="c2", dataset="pubmedqa", question="q", gold_label="maybe"),
        BenchmarkCase(case_id="c3", dataset="pubmedqa", question="q", gold_label="yes"),
    ]
    predictions = [
        PredictionRecord(case_id="c1", predicted_label="yes"),
        PredictionRecord(case_id="c2", predicted_label="maybe"),
        PredictionRecord(case_id="c3", predicted_label="yes"),
    ]

    score = score_pubmedqa(cases, predictions, mode="mcp_oracle_pmid")

    assert score.score_details["maybe_decisive_overcall_count"] == 1
    assert score.score_details["maybe_decisive_overcall_rate"] == 0.5
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_scoring_pubmedqa.py::test_pubmedqa_scores_decisive_overcall_rate_for_maybe_cases -q
```

Expected: FAIL because the metric does not exist.

- [ ] **Step 3: Implement scoring metric**

In `pubtator_link/benchmarks/scoring.py`, inside `score_pubmedqa`, compute:

```python
    maybe_cases = [case for case in cases if case.gold_label == "maybe"]
    maybe_decisive_overcalls = sum(
        1
        for case in maybe_cases
        if predictions_by_case_id.get(case.case_id).predicted_label in {"yes", "no"}
    )
    maybe_decisive_overcall_rate = (
        maybe_decisive_overcalls / len(maybe_cases) if maybe_cases else 0.0
    )
```

Add to `score_details`:

```python
        "maybe_decisive_overcall_count": maybe_decisive_overcalls,
        "maybe_decisive_overcall_rate": maybe_decisive_overcall_rate,
```

Use the existing local variable names from `score_pubmedqa`; do not duplicate prediction parsing.

- [ ] **Step 4: Add focused report fields**

In `scripts/analyze_focused_benchmark.py`, add these report lines under PubMedQA class details or No-MCP vs MCP deltas:

```python
    details = scores.get("score_details", {})
    if "maybe_decisive_overcall_rate" in details:
        lines.append(
            f"- maybe decisive-overcall rate: {float(details['maybe_decisive_overcall_rate']):.3f}"
        )
```

Keep this diagnostic separate from deterministic macro F1 and accuracy.

- [ ] **Step 5: Verify**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_scoring_pubmedqa.py -q
uv run python scripts/analyze_focused_benchmark.py --artifact-root benchmarks/results/focused_51_delta --output benchmarks/reports/focused-51-delta-report.md --title "Focused 51-Case MCP Delta Report"
```

Expected: PASS and report includes decisive-overcall rate.

---

### Task 7: Make Source Coverage Counts Prominent In Summaries

**Files:**
- Modify: `pubtator_link/benchmarks/summaries.py`
- Modify: `scripts/analyze_focused_benchmark.py`
- Test: `tests/unit/benchmarks/test_summaries.py`

- [ ] **Step 1: Write failing summary test**

Add to `tests/unit/benchmarks/test_summaries.py`:

```python
def test_summary_highlights_source_coverage_counts_before_scores() -> None:
    run = RunMetadata(
        run_id="run-coverage",
        suite="pubmedqa_full_text_smoke",
        dataset="pubmedqa",
        mode="mcp_oracle_pmid",
        sample_seed=20260509,
    )
    scores = BenchmarkScore(
        dataset="pubmedqa",
        accuracy=0.75,
        macro_f1=0.74,
        gold_source_access_rate={"full_text": 0.5, "abstract_only": 0.5},
        score_details={"source_access_counts": {"full_text": 6, "abstract_only": 6}},
    )
    analysis = analyze_events([])

    text = render_summary(run, scores, analysis)

    assert text.index("## Source Coverage Counts") < text.index("## Label Metrics")
    assert "- full_text: 6" in text
    assert "- abstract_only: 6" in text
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_summaries.py::test_summary_highlights_source_coverage_counts_before_scores -q
```

Expected: FAIL because coverage counts are not rendered before scores.

- [ ] **Step 3: Implement summary rendering**

In `pubtator_link/benchmarks/summaries.py`, after the initial run metadata block and before `Label Metrics`, add:

```python
    source_access_counts = scores.score_details.get("source_access_counts")
    if isinstance(source_access_counts, dict) and source_access_counts:
        lines.extend(["## Source Coverage Counts"])
        for key, value in sorted(source_access_counts.items()):
            lines.append(f"- {key}: {value}")
        lines.append("")
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_summaries.py -q
```

Expected: PASS.

---

### Task 8: Update MCP Benchmark Prompt For Better Calibration

**Files:**
- Modify: `benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md`
- Test: `tests/unit/benchmarks/test_prompts.py`

- [ ] **Step 1: Write prompt regression test**

Add a test to `tests/unit/benchmarks/test_prompts.py`:

```python
def test_pubmedqa_mcp_prompt_mentions_full_abstract_and_maybe_calibration() -> None:
    prompt = Path("benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md").read_text()

    assert "mode='full_abstract'" in prompt
    assert "If preflight fails, call pubtator_get_publication_passages" in prompt
    assert "Do not convert conditional, underpowered, mixed, or method-limited evidence into yes/no" in prompt
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_prompts.py::test_pubmedqa_mcp_prompt_mentions_full_abstract_and_maybe_calibration -q
```

Expected: FAIL until the prompt is updated.

- [ ] **Step 3: Update the prompt**

In `benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md`, update the workflow section to include:

```markdown
Recommended workflow:
1. Use target_pmids from the case as the article-local evidence set.
2. Call pubtator_preflight_review_sources for those PMIDs when available.
3. If preflight fails, call pubtator_get_publication_passages with the same PMIDs.
4. For article-local answering, call pubtator_get_publication_passages with mode='full_abstract'. Prefer full text when available; otherwise use the complete title/abstract evidence.
5. Decide only from MCP-returned evidence. Do not use outside biomedical knowledge.
6. Do not convert conditional, underpowered, mixed, or method-limited evidence into yes/no. Use "maybe" when evidence supports a nuanced or context-dependent answer.
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_prompts.py -q
```

Expected: PASS.

---

### Task 9: Re-run Benchmarks And Gate On >9 Experience Target

**Files:**
- Modify: `benchmarks/reports/focused-51-delta-report.md`
- Modify: `benchmarks/reports/focused-51-delta-experience.md`
- Modify: `benchmarks/reports/focused-full-text-smoke-report.md`
- Raw ignored: `benchmarks/results/focused_51_delta/`
- Raw ignored: `benchmarks/results/focused_full_text_smoke/`

- [ ] **Step 1: Run focused unit checks**

Run:

```bash
uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_publication_passage_service.py tests/unit/test_source_preflight.py -q
uv run pytest tests/unit/benchmarks/test_summaries.py tests/unit/benchmarks/test_scoring_pubmedqa.py tests/unit/benchmarks/test_prompts.py -q
uv run ruff check pubtator_link/mcp/errors.py pubtator_link/mcp/tools/review.py pubtator_link/mcp/tools/publications.py pubtator_link/services/source_preflight.py pubtator_link/services/publication_passage_service.py pubtator_link/models/publication_passages.py scripts/analyze_focused_benchmark.py
```

Expected: PASS.

- [ ] **Step 2: Run the balanced 51 no-MCP control**

Run:

```bash
uv run python scripts/run_single_case_provider_benchmark.py --suite benchmarks/suites/pubmedqa_balanced_51.yaml --mode no_tools --provider claude --model sonnet --artifact-dir benchmarks/results/focused_51_delta --max-cases 51 --timeout-s 180 --prompt benchmarks/prompts/provider_pubmedqa_single_v4.md --prompt-version pubmedqa_no_tools_v4_context_policy --tool-workflow none
```

Expected: 51/51 complete, zero provider errors.

- [ ] **Step 3: Run the balanced 51 MCP treatment**

Run:

```bash
uv run python scripts/run_single_case_provider_benchmark.py --suite benchmarks/suites/pubmedqa_balanced_51.yaml --mode mcp_oracle_pmid --provider claude --model sonnet --artifact-dir benchmarks/results/focused_51_delta --max-cases 51 --timeout-s 300 --prompt benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md --prompt-version pubmedqa_mcp_article_local_v1 --tool-workflow preflight_review_sources>get_publication_passages
```

Expected: 51/51 complete, zero provider errors, source access counts present.

- [ ] **Step 4: Run the full-text smoke**

Run:

```bash
uv run python scripts/run_single_case_provider_benchmark.py --config benchmarks/configs/focused_full_text_smoke.yaml --run-name pubmedqa_full_text_smoke_claude
uv run python scripts/run_single_case_provider_benchmark.py --config benchmarks/configs/focused_full_text_smoke.yaml --run-name pubmedqa_full_text_smoke_claude_mcp
uv run python scripts/analyze_focused_benchmark.py --config benchmarks/configs/focused_full_text_smoke.yaml
```

Expected: full-text and abstract-only counts are visible in `benchmarks/reports/focused-full-text-smoke-report.md`.

- [ ] **Step 5: Generate the 51-case report**

Run:

```bash
uv run python scripts/analyze_focused_benchmark.py --artifact-root benchmarks/results/focused_51_delta --output benchmarks/reports/focused-51-delta-report.md --title "Focused 51-Case MCP Delta Report"
```

Expected: report includes:

```markdown
## MCP Experience Signals
```

and all mean ratings are above 9.0.

- [ ] **Step 6: Update experience summary**

Update `benchmarks/reports/focused-51-delta-experience.md` with:

```markdown
## Experience Gate

| Dimension | Mean Rating | Gate |
| --- | ---: | --- |
| tool_discoverability | 9.01+ | pass |
| context_quality | 9.01+ | pass |
| context_size_control | 9.01+ | pass |
| citation_support | 9.01+ | pass |
| latency | 9.01+ | pass |
| error_recovery | 9.01+ | pass |
| workflow_ergonomics | 9.01+ | pass |
```

Use actual observed values. If any dimension remains at or below 9.0, keep the gate as `fail` and add the exact model note that explains the remaining pain point.

- [ ] **Step 7: Run broad local checks**

Run:

```bash
uv run pytest tests/unit/benchmarks -q
uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_publication_passage_service.py tests/unit/test_source_preflight.py -q
make lint
make typecheck
```

Expected: PASS. If PostgreSQL is available, also run `make ci-local`; if it is blocked, report the missing service exactly.

---

## Implementation Order

1. Task 1: error recovery, because this is the lowest-rated dimension and removes manual fallback guessing.
2. Task 2: `full_abstract`, because it prevents truncation and improves context quality and ergonomics.
3. Task 3: text cleanup, because it is low-risk and improves context quality.
4. Task 4: source coverage clarity, because it improves citation support and model confidence.
5. Task 6 and Task 7: metrics/reporting, because we need to measure the improvement.
6. Task 8: prompt calibration, because it aligns tool use with the benchmark goal and reduces `maybe` overcalls.
7. Task 5: full-text suite, because it requires live source vetting and should be isolated from core tool fixes.
8. Task 9: rerun and gate on the >9 target.

## Risks And Mitigations

- **Risk:** `full_abstract` increases context size on unusually fragmented abstracts.
  - **Mitigation:** Keep `max_chars` budget enforced; `full_abstract` bypasses per-PMID passage count only for title/abstract sections.
- **Risk:** Experience ratings are subjective and may vary between provider runs.
  - **Mitigation:** Keep deterministic scores and experience ratings separate; require both aggregate ratings and model notes.
- **Risk:** Full-text PMIDs are unstable if upstream availability changes.
  - **Mitigation:** Store expected source access in case metadata and report drift if observed coverage differs.
- **Risk:** Prompt changes could inflate benchmark prompt quality rather than MCP capability.
  - **Mitigation:** Prompt changes must focus on tool workflow and calibration, not injecting biomedical task heuristics or gold labels.

## Final Verification Checklist

- [ ] Raw results remain ignored under `benchmarks/results/` and `benchmarks/logs/`.
- [ ] Gold labels and gold/reference answers do not render into answer prompts.
- [ ] Deterministic PubMedQA scoring remains separate from judge/self-assessment diagnostics.
- [ ] Source coverage counts appear in reports.
- [ ] `maybe_decisive_overcall_rate` appears in PubMedQA score details.
- [ ] Full-text smoke has at least one `full_text` source-access result.
- [ ] All MCP experience dimensions are greater than 9.0 or the report explicitly lists remaining failures.
- [ ] `uv run pytest tests/unit/benchmarks -q` passes.
- [ ] `make lint` passes.
- [ ] `make typecheck` passes.
