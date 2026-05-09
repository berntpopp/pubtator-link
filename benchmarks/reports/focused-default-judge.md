## Benchmark Diagnostic Review

### Validity Risks

**Citation metrics are meaningless in no_tools mode.**
BioASQ reports citation recall 0.000 / precision 0.000 for a run where the model has no tool access and therefore cannot retrieve PMIDs. These are structurally guaranteed zeros, not a signal about model quality. Reporting them alongside token F1 / ROUGE-L creates false equivalence between two very different evaluation axes.

**v4 prompt regresses vs v3 on all headline metrics.**
pubmedqa_balanced_51 (v4, context_policy) scores accuracy 0.667 / macro F1 0.656 vs pubmedqa_balanced_30 (v3, uncertainty) at 0.733 / 0.694. The case sets differ (30 vs 51), so exact comparison is noisy, but the direction is consistently negative across both accuracy and macro F1. A newer prompt performing worse is a validity risk unless the set-size difference fully explains it — it likely does not, because the v4 "maybe" F1 (0.467) is still lower than v3 (0.429... wait, v4 0.467 > v3 0.429 — "maybe" is slightly better in v4), but "yes" and "no" F1 both drop sharply (0.765 vs 0.870; 0.737 vs 0.783).

**"Maybe" class is a systematic failure mode across both prompts.**
Confusion matrices show the model converts the majority of gold-"maybe" labels to "yes" or "no": 7/10 in v3, 10/17 in v4. This is not random noise; it suggests both prompts under-elicit hedged responses.

---

### Provider Experience Issues

**No tools invoked across all three runs.**
All suites are in `no_tools` mode. For BioASQ, which is specifically designed to test citation-grounded answering, this means the MCP/RAG stack is entirely untested here. The run structure does not exercise the provider experience that end users encounter.

**BioASQ latency variance is large and unexplained.**
Slowest case (57.3 s) is 2× the median (28.2 s) with no tool calls to blame. This points to generation-length variance on complex multi-hop questions. Without per-case token counts or generation lengths in the logs, the root cause is opaque.

---

### Schema / Logging Failures

| Issue | Severity |
|---|---|
| Citation recall/precision emitted for `no_tools` runs — always 0, never informative | High |
| No per-case correctness breakdown in report — impossible to identify systematic failure patterns from the report alone | Medium |
| BioASQ lacks a question-type or class-level breakdown (factoid / list / yes/no) that would match PubMedQA reporting depth | Medium |
| Slowest-case latency logged but no token-count or generation-length field — latency spike root cause untraceable | Low |

---

### Improvements Ranked by Impact

**1. Add a tools-enabled BioASQ run (highest impact)**
The citation evaluation framework is completely dark. A single 12-case run with MCP tools enabled would produce non-trivial citation recall/precision and validate the entire retrieval pipeline end-to-end. This is the biggest gap in the current benchmark.

**2. Suppress citation metrics for `no_tools` runs (high impact, low effort)**
Emit `null` or omit citation recall/precision when `tool_workflow: none`. Prevents misleading 0.000 values from being interpreted as model failures rather than evaluation non-applicability.

**3. Head-to-head prompt comparison on the same case set**
Run v3 and v4 on `balanced_51` (or both on `balanced_30`) to isolate the prompt effect from the set-size effect. Currently the regression signal is real but confounded.

**4. Improve "maybe" class coverage in prompts**
Both prompts systematically over-predict binary answers. Add 1–2 few-shot examples where the correct answer is "maybe" and the evidence is genuinely ambiguous. Target: bring "maybe" F1 above 0.55.

**5. Add per-case correctness output to the run artifact**
A case-level CSV with `[case_id, gold_label, predicted_label, correct, latency_s]` would let reviewers directly inspect the confusion matrix entries and identify whether failures cluster by question type, year, or topic.

**6. Log generation token counts per case**
Pairing latency with output token count would immediately explain the BioASQ outlier cases (57 s vs 28 s median) and separate model reasoning depth from infrastructure noise.
