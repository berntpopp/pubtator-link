# Focused 51-Case MCP Delta Report

## Runs

| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) | mcp_oracle_pmid | claude | sonnet | 51 | accuracy 0.745, macro F1 0.687, invalid 0 | 0 | 51 | 33.93 |
| pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) | no_tools | claude | sonnet | 51 | accuracy 0.706, macro F1 0.690, invalid 0 | 0 | 0 | 12.70 |

## Error And Logging Analysis

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) / claude / sonnet

- tool workflow: get_publication_passages
- prompt path: benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md
- total runtime seconds: 1730.5
- median seconds per case: 33.34
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 51

### pubmedqa_balanced_51 (pubmedqa_no_tools_v4_context_policy) / claude / sonnet

- tool workflow: none
- prompt path: benchmarks/prompts/provider_pubmedqa_single_v4.md
- total runtime seconds: 647.9
- median seconds per case: 10.74
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0


## No-MCP vs MCP Deltas

| Dataset | Provider | Metric | No MCP | MCP | Delta | No MCP sec/case | MCP sec/case | Retrieved PMIDs | Cited PMIDs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pubmedqa | claude | macro F1 | 0.690 | 0.687 | -0.002 | 12.70 | 33.93 | 51 | 51 |

## MCP Experience Signals

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1)

- retrieved PMIDs: 51
- cited PMIDs: 51
- source access counts: {'abstract_only': 51}

| Dimension | Mean Rating |
| --- | ---: |
| citation_support | 7.65 |
| context_quality | 8.22 |
| context_size_control | 8.41 |
| error_recovery | 6.78 |
| latency | 8.25 |
| tool_discoverability | 8.00 |
| workflow_ergonomics | 8.08 |


#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.872 |
| no | 0.810 |
| maybe | 0.381 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 17 | 0 | 0 |
| no | 0 | 17 | 0 |
| maybe | 5 | 8 | 4 |

#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.800 |
| no | 0.769 |
| maybe | 0.500 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 14 | 1 | 2 |
| no | 0 | 15 | 2 |
| maybe | 4 | 6 | 7 |