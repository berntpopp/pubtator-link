# PubMedQA 50-Case Single-Prediction Smoke

Date: 2026-05-09
Dataset: PubMedQA PQA-L, first 50 cases from `pqa_l_full_1000_v1`
Task: yes / no / maybe classification
Mode: `no_tools`
Execution shape: one provider call per case, one prediction per call

## Results

| Provider | Model | Completed Cases | Provider Errors | Accuracy | Macro F1 | Mean sec/case | Notes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Claude | `sonnet` | 50/50 | 0 | 0.720 | 0.630 | 33.28 | Complete run. |
| Codex | `gpt-5.4` | 47/50 | 3 | 0.840 | 0.877 | 31.70 | 3 timeouts counted incorrect. |
| Gemini | `gemini-2.5-flash` | 49/50 | 1 | 0.480 | 0.391 | 21.35 | Flash rerun; one unparsable response counted incorrect. |

## Confusion Matrices

### Claude

Gold distribution: yes 25, no 18, maybe 7.

| Gold \\ Pred | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 24 | 1 | 0 |
| no | 8 | 10 | 0 |
| maybe | 3 | 2 | 2 |

### Codex

Gold distribution among scored rows: yes 25, no 15, maybe 7. Three provider timeouts were counted as invalid/incorrect.

| Gold \\ Pred | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 22 | 1 | 2 |
| no | 1 | 14 | 0 |
| maybe | 1 | 0 | 6 |

Timeout cases: `pubmedqa_full_0015`, `pubmedqa_full_0026`, `pubmedqa_full_0028`.

### Gemini Flash

Gold distribution among scored rows plus one invalid: yes 24, no 18, maybe 7, invalid 1.

| Gold \ Pred | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 17 | 5 | 2 |
| no | 8 | 6 | 4 |
| maybe | 5 | 1 | 1 |

Unparsed case: `pubmedqa_full_0012`.

## Interpretation

Codex was strongest on the 50-case no-tools PubMedQA smoke despite three timeouts. Claude showed high yes-bias: it predicted yes 35 times on a gold distribution with 25 yes labels, hurting no and maybe recall. Gemini Flash completed 49/50 parseable predictions but was substantially less accurate and also yes-biased.

These are no-tools results. They measure model prior plus any benchmark contamination, not MCP retrieval.

Raw artifacts:

- `benchmarks/results/20260509-pubmedqa-50-single/pubmedqa_full-no_tools-claude-1778316466/`
- `benchmarks/results/20260509-pubmedqa-50-single/pubmedqa_full-no_tools-codex-1778316466/`
- `benchmarks/results/20260509-pubmedqa-50-single/pubmedqa_full-no_tools-gemini-1778319048/`
