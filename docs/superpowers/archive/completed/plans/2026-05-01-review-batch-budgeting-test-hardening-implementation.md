# Review Batch Budgeting Test Hardening Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Broaden pure-unit tests for review batch-budgeting behavior without changing production behavior.

**Architecture:** Extend `tests/unit/test_review_context_batch_budgeting.py` around `merge_batch_context()`. Use small Pydantic model fixtures and assert observable merged passages, drop reasons, source summaries, and query summaries.

**Tech Stack:** Python 3.11, pytest, Pydantic models, Make.

---

## File Structure

- Modify `tests/unit/test_review_context_batch_budgeting.py`: add focused tests.
- Modify production only if a test exposes an actual existing behavior bug.

## Task 1: Test Source-Fair First-Pass Representation

**Files:**
- Modify: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Add the source-fair test**

Append:

```python
def test_merge_batch_context_source_fair_represents_sources_before_overflow() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        budget_strategy="source_fair",
        max_total_passages=2,
        max_chars=1000,
        min_passages_per_source=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result(
                "q1",
                [
                    _passage("p1", "one", pmid="1"),
                    _passage("p2", "two", pmid="2"),
                    _passage("p3", "three", pmid="1"),
                ],
            )
        ],
        coverage_by_source={"1": "full_text", "2": "abstract_only"},
    )

    assert [passage.passage_id for passage in merged.passages] == ["p1", "p2"]
    assert merged.source_budget_summaries[0].candidate_count == 2
    assert merged.source_budget_summaries[0].returned_count == 1
    assert merged.source_budget_summaries[0].first_pass_eligible is True
    assert merged.source_budget_summaries[1].candidate_count == 1
    assert merged.source_budget_summaries[1].returned_count == 1
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_review_context_batch_budgeting.py
git commit -m "test: cover source fair batch budgeting"
```

## Task 2: Test Scarcity-First Ordering

**Files:**
- Modify: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Add scarcity-first test**

Append:

```python
def test_merge_batch_context_scarcity_first_prioritizes_scarcer_coverage() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        budget_strategy="scarcity_first",
        max_total_passages=1,
        max_chars=1000,
        min_passages_per_source=1,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[
            _result(
                "q1",
                [
                    _passage("full", "full text", pmid="1"),
                    _passage("abstract", "abstract text", pmid="2"),
                ],
            )
        ],
        coverage_by_source={"1": "full_text", "2": "abstract_only"},
    )

    assert [passage.passage_id for passage in merged.passages] == ["abstract"]
    assert any(drop.reason == "max_total_passages_exceeded" for drop in merged.dropped)
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_review_context_batch_budgeting.py
git commit -m "test: cover scarcity first batch budgeting"
```

## Task 3: Test Response Character Budget Drops

**Files:**
- Modify: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Add response budget test**

Append:

```python
def test_merge_batch_context_drops_when_response_budget_would_be_exceeded() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        max_total_passages=5,
        max_chars=1000,
        max_response_chars=10,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[_result("q1", [_passage("p1", "one")])],
        coverage_by_source={},
    )

    assert merged.passages == []
    assert merged.dropped[0].reason == "response_char_budget_exceeded"
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_review_context_batch_budgeting.py
git commit -m "test: cover batch response character budget"
```

## Task 4: Test Diagnostics-Only Mode

**Files:**
- Modify: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Add diagnostics mode test**

Append:

```python
def test_merge_batch_context_diagnostics_mode_skips_merged_passages() -> None:
    request = RetrieveReviewContextBatchRequest(
        queries=["q1"],
        response_mode="diagnostics",
        max_total_passages=5,
        max_chars=1000,
    )

    merged = merge_batch_context(
        request=request,
        query_results=[_result("q1", [_passage("p1", "one")])],
        coverage_by_source={},
    )

    assert merged.passages == []
    assert merged.query_summaries[0].query == "q1"
    assert merged.query_summaries[0].returned_count == 0
```

- [ ] **Step 2: Run focused tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q
```

Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_review_context_batch_budgeting.py
git commit -m "test: cover diagnostics batch response mode"
```

## Task 5: Final Verification

**Files:**
- Modify: `tests/unit/test_review_context_batch_budgeting.py`

- [ ] **Step 1: Run focused review tests**

```bash
uv run pytest tests/unit/test_review_context_batch_budgeting.py tests/unit/test_review_context_service.py -q
```

Expected: pass.

- [ ] **Step 2: Run full gate**

```bash
make ci-local
make test-cov
```

Expected: both exit 0 and coverage remains at or above 80%.

- [ ] **Step 3: Check for final cleanup changes**

```bash
git add tests/unit/test_review_context_batch_budgeting.py
git commit -m "test: finalize review batch budgeting hardening"
```

Run:

```bash
git status --short
```

If `tests/unit/test_review_context_batch_budgeting.py` changed during final verification, commit it. If `git status --short` is empty, do not create an empty commit for this task.

## Plan Self-Review Checklist

- Spec coverage: source-fair, scarcity-first, response budget, diagnostics mode, and source summaries are covered.
- Placeholder scan: no placeholders.
- Type consistency: tests use existing `RetrieveReviewContextBatchRequest` and `merge_batch_context`.
