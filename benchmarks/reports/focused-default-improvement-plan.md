# Focused Default Benchmark Improvement Plan

Date: 2026-05-09

## Evidence Reviewed

- Deterministic focused default report: `benchmarks/reports/focused-default-report.md`
- LLM judge diagnostics: `benchmarks/reports/focused-default-judge.md`
- LLM execution self-assessment: `benchmarks/reports/focused-default-self-assessment.md`
- PubMedQA prompt used for the completed run: `benchmarks/prompts/provider_pubmedqa_single_v1.md`
- PubMedQA prompt configured for the next default run: `benchmarks/prompts/provider_pubmedqa_single_v2.md`
- External paper reviewed: https://arxiv.org/html/2510.14353v1

## Current Result Summary

| Suite | Mode | Provider | Cases | Main Result | Operational Result |
| --- | --- | --- | ---: | --- | --- |
| PubMedQA balanced | `no_tools` | Claude Sonnet | 30 | accuracy `0.633`, macro F1 `0.549` | 0 provider errors, 0 invalid labels |
| BioASQ complex | `no_tools` | Claude Sonnet | 12 | citation recall `0.000`, token F1 `0.284`, ROUGE-L `0.170` | 0 provider errors, 0 tool mentions |

PubMedQA class F1:

| Class | F1 | Interpretation |
| --- | ---: | --- |
| `yes` | `0.800` | Strongest class; model accepts direct support. |
| `no` | `0.667` | Usable but has false positives into `yes`. |
| `maybe` | `0.182` | Main failure; model forces ambiguous cases into binary answers. |

## What We Learned

The harness is stable enough for focused diagnostics. The run had no provider errors, no timeouts, no quota events, no invalid PubMedQA labels, and no tool leakage in `no_tools` mode.

The primary quality failure is not schema compliance. It is decision policy. Claude is behaving like a decisive binary classifier on PubMedQA and only predicted `maybe` once across 10 gold `maybe` cases.

The BioASQ result is a valid parametric baseline, not a useful grounded-answer result. In `no_tools`, zero citation recall is expected unless the model memorizes PMIDs. The useful next measurement is the delta from the same cases with tools enabled.

Latency has a right tail. `pubmedqa_balanced_001` took `86.2s`, roughly 4x the median. Future reports should make slow cases filterable by case metadata, response length, and retry/provider telemetry.

## Prompt Diagnosis

The v1 PubMedQA prompt was too underspecified:

- It listed `yes|no|maybe` but did not define when `maybe` is correct.
- It asked the model to "answer" the case, which encourages a decisive conclusion.
- It did not explicitly forbid forcing a binary answer under incomplete or mixed evidence.
- It did not make article-local evidence sufficiency the decision criterion.

The configured v2 prompt now makes `maybe` evidence-gated:

- `yes`: supplied evidence directly supports the question.
- `no`: supplied evidence directly contradicts the question.
- `maybe`: evidence is mixed, indirect, underpowered, incomplete, or insufficient.
- It explicitly instructs the model not to force a binary answer when yes and no interpretations remain plausible.

This is a prompt hypothesis, not a proven improvement. It needs a fresh A/B run against the same 30 balanced cases.

## Takeaways From CURE Paper

The CURE paper argues for confidence-aware routing and model diversity rather than blanket chain-of-thought. The most relevant details for this benchmark are:

- It uses a confidence detection step before deciding whether to route to helper models.
- Low-confidence cases are routed to complementary models, then synthesized by the primary model.
- Their ablation reports that single-model chain-of-thought can be mixed or harmful, while confidence-aware collaboration improves aggregate results.
- Their PubMedQA result is reported as high, but their paper describes PubMedQA as binary in one section despite PubMedQA's yes/no/maybe framing, so we should not copy their setup blindly.

Implication for this suite: use confidence and ambiguity detection as diagnostics, but do not turn the default prompt into verbose chain-of-thought. The safer next step is a structured, evidence-gated label policy plus optional confidence fields in raw outputs.

## Action Plan

### 1. Rerun PubMedQA Prompt A/B

Run the same 30 balanced cases with:

- v1 prompt: current completed baseline
- v2 prompt: evidence-gated `maybe` prompt

Primary success criteria:

- `maybe` F1 improves materially.
- Macro F1 improves without collapsing `yes` or `no`.
- Invalid label count remains 0.
- Mean latency does not increase by more than 20%.

### 2. Add Per-Case Analysis Output

Generate a tracked summary table, not raw provider output, with:

- `case_id`
- gold label
- predicted label
- correct/incorrect
- latency seconds
- response length
- prompt version
- provider/model

This makes class bias, slow cases, and prompt regressions inspectable without reading raw ignored artifacts.

### 3. Add Tool-Enabled BioASQ Focused Run

Run the same 12 complex BioASQ cases with MCP tools enabled.

Success criteria:

- citation recall rises above the `no_tools` zero baseline
- citation precision is non-zero and inspectable
- token F1 or ROUGE-L improves without schema failures
- tool mentions and accessed PMIDs are logged in structured summaries

### 4. Add Confidence Diagnostics Without Scoring Leakage

Permit providers to emit optional diagnostic fields such as:

- `confidence`
- `evidence_sufficiency`
- `ambiguity_reason`

These fields must remain separate from deterministic scoring. They are for analysis only and must not expose gold labels or reference answers in prompts.

### 5. Consider Confidence-Routed Multi-Provider Experiments

Inspired by CURE, add a later experimental mode:

1. primary model predicts label and confidence
2. low-confidence or ambiguous cases route to another provider/model
3. synthesis model chooses a final label from visible model opinions

This should remain outside the default v1 benchmark path until the single-provider prompt A/B and tool-enabled BioASQ runs are stable.

## Recommended Next Run

Run Claude only on the focused default after the v2 prompt change:

```bash
uv run python scripts/run_single_case_provider_benchmark.py \
  --config benchmarks/configs/focused_default.yaml \
  --run-name pubmedqa_balanced_30_claude
```

Then regenerate:

```bash
uv run python scripts/analyze_focused_benchmark.py --config benchmarks/configs/focused_default.yaml
uv run python scripts/run_focused_benchmark_diagnostics.py --config benchmarks/configs/focused_default.yaml
```

Do not overwrite the v1 report interpretation. Treat the next run as a new prompt-version comparison.
