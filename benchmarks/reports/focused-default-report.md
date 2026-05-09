# Focused Default Benchmark Report

## Runs

| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| bioasq_complex_12 | no_tools | claude | sonnet | 12 | citation recall 0.000, citation precision 0.000, token F1 0.284, ROUGE-L 0.170 | 0 | 0 | 34.68 |
| pubmedqa_balanced_30 | no_tools | claude | sonnet | 30 | accuracy 0.633, macro F1 0.549, invalid 0 | 0 | 0 | 27.50 |

## Error And Logging Analysis

### bioasq_complex_12 / claude / sonnet

- total runtime seconds: 416.1
- median seconds per case: 28.16
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0
- slowest cases: bioasq_complex_011 (57.3s), bioasq_complex_005 (50.6s), bioasq_complex_012 (50.5s), bioasq_complex_009 (35.3s), bioasq_complex_001 (35.2s)

### pubmedqa_balanced_30 / claude / sonnet

- total runtime seconds: 824.9
- median seconds per case: 22.01
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0
- slowest cases: pubmedqa_balanced_001 (86.2s), pubmedqa_balanced_014 (52.9s), pubmedqa_balanced_022 (44.4s), pubmedqa_balanced_004 (41.9s), pubmedqa_balanced_015 (40.4s)


#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.800 |
| no | 0.667 |
| maybe | 0.182 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 10 | 0 | 0 |
| no | 2 | 8 | 0 |
| maybe | 3 | 6 | 1 |