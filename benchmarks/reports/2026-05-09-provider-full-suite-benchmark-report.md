# Provider Full-Suite Benchmark Report

Date: 2026-05-09
Repository: `/home/bernt-popp/development/pubtator-link`
Benchmark runner: `pubtator_link.benchmarks` v1 working tree
Raw artifact roots:
- `benchmarks/results/20260509-provider-full-suite/`
- `benchmarks/results/20260509-provider-probes/`

## Executive Readout

The only tracked "full sets" currently available are the pinned smoke suites:

| Suite | Dataset | Cases | Modes Run |
| --- | --- | ---: | --- |
| `pubmedqa_smoke` | PubMedQA PQA-L article-local | 10 | `no_tools`, `mcp_oracle_pmid` |
| `bioasq_ideal_smoke` | BioASQ generated ideal answer | 3 | `no_tools`, `mcp_oracle_pmid` |

Provider coverage was asymmetric:

| Provider Stack | Current Status | Interpretation |
| --- | --- | --- |
| `dry_run:deterministic` | Ran all suites/modes | Harness sanity check only; not a model benchmark. |
| `claude_code:sonnet` | Ran all suites/modes | Model output usable after parsing raw Claude `result` JSON. |
| `codex_cli:gpt-5.4` | Not run | Adapter intentionally raises `AdapterNotAvailable`: interface exists, live execution is not implemented in v1. |
| `gemini_cli:gemini-3.1-pro-preview` | Not run | Adapter intentionally raises `AdapterNotAvailable`: interface exists, live execution is not implemented in v1. |

Critical validity note: Claude debug logs showed zero MCP tool calls in both `mcp_oracle_pmid` runs. Therefore the Claude `mcp_oracle_pmid` rows below measure prompt exposure to oracle PMIDs, not verified PubTator-Link MCP retrieval quality.

## Environment

| CLI | Version / Path |
| --- | --- |
| Claude Code | `2.1.138`; `/home/bernt-popp/.local/bin/claude` |
| Codex CLI | `codex-cli 0.129.0`; `/home/bernt-popp/.nvm/versions/node/v24.14.1/bin/codex` |
| Gemini CLI | `0.39.1`; `/home/bernt-popp/.nvm/versions/node/v24.14.1/bin/gemini` |

## Run Matrix

### PubMedQA Label Classification

| Stack | Mode | Cases | Parsed Predictions | Accuracy | Macro F1 | Debug MCP Calls | Cost USD | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `dry_run:deterministic` | `no_tools` | 10 | 10 | 1.000 | 1.000 | 0 | n/a | Oracle harness check; uses gold labels by construction. |
| `dry_run:deterministic` | `mcp_oracle_pmid` | 10 | 10 | 1.000 | 1.000 | 0 | n/a | Oracle harness check; uses gold labels by construction. |
| `claude_code:sonnet` | `no_tools` | 10 | 10 | 0.900 | 0.905 | 0 | 0.3927 | Raw Claude JSON parsed from `answer_output.json`. |
| `claude_code:sonnet` | `mcp_oracle_pmid` | 10 | 10 | 0.900 | 0.905 | 0 | 0.6644 | No MCP calls observed; not a retrieval benchmark. |

Claude PubMedQA paired delta on this pinned set:

| Delta | Value |
| --- | ---: |
| `mcp_oracle_pmid - no_tools` accuracy | +0.000 |
| `mcp_oracle_pmid - no_tools` macro F1 | +0.000 |

Interpretation: on these 10 cases, Claude already answers 9/10 under `no_tools`. The oracle-PMID prompt condition did not improve label accuracy, and because no MCP calls occurred, the row cannot support claims about PubTator-Link retrieval benefit.

### BioASQ Generated Ideal Answer

| Stack | Mode | Cases | Parsed Predictions | Citation Recall | Citation Precision | Token F1 | ROUGE-L F1 | Debug MCP Calls | Cost USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `dry_run:deterministic` | `no_tools` | 3 | 3 | 0.000 | 0.000 | 1.000 | 1.000 | 0 | n/a |
| `dry_run:deterministic` | `mcp_oracle_pmid` | 3 | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | n/a |
| `claude_code:sonnet` | `no_tools` | 3 | 3 | 0.000 | 0.000 | 0.275 | 0.162 | 0 | 0.1404 |
| `claude_code:sonnet` | `mcp_oracle_pmid` | 3 | 3 | 1.000 | 1.000 | 0.319 | 0.213 | 0 | 0.1906 |

Claude BioASQ paired deltas:

| Metric | Delta |
| --- | ---: |
| Citation recall | +1.000 |
| Citation precision | +1.000 |
| Mean token F1 | +0.044 |
| Mean ROUGE-L F1 | +0.051 |

Interpretation: exposing oracle PMIDs caused Claude to cite the expected references exactly, and lexical overlap improved modestly. Because no MCP tool calls occurred, this is evidence of citation-prompt conditioning, not evidence that PubTator-Link retrieved or improved answer evidence.

## Source Access

BioASQ required PMIDs were scored as:

| Access Class | Rate |
| --- | ---: |
| `full_text` | 0.000 |
| `abstract_only` | 1.000 |
| `metadata_only` | 0.000 |
| `missing` | 0.000 |

This matches the design expectation that the BioASQ ideal-answer smoke is abstract-level evidence only. The report should not imply full-text coverage.

## Provider Adapter Findings

Codex and Gemini CLIs are installed, but the benchmark v1 adapter implementations are intentionally non-executable:

| Stack | Probe Result |
| --- | --- |
| `codex_cli:gpt-5.4` | Exit 1, `AdapterNotAvailable: codex_cli live adapter is a manual v1 follow-up` |
| `gemini_cli:gemini-3.1-pro-preview` | Exit 1, `AdapterNotAvailable: gemini_cli live adapter is a manual v1 follow-up` |

Claude ran, but the adapter did not parse nested Claude `result` JSON into `predictions.jsonl`; metrics above were computed from raw `answer_output.json`. That should be fixed before treating Claude rows as first-class benchmark artifacts.

## Validity Risks

1. The current `case_id` values contain PMIDs, for example `pubmedqa_21618245`. That leaks target identifiers into `no_tools` prompts even when `target_pmids` are hidden. This contaminates model-prior estimates.
2. `mcp_oracle_pmid` did not produce MCP tool calls in Claude debug logs. This invalidates any claim of MCP retrieval lift from this run.
3. The tracked full sets are small smoke sets, not statistically powered benchmark suites. PubMedQA has `n=10`; BioASQ ideal has `n=3`.
4. Dry-run metrics are harness sentinels, not model-quality measurements.
5. BioASQ generated-answer token F1 and ROUGE-L are weak lexical diagnostics. They should not be treated as semantic correctness without judge diagnostics or stronger deterministic checks.

## Recommendations

1. Replace PMID-bearing `case_id` values in rendered prompt contexts with opaque IDs for `no_tools`.
2. Add hard validation that `mcp_oracle_pmid` runs contain at least one expected PubTator-Link MCP call before reporting them as MCP runs.
3. Implement executable Codex and Gemini adapters before making cross-provider comparisons.
4. Parse Claude `result` JSON into `PredictionRecord` inside the adapter so artifact `scores.json` is authoritative.
5. Separate headline model-prior results from evidence-access results; do not call `mcp_oracle_pmid - no_tools` "MCP lift."

## Bottom Line

Current evidence supports only this narrow claim:

> On the tracked pinned smoke suites, the benchmark harness runs end-to-end, Claude can produce parseable JSON answers, and oracle-PMID prompt exposure improves BioASQ citation metrics. The run does not yet establish PubTator-Link MCP retrieval lift across providers because Codex/Gemini live adapters are not implemented and Claude made zero MCP tool calls in the MCP-labeled runs.
