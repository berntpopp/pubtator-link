# Focused Balanced 10-Case MCP Experience Notes

## Scope

This summarizes the Claude Sonnet MCP-consumer experience from the balanced
10-case PubMedQA smoke run in `benchmarks/results/focused_smoke_balanced10/`.
Raw artifacts remain ignored under `benchmarks/results/`.

## Aggregate Ratings

| Dimension | Mean Rating |
| --- | ---: |
| context_size_control | 8.40 |
| latency | 8.50 |
| context_quality | 8.00 |
| citation_support | 7.90 |
| tool_discoverability | 7.90 |
| workflow_ergonomics | 7.80 |
| error_recovery | 6.50 |

## What Worked

- `get_publication_passages` returned clean passage structures with PMIDs,
  passage IDs, and section labels that supported citation tracing.
- The MCP forced explicit source accounting: 10/10 cases retrieved the target
  PMID and cited the retrieved PMID.
- Abstract fallback was clear enough for most article-local PubMedQA cases.
- Coverage metadata was useful when preflight succeeded, especially
  `abstract_fallback_used` and no-PMC/no-full-text indications.
- Compact mode was generally well calibrated for single-article questions.

## Problems Observed

- `preflight_review_sources` returned `internal_error` on 2/10 cases. The model
  recovered by calling `get_publication_passages` directly, but the fallback was
  manual and not obvious from the tool error.
- All 10 cases were `abstract_only`. This smoke did not exercise full-text
  retrieval or measure full-text value.
- One structured abstract was truncated by the default
  `max_passages_per_pmid=6`, cutting off Results/Conclusion. The model had to
  make a second call with explicit section filters and a higher passage limit.
- Error recovery guidance was rated weakest. The model noted that a suggestion
  to run diagnostics was not useful inside the benchmark task.
- Tool schema discovery had minor friction in one case where deferred tool
  schemas had to be loaded before the workflow was clear.
- One abstract contained an HTML entity (`&lt;`) that created minor evidence
  noise.

## Action Items

- Add a `full_abstract` retrieval mode or raise the default article-local
  passage budget for structured abstracts.
- Make `preflight_review_sources` failure recoverable with a direct fallback
  hint: call `get_publication_passages` with the same PMIDs.
- Include source coverage counts in benchmark summaries so abstract-only versus
  full-text cases are immediately visible.
- Add a targeted smoke set with PMIDs known to have PMC full text, separate from
  the PubMedQA balanced smoke, to measure full-text MCP value directly.
- Improve tool descriptions for the recommended article-local workflow:
  preflight when available, passage retrieval as required fallback, cite only
  retrieved PMIDs.
