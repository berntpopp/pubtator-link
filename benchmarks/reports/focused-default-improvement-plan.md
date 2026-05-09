# Focused Default Benchmark Improvement Plan

Date: 2026-05-09

## Evidence Reviewed

- Deterministic focused default report: `benchmarks/reports/focused-default-report.md`
- LLM judge diagnostics: `benchmarks/reports/focused-default-judge.md`
- LLM execution self-assessment: `benchmarks/reports/focused-default-self-assessment.md`
- PubMedQA prompt used for the completed run: `benchmarks/prompts/provider_pubmedqa_single_v1.md`
- PubMedQA prompt configured for the next default run: `benchmarks/prompts/provider_pubmedqa_single_v3.md`
- MCP-aware PubMedQA tool prompt: `benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md`
- MCP-aware BioASQ tool prompt: `benchmarks/prompts/provider_bioasq_mcp_review_rag_v1.md`
- External papers and dataset references reviewed:
  - PubMedQA dataset card: https://huggingface.co/datasets/bigbio/pubmed_qa
  - CURE paper: https://www.mdpi.com/2504-2289/9/12/299
  - Science QA abstention paper: https://aclanthology.org/2024.findings-emnlp.197.pdf

## Current Result Summary And Focus

This benchmark is for measuring PubTator-Link MCP value, not prompt-maxing
PubMedQA. The default must be interpreted as paired no-MCP vs MCP runs on the
same cases.

| Suite | Mode | Provider | Cases | Main Result | Operational Result |
| --- | --- | --- | ---: | --- | --- |
| PubMedQA balanced | `no_tools` control | Claude Sonnet | 51 | accuracy `0.667`, macro F1 `0.656` | 0 provider errors, 0 invalid labels |
| BioASQ complex | `no_tools` | Claude Sonnet | 12 | citation recall `0.000`, token F1 `0.284`, ROUGE-L `0.170` | 0 provider errors, 0 tool mentions |

PubMedQA class F1:

| Class | F1 | Interpretation |
| --- | ---: | --- |
| `yes` | `0.870` | Strongest class; model accepts direct support. |
| `no` | `0.783` | Improved after context and v3 prompt. |
| `maybe` | `0.429` | Still weakest; improved but ambiguous cases are often forced into yes/no. |

## What We Learned

The harness is stable enough for focused diagnostics. The run had no provider errors, no timeouts, no quota events, no invalid PubMedQA labels, and no tool leakage in `no_tools` mode.

The primary product question is: how much does the MCP improve the LLM over the
no-MCP control, and where does the MCP experience make the LLM struggle?

The BioASQ result is a valid parametric baseline, not a useful grounded-answer result. In `no_tools`, zero citation recall is expected unless the model memorizes PMIDs. The useful next measurement is the delta from the same cases with tools enabled.

Latency has a right tail, but the corrected v3 PubMedQA run was faster than the
original run: mean `10.73s`/case and median `9.47s`/case. Future reports should
make slow cases filterable by case metadata, response length, and retry/provider
telemetry.

## Prompt Diagnosis

The v1 PubMedQA prompt and payload were too underspecified:

- It listed `yes|no|maybe` but did not define when `maybe` is correct.
- It asked the model to "answer" the case, which encourages a decisive conclusion.
- It did not explicitly forbid forcing a binary answer under incomplete or mixed evidence.
- It did not make article-local evidence sufficiency the decision criterion.
- The provider payload did not include the non-gold PubMedQA abstract context, so strict evidence prompts could only abstain.

The configured v3 prompt now makes `maybe` evidence-gated and maps it to the
abstention/uncertainty behavior used by science QA literature:

- `yes`: supplied evidence directly supports the question.
- `no`: supplied evidence directly contradicts the question.
- `maybe`: evidence is mixed, indirect, underpowered, incomplete, or insufficient.
- It explicitly instructs the model not to force a binary answer when yes and no interpretations remain plausible.
- It requires diagnostic-only fields: `evidence_status`, `confidence`, and `abstention_reason`.

This is now partially validated on the focused 30-case set after correcting the
input context. It improved accuracy from `0.633` to `0.733`, macro F1 from
`0.549` to `0.694`, and `maybe` F1 from `0.182` to `0.429`. It remains
insufficient for `maybe`, where only 3 of 10 gold `maybe` cases were predicted
correctly.

