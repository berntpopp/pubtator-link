# PubTator-Link Benchmarks

This directory contains tracked benchmark inputs for the in-house PubTator-Link MCP benchmark runner.

Tracked:
- `cases/` pinned case files without hidden gold in rendered prompts
- `prompts/` immutable prompt versions
- `suites/` declarative YAML suite definitions

Ignored:
- `results/` raw run artifacts
- `logs/` raw transient logs

Benchmark outputs are research diagnostics, not clinical validation.

Evidence Inference 2.0 is the next directionality benchmark after the BioASQ ideal-answer smoke suite; it is not implemented in v1.
