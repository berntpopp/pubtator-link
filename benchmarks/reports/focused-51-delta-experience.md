# Focused 51-Case MCP Delta Experience Notes

## Scope

Claude Sonnet was run on 51 balanced PubMedQA cases with and without
PubTator-Link MCP access. Raw artifacts remain ignored under
`benchmarks/results/focused_51_delta/`.

## Deterministic Delta

| Run | Accuracy | Macro F1 | Mean sec/case | Tool Mentions |
| --- | ---: | ---: | ---: | ---: |
| no MCP | 0.706 | 0.690 | 12.70 | 0 |
| MCP | 0.745 | 0.687 | 33.93 | 51 |
| delta | +0.039 | -0.002 | +21.23 | +51 |

The MCP run improved accuracy by perfectly resolving all `yes` and `no` cases,
but macro F1 was flat because it over-called decisive labels on `maybe` cases.

## Class-Level Effect

| Class | No MCP F1 | MCP F1 | Delta |
| --- | ---: | ---: | ---: |
| yes | 0.800 | 0.872 | +0.072 |
| no | 0.769 | 0.810 | +0.040 |
| maybe | 0.500 | 0.381 | -0.119 |

## MCP Experience Ratings

| Dimension | Mean Rating |
| --- | ---: |
| context_size_control | 8.41 |
| latency | 8.25 |
| context_quality | 8.22 |
| workflow_ergonomics | 8.08 |
| tool_discoverability | 8.00 |
| citation_support | 7.65 |
| error_recovery | 6.78 |

## Source Access

All 51 retrieved sources were `abstract_only`. This run measured article-local
abstract retrieval, citation discipline, and source accounting. It did not
measure full-text value.

## Main Problems

- `preflight_review_sources` intermittently returned `internal_error`, requiring
  manual fallback to `get_publication_passages`.
- The model over-trusted abstract conclusions on ambiguous PubMedQA `maybe`
  cases, reducing `maybe` F1.
- Several notes mention `coverage_confidence=unknown` or
  `coverage_resolution_stage=not_resolved` for articles that ultimately behaved
  as straightforward abstract-only retrieval.
- Deferred tool schema loading introduced minor friction before the first tool
  call in some cases.
- The MCP report still needs a separate full-text-available subset to quantify
  the value of PMC/full-text retrieval.

## Next Actions

- Add a full-text smoke suite using PMIDs known to expose PMC full text.
- Add direct fallback guidance to `preflight_review_sources` errors.
- Improve source coverage metadata for no-PMC/abstract-only cases.
- Add a benchmark metric for `maybe` calibration: decisive-label overcall rate
  on gold `maybe` cases.
