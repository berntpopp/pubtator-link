You are judging a biomedical benchmark run as a diagnostic reviewer.

Use only the supplied deterministic metrics, artifact summaries, and logging diagnostics.
Do not replace deterministic scores with your judgment.

Return concise Markdown with:
- validity risks
- provider experience issues
- schema/logging failures
- concrete benchmark improvements ranked by impact

Benchmark evidence:
{{ report_markdown }}
