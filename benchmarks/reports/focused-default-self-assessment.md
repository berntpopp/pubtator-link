---

# Benchmark Execution Assessment

## Deterministic Correctness (Separated)

| Metric | Suite | Value | Verdict |
|--------|-------|-------|---------|
| Citation recall | bioasq_complex_12 | 0.000 | **Hard failure** — no valid citations extracted |
| Citation precision | bioasq_complex_12 | 0.000 | **Hard failure** |
| Token F1 | bioasq_complex_12 | 0.284 | Weak signal only |
| ROUGE-L | bioasq_complex_12 | 0.170 | Weak signal only |
| PubMedQA accuracy | pubmedqa_balanced_30 | 0.633 | Above chance (0.33), below strong |
| Macro F1 | pubmedqa_balanced_30 | 0.549 | Class-imbalanced drag |
| "maybe" F1 | pubmedqa_balanced_30 | 0.182 | **Systematic failure** on uncertain class |

The citation zeroes are *expected* in `no_tools` mode — this is the correct baseline. The "maybe" collapse is a behavioral property of the model, not a harness defect.

---

## Experience Diagnostics

### 1. Schema Compliance

No schema violations detected in either suite (`invalid = 0`). Outputs parsed cleanly across all 42 cases. The harness correctly ingested and scored structured responses. **No issues.**

### 2. Latency

Both suites show heavy right-tail distributions — a sign that occasional cases trigger substantially longer reasoning chains.

| Suite | Median | Mean | Max (case) | Mean/Median ratio |
|-------|--------|------|------------|-------------------|
| bioasq_complex_12 | 28.2s | 34.7s | 57.3s | 1.23× |
| pubmedqa_balanced_30 | 22.0s | 27.5s | 86.2s | 1.25× |

The `pubmedqa_balanced_001` outlier at **86.2s** is ~4× the median and ~2.5× the next-slowest case. This is the single most anomalous data point in the run. It warrants case-level inspection: long abstract, ambiguous framing, or an internal retry loop.

**Recommendation:** Add per-case wall-time logging with a soft warning threshold (e.g., >2× suite median) to surface latency outliers during run, not only in post-analysis.

### 3. Provider Reliability

**Perfect.** Zero provider errors, zero timeouts, zero quota events across 42 cases and ~20 minutes total wall time. Infrastructure is stable at this scale.

### 4. Tool Isolation

`no_tools` mode enforces correctly — MCP/tool mentions = 0 in both suites. No tool leakage into the baseline condition. This validates the harness mode-switching mechanism.

The flip side: these runs establish the **tool-absent floor**. The citation zeroes and low ROUGE-L scores quantify exactly what tool access would need to recover. The baseline is doing its job.

### 5. Citation Behavior

Zero citation recall and precision in `no_tools` mode confirms the model does not spontaneously produce verifiable PMIDs or structured references from parametric memory alone. This is the expected and desired baseline result.

What is diagnostically interesting: token F1 (0.284) and ROUGE-L (0.170) are non-zero, meaning the model generates *related content* — just not citable content. The gap between "semantically adjacent" (token F1) and "citable" (0.000) will be the core measurement target when tool-enabled runs are added.

### 6. Failure Recovery

No infrastructure failures required recovery. However, the confusion matrix reveals a **systematic classification bias** worth treating as an experience-level issue:

| Gold | yes | no | maybe |
|------|-----|----|-------|
| yes | 10 | 0 | 0 |
| no | 2 | 8 | 0 |
| **maybe** | **3** | **6** | **1** |

The model correctly handles "yes" (F1 0.800) and "no" (F1 0.667) but collapses "maybe" — 9 of 10 "maybe" cases are predicted as binary answers. This is a **decisive-answer bias**: the model resists expressing uncertainty without tool grounding. It does not recover into "maybe" even when the evidence is ambiguous.

This is not a harness bug. It is a signal that `maybe` detection in parametric-only mode is near-random, and sets the expectation that tool-enabled runs should materially lift "maybe" F1.

### 7. Insight Density

The run delivers high-quality baseline signal despite simplicity:

- **Confirmed:** `no_tools` mode correctly isolates parametric behavior from retrieval
- **Confirmed:** Citation metrics are zero without tool access (validates measurement design)
- **Confirmed:** Provider and harness stability at this case count
- **Revealed:** Model has strong binary bias — "maybe" is under-represented in outputs
- **Revealed:** Latency variance is significant; single-case outliers can dominate suite totals
- **Not yet visible:** How much tool access lifts citation metrics, ROUGE-L, and "maybe" F1 — requires the `with_tools` suite

The bioasq suite's token F1 (0.284) provides a weak but real content-overlap floor. If `with_tools` does not substantially increase this *and* lift citation recall, it would indicate the tool outputs are not being integrated into the answer text.

---

## Summary

| Dimension | Status | Priority |
|-----------|--------|----------|
| Schema compliance | Clean | — |
| Provider reliability | Clean | — |
| Tool isolation | Correct | — |
| Citation behavior | Expected zero (baseline) | Add `with_tools` runs |
| "maybe" class | Systematic collapse | Monitor against `with_tools` |
| Latency tail | 86.2s outlier needs inspection | Medium — add per-case threshold alerting |
| Insight density | High for a baseline run | Proceed to tool-enabled suite |

The baseline is valid. The immediate next step is a `with_tools` run on the same cases to measure the citation lift and "maybe" recovery delta.
