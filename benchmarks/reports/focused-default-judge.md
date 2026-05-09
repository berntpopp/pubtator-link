## Benchmark Diagnostic Review

---

### Validity Risks

**Critical — BioASQ citation scores are identically zero**
`citation_recall = 0.000` and `citation_precision = 0.000` across all 12 cases. Exact-zero on both metrics simultaneously is a strong signal of a scoring-pipeline bug, not model behavior. Likely causes: the citation extractor is not finding citations in the response text (wrong regex / format mismatch), or the gold citation IDs are in a different format than what the model produces (e.g., PMIDs vs DOIs vs plain author-year strings). These metrics are uninformative in their current state and should not be used to characterize model performance.

**High — "maybe" class is near-random**
Gold `maybe` cases: 3 predicted `yes`, 6 predicted `no`, 1 correct → F1 0.182. The model essentially never emits "maybe". This is a known LLM bias but also means the balanced-30 split may not be providing any discriminative signal for that class. With only 10 `maybe` gold cases, a single additional correct prediction shifts F1 by ~0.15.

**Medium — `no_tools` mode makes citation metrics vacuous for BioASQ**
If BioASQ citation recall is defined as matching retrieved PMIDs, running in `no_tools` mode guarantees zero recall unless the model reproduces PMIDs from training memory. This conflates tool access with recall performance. The metric label is misleading for this mode.

---

### Provider Experience Issues

**Latency outliers without explanation**
- `pubmedqa_balanced_001`: 86.2 s — roughly 4× the median (22 s). No timeout or error logged.
- `bioasq_complex_011`: 57.3 s — 2× its suite median.

These outliers inflate mean sec/case without any logged cause (no quota, no retry, no tool call). They likely represent long context or streaming stalls that are invisible to the current logging layer.

**No tool calls logged in either suite**
Expected in `no_tools` mode, but worth confirming the run config actually suppressed tool access rather than just not logging it. If MCP was silently available, citation behavior would be unexplained.

---

### Schema / Logging Failures

| Issue | Severity |
|---|---|
| Citation extractor emits 0/0 with no debug trace | Critical |
| No per-case prediction logged alongside gold label | High |
| Outlier latency cases have no cause field in logs | Medium |
| `maybe` confusion breakdown not surfaced in top-level metrics | Low |

The absence of per-case output logs means it is impossible to distinguish "model never cited anything" from "model cited but extractor failed." This blocks root-cause diagnosis entirely.

---

### Concrete Improvements (ranked by impact)

1. **Fix or instrument citation extraction** — Add a debug log of the raw response snippet and the citation-extraction result for at least one BioASQ case. If the extractor returns empty lists, the regex or format assumption is wrong. *Impact: makes the primary BioASQ metric meaningful.*

2. **Separate citation recall from tool-recall** — For `no_tools` mode, report a "parametric citation recall" (PMIDs the model emits from memory) separately from "retrieved citation recall." Mixing the two hides what is actually being measured.

3. **Add a `with_tools` BioASQ run** — Running the same 12 cases with MCP tools enabled gives a direct delta for tool contribution and validates whether citations become non-zero. Without this, the BioASQ suite produces no actionable signal.

4. **Increase `maybe` sample size or report per-class support** — With only 10 gold `maybe` cases, macro F1 is noisy. Either upsample to ≥30 per class or report support-weighted F1 alongside macro F1 so the instability is visible.

5. **Log per-case prediction and gold label** — Emit a structured record `{case_id, gold, prediction, latency_s, response_chars}` per case. This enables post-hoc slicing (latency vs. difficulty, response length vs. F1) and is a prerequisite for any future regression detection.

6. **Tag slow cases with a cause field** — If a case exceeds 2× suite median latency, log the first detectable cause (context length, retry count, stream stall). This turns outlier inspection from manual grep work into a filterable field.
