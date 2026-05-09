# Focused Balanced 10-Case MCP Smoke Report

## Runs

| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) | mcp_oracle_pmid | claude | sonnet | 10 | accuracy 0.900, macro F1 0.896, invalid 0 | 0 | 10 | 35.26 |
| pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) | no_tools | claude | sonnet | 10 | accuracy 0.700, macro F1 0.707, invalid 0 | 0 | 0 | 14.80 |

## Error And Logging Analysis

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) / claude / sonnet

- tool workflow: get_publication_passages
- prompt path: benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md
- total runtime seconds: 352.6
- median seconds per case: 33.96
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 10

### pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) / claude / sonnet

- tool workflow: none
- prompt path: benchmarks/prompts/provider_pubmedqa_single_v4.md
- total runtime seconds: 148.0
- median seconds per case: 11.16
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0


## No-MCP vs MCP Deltas

| Dataset | Provider | Metric | No MCP | MCP | Delta | No MCP sec/case | MCP sec/case | Retrieved PMIDs | Cited PMIDs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pubmedqa | claude | macro F1 | 0.707 | 0.896 | +0.189 | 14.80 | 35.26 | 10 | 10 |

## MCP Experience Signals

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1)

- retrieved PMIDs: 10
- cited PMIDs: 10
- source access counts: {'abstract_only': 10}

| Dimension | Mean Rating |
| --- | ---: |
| citation_support | 7.90 |
| context_quality | 8.00 |
| context_size_control | 8.40 |
| error_recovery | 6.50 |
| latency | 8.50 |
| tool_discoverability | 7.90 |
| workflow_ergonomics | 7.80 |


#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.889 |
| no | 1.000 |
| maybe | 0.800 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 4 | 0 | 0 |
| no | 0 | 3 | 0 |
| maybe | 1 | 0 | 2 |

#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.750 |
| no | 0.800 |
| maybe | 0.571 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 3 | 0 | 1 |
| no | 0 | 2 | 1 |
| maybe | 1 | 0 | 2 |