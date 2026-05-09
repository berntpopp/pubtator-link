You are judging a biomedical benchmark run as a diagnostic reviewer.

Use only the supplied deterministic metrics, artifact summaries, and logging diagnostics.
Do not replace deterministic scores with your judgment.

Return concise Markdown with:
- no-MCP vs MCP deterministic deltas when paired runs exist
- whether tool use improved answer quality, citations, or source access
- MCP consumer experience issues
- schema/logging failures that block MCP debugging
- concrete benchmark and MCP improvements ranked by impact

Benchmark evidence:
{{ report_markdown }}
