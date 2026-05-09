## Benchmark Execution Experience Assessment

---

### Deterministic Correctness (Reference Only)

| Suite | Key Metric | Value |
|---|---|---|
| bioasq_complex_12 | token F1 / ROUGE-L | 0.284 / 0.170 |
| pubmedqa_balanced_30 (v3) | accuracy / macro F1 | 0.733 / 0.694 |
| pubmedqa_balanced_51 (v4) | accuracy / macro F1 | 0.667 / 0.656 |

v4 underperforms v3 on accuracy (−0.066) and macro F1 (−0.038) despite a larger evaluation set. Correctness discussion ends here; the remainder is execution experience.

---

### 1. Schema Compliance

**Rating: Excellent**

- `invalid` label count is **0** across both PubMedQA runs (30 and 51 cases).
- BioASQ reports no parse or schema errors; 0 provider errors logged.
- All three suites completed without a single malformed response requiring rejection or fallback parsing.

No compliance incidents detected.

---

### 2. Latency

**Rating: Acceptable with notable BioASQ tail**

| Suite | Median s/case | Mean s/case | Mean/Median ratio | Slowest case |
|---|---:|---:|---:|---:|
| bioasq_complex_12 | 28.16 | 34.68 | **1.23** | 57.3 s |
| pubmedqa_balanced_30 | 9.47 | 10.73 | 1.13 | 23.1 s |
| pubmedqa_balanced_51 | 10.1 | 11.99 | 1.19 | 35.9 s |

- BioASQ mean/median spread (1.23) signals moderate right-tail skew: at least one cluster of cases is substantially heavier. Three cases exceeded 50 s.
- PubMedQA latency is stable and predictable. Both versions are comparable (10–12 s mean), with the spread tighter.
- Nothing suggests rate limiting or throttling; variance looks like prompt-length driven, not provider-induced jitter.
- **Watch:** If BioASQ expands beyond 12 cases, the tail (50+ s outliers) will dominate total wall time.

---

### 3. Provider Reliability

**Rating: Perfect within this run**

- Provider error count: **0** across all 93 cases.
- Timeout mentions: **0**.
- Quota/capacity mentions: **0**.

The run was clean. No retry logic was exercised. This is a single-run snapshot; reliability under concurrent load or longer suites is not captured here.

---

### 4. Tool Isolation

**Rating: Verified clean**

- All three suites ran `no_tools` mode.
- MCP/tool mentions in raw provider logs: **0** for every suite.
- The no-tool boundary held completely — no accidental tool invocations leaked through system prompt or prompt templating.

This is a meaningful signal: if tool mentions appeared in raw logs it would indicate prompt leakage. None did.

---

### 5. Citation Behavior

**Rating: Not exercisable in this configuration**

- BioASQ citation recall and precision are both **0.000** — expected given `no_tools` mode. Without retrieval, the model has no mechanism to produce grounded citations matching the gold standard.
- PubMedQA does not assess citations; metric not applicable.

**Diagnosis:** Citation metrics in a no_tools suite measure only parametric recall of specific citation identifiers, which is near-zero for most LLMs. These numbers do not reflect tool-augmented citation capability. They serve as a useful zero-baseline but should not be interpreted as a ceiling.

---

### 6. Failure Recovery

**Rating: Not exercised — baseline not established**

Zero errors occurred, so no recovery paths were triggered. This means:

- Retry logic correctness is unverified.
- Graceful degradation behavior (partial results, timeouts, fallback prompts) has no evidence in this run.
- For experience purposes, a run with injected failures (malformed responses, forced timeouts) is needed to assess recovery behavior.

Current data only confirms the happy path.

---

### 7. Insight Density

**Rating: Moderate — actionable signals exist but output metadata is thin**

Positive signals:

- Per-class F1 and confusion matrices are present for both PubMedQA runs — this is the most diagnostically useful artifact.
- Slowest-case listings per suite enable targeted case-level investigation.
- Runtime totals and per-case medians are captured consistently.

Gaps:

- **No per-case latency distribution** (histogram or percentiles). Median alone obscures the tail shape; the five-slowest list is a proxy, not a distribution.
- **No prompt token counts.** The BioASQ/PubMedQA latency gap (3× slower) is likely prompt-length driven, but there is no token-count artifact to confirm this.
- **No `maybe` gold-label breakdown by question type** across v3 vs v4. The `maybe` class degraded from F1 0.429 → 0.467 (improved slightly) but the confusion matrix shift (v3: 3 misses to `yes` / 4 to `no`; v4: 4 misses to `yes` / 6 to `no`) shows systematic `maybe`→`no` drift in v4 that is diagnostically interesting and unexplained by the current artifacts.
- **No inter-run comparison artifact.** v3 vs v4 results are presented in separate tables rather than a diff-aligned view, making regression detection manual.

---

### Summary Table

| Dimension | Rating | Primary Evidence |
|---|---|---|
| Schema compliance | Excellent | 0 invalid labels, 0 parse errors |
| Latency | Acceptable | BioASQ tail up to 57 s; PubMedQA stable ~10 s |
| Provider reliability | Perfect (this run) | 0 errors, 0 timeouts across 93 cases |
| Tool isolation | Verified clean | 0 tool mentions in no-tools runs |
| Citation behavior | Baseline only | 0.000 recall/precision expected without tools |
| Failure recovery | Not exercised | Happy-path only; no injected failures |
| Insight density | Moderate | Good confusion matrices; missing token counts and latency distributions |
