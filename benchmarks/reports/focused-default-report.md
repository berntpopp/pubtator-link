# Focused Default Benchmark Report

## Runs

| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| bioasq_complex_12 | no_tools | claude | sonnet | 12 | citation recall 0.000, citation precision 0.000, token F1 0.284, ROUGE-L 0.170 | 0 | 0 | 34.68 |
| pubmedqa_balanced_30 (pubmedqa_no_tools_v3_uncertainty) | no_tools | claude | sonnet | 30 | accuracy 0.733, macro F1 0.694, invalid 0 | 0 | 0 | 10.73 |
| pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) | no_tools | claude | sonnet | 51 | accuracy 0.667, macro F1 0.656, invalid 0 | 0 | 0 | 11.99 |

## Error And Logging Analysis

### bioasq_complex_12 / claude / sonnet

- total runtime seconds: 416.1
- median seconds per case: 28.16
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0
- slowest cases: bioasq_complex_011 (57.3s), bioasq_complex_005 (50.6s), bioasq_complex_012 (50.5s), bioasq_complex_009 (35.3s), bioasq_complex_001 (35.2s)

### pubmedqa_balanced_30 (pubmedqa_no_tools_v3_uncertainty) / claude / sonnet

- tool workflow: none
- prompt path: benchmarks/prompts/provider_pubmedqa_single_v3.md
- total runtime seconds: 321.9
- median seconds per case: 9.47
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0
- slowest cases: pubmedqa_balanced_012 (23.1s), pubmedqa_balanced_018 (16.3s), pubmedqa_balanced_016 (16.0s), pubmedqa_balanced_002 (15.6s), pubmedqa_balanced_024 (13.0s)

### pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) / claude / sonnet

- tool workflow: none
- prompt path: benchmarks/prompts/provider_pubmedqa_single_v4.md
- total runtime seconds: 611.3
- median seconds per case: 10.1
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0
- slowest cases: pubmedqa_balanced_019 (35.9s), pubmedqa_balanced_023 (27.7s), pubmedqa_balanced_049 (20.8s), pubmedqa_balanced_041 (20.4s), pubmedqa_balanced_039 (20.2s)


## No-MCP vs MCP Deltas

No paired no-MCP/MCP runs found yet.

## MCP Experience Signals

No MCP runs with structured MCP experience fields found yet.

#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.870 |
| no | 0.783 |
| maybe | 0.429 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 10 | 0 | 0 |
| no | 0 | 9 | 1 |
| maybe | 3 | 4 | 3 |

#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.765 |
| no | 0.737 |
| maybe | 0.467 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 13 | 1 | 3 |
| no | 0 | 14 | 3 |
| maybe | 4 | 6 | 7 |