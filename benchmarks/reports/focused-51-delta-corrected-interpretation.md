# Corrected 51-Case MCP Delta Interpretation

## What Was Wrong

The earlier 51-case no-MCP baseline was invalid for measuring PubTator-Link MCP
value because the live provider runner injected `case_metadata.abstract_context`
into all prompts. That meant the no-MCP arm received the article abstract
directly, while the MCP arm retrieved the same abstract through
`pubtator_get_publication_passages`.

That comparison measured pasted abstract context versus MCP-retrieved abstract
context. It did not measure model-native capability versus PubTator-Link MCP.

## Correction

The corrected runner now renders:

- no-MCP arm: `case_id` and `question` only; native provider tools such as
  web search may be available; PubTator-Link MCP is blocked.
- MCP arm: `case_id`, `question`, and target PMIDs only; PubTator-Link MCP is
  available; abstracts are not injected.

Gold labels, gold answers, and reference answers still never render into answer
prompts.

## Corrected Result

| Run | Accuracy | Macro F1 | Mean sec/case | Retrieved PMIDs | Cited PMIDs |
| --- | ---: | ---: | ---: | ---: | ---: |
| no-MCP open baseline | 0.588 | 0.537 | 36.51 | 0 | 50 |
| PubTator MCP | 0.725 | 0.672 | 33.13 | 51 | 51 |
| delta | +0.137 | +0.135 | -3.38 | +51 | +1 |

## Class-Level Delta

| Class | no-MCP F1 | MCP F1 | Delta |
| --- | ---: | ---: | ---: |
| yes | 0.780 | 0.842 | +0.062 |
| no | 0.649 | 0.810 | +0.161 |
| maybe | 0.182 | 0.364 | +0.182 |

## Interpretation

After removing abstract injection from the baseline, PubTator-Link MCP shows a
material gain: `+0.135` macro F1 and `+0.137` accuracy on the balanced 51-case
PubMedQA set.

The corrected result is still not the final full MCP value estimate because all
51 MCP-retrieved sources were `abstract_only`. The next benchmark requirement is
a separate full-text-available smoke suite so we can measure the incremental
value of PMC/full-text retrieval.

## Remaining MCP Experience Issues

| Dimension | Corrected Mean Rating | Target |
| --- | ---: | ---: |
| context_size_control | 8.37 | >9.0 |
| context_quality | 8.20 | >9.0 |
| workflow_ergonomics | 8.02 | >9.0 |
| latency | 8.06 | >9.0 |
| tool_discoverability | 7.96 | >9.0 |
| citation_support | 7.92 | >9.0 |
| error_recovery | 6.82 | >9.0 |

The implementation plan to raise every dimension above 9.0 is:
`docs/superpowers/plans/2026-05-09-mcp-experience-over-9-improvement-plan.md`.