## Takeaways From CURE Paper

The CURE paper argues for confidence-aware routing and model diversity rather than blanket chain-of-thought. The most relevant details for this benchmark are:

- It uses a confidence detection step before deciding whether to route to helper models.
- Low-confidence cases are routed to complementary models, then synthesized by the primary model.
- Their ablation reports that single-model chain-of-thought can be mixed or harmful, while confidence-aware collaboration improves aggregate results.
- Their PubMedQA result is reported as high, but their paper describes PubMedQA as binary in one section despite PubMedQA's yes/no/maybe framing, so we should not copy their setup blindly.

The science QA abstention paper is directly relevant to our `maybe` failure. It
interprets PubMedQA `maybe` as high uncertainty from context and reports that
abstention wording such as "Unanswerable" can improve abstention behavior for
some models. The v3 prompt uses that insight while still requiring the canonical
PubMedQA label `maybe` for deterministic scoring.

Implication for this suite: use confidence and ambiguity detection as diagnostics,
but do not turn the default prompt into verbose chain-of-thought. The safer next
step is a structured, evidence-gated label policy plus diagnostic fields in raw
outputs.

## MCP Capability Adaptation

The lean MCP profile already supports the benchmark workflows we need:

| Benchmark need | MCP capability | Prompt adaptation |
| --- | --- | --- |
| Known PubMedQA PMID evidence | `pubtator.get_publication_passages` | Use `target_pmids`, retrieve compact passages, decide from retrieved passages only. |
| Review-style BioASQ retrieval | `pubtator.index_review_evidence`, `pubtator.inspect_review_index`, `pubtator.retrieve_review_context_batch` | Index target PMIDs, confirm source coverage, retrieve quote-mode context, cite only returned PMIDs/passages. |
| One-call open grounding | `pubtator.ground_question` | Reserve for open-retrieval experiments, not the default focused oracle-PMID benchmark. |
| Auditability | `pubtator.record_review_context`, `pubtator.get_review_audit_trail` | Later tool-enabled runs should record selected passages and citation keys. |

## Action Plan

### 1. Run Paired No-MCP vs MCP PubMedQA

Run the same 51 balanced cases with:

- no-MCP control: abstract context only
- MCP article-local: target PMID, preflight source coverage, retrieve passages, prefer full text when available

Primary success criteria:

- MCP macro F1 improves over no-MCP macro F1.
- Citation and retrieved-PMID fields are populated.
- Source access counts show full-text vs abstract-only vs missing.
- Invalid label count remains 0.
- Latency increase is explained by tool calls and acceptable for the quality delta.
- MCP experience fields parse for every case and remain excluded from deterministic scoring.

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

### 3. MCP Consumer Experience Rubric

Every MCP run should ask the LLM consumer to rate the MCP from 1-10 on:

- tool discoverability
- context quality
- context size control
- citation support
- latency
- error recovery
- workflow ergonomics

These are experience diagnostics, not deterministic scores.

### 4. Run Tool-Enabled BioASQ Focused Run

Run the same 12 complex BioASQ cases with MCP tools enabled.

Success criteria:

- citation recall rises above the `no_tools` zero baseline
- citation precision is non-zero and inspectable
- token F1 or ROUGE-L improves without schema failures
- tool mentions and accessed PMIDs are logged in structured summaries

### 5. Add Confidence Diagnostics Without Scoring Leakage

Permit providers to emit optional diagnostic fields such as:

- `confidence`
- `evidence_status`
- `abstention_reason`

These fields must remain separate from deterministic scoring. They are for analysis only and must not expose gold labels or reference answers in prompts.

### 6. Consider Confidence-Routed Multi-Provider Experiments

Inspired by CURE, add a later experimental mode:

1. primary model predicts label and confidence
2. low-confidence or ambiguous cases route to another provider/model
3. synthesis model chooses a final label from visible model opinions

This should remain outside the default v1 benchmark path until the single-provider prompt A/B and tool-enabled BioASQ runs are stable.

## Recommended Next Run

Run Claude only on the focused default after the v3 prompt change:

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
