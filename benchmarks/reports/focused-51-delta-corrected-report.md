# Focused 51-Case Corrected MCP Delta Report

## Runs

| Suite | Mode | Provider | Model | Cases | Deterministic Scores | Errors | Tool Mentions | Mean sec/case |
| --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: |
| pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) | mcp_oracle_pmid | claude | sonnet | 51 | accuracy 0.725, macro F1 0.672, invalid 0 | 0 | 51 | 33.13 |
| pubmedqa_balanced_51 (pubmedqa_no_tools_v4_open_no_mcp) | no_tools | claude | sonnet | 51 | accuracy 0.588, macro F1 0.537, invalid 1 | 0 | 0 | 36.51 |

## Error And Logging Analysis

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1) / claude / sonnet

- tool workflow: get_publication_passages
- prompt path: benchmarks/prompts/provider_pubmedqa_mcp_article_local_v1.md
- total runtime seconds: 1689.5
- median seconds per case: 31.03
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 51

### pubmedqa_balanced_51 (pubmedqa_no_tools_v4_open_no_mcp) / claude / sonnet

- tool workflow: none
- prompt path: benchmarks/prompts/provider_pubmedqa_single_v4.md
- total runtime seconds: 1862.2
- median seconds per case: 35.27
- provider error count: 0
- timeout mentions: 0
- quota/capacity mentions: 0
- MCP/tool mentions in raw provider logs: 0


## No-MCP vs MCP Deltas

| Dataset | Provider | Metric | No MCP | MCP | Delta | No MCP sec/case | MCP sec/case | Retrieved PMIDs | Cited PMIDs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pubmedqa | claude | macro F1 | 0.537 | 0.672 | +0.135 | 36.51 | 33.13 | 51 | 51 |

## MCP Experience Signals

### pubmedqa_balanced_51 (pubmedqa_mcp_article_local_v1)

- retrieved PMIDs: 51
- cited PMIDs: 51
- source access counts: {'abstract_only': 51}

| Dimension | Mean Rating |
| --- | ---: |
| citation_support | 7.92 |
| context_quality | 8.20 |
| context_size_control | 8.37 |
| error_recovery | 6.82 |
| latency | 8.06 |
| tool_discoverability | 7.96 |
| workflow_ergonomics | 8.02 |


#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.842 |
| no | 0.810 |
| maybe | 0.364 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 16 | 0 | 1 |
| no | 0 | 17 | 0 |
| maybe | 5 | 8 | 4 |

#### PubMedQA Class Metrics

| Class | F1 |
| --- | ---: |
| yes | 0.780 |
| no | 0.649 |
| maybe | 0.182 |

Confusion matrix rows are gold labels and columns are predictions.

| Gold | yes | no | maybe |
| --- | ---: | ---: | ---: |
| yes | 16 | 0 | 1 |
| no | 2 | 12 | 2 |
| maybe | 6 | 9 | 2 |