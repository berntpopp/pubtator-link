You are an LLM-as-judge evaluating ten Claude Code runs of the same PubTator-Link MCP clinical-literature task.

Use only the files provided in this benchmark directory. Do not use web search or outside biomedical knowledge as evidence. Judge the generated outputs for internal scientific rigor and citation discipline, not whether you know the biomedical topic independently.

Inputs available:
- `runs/run_*/clinical_output.json`: Claude's clinical-report answer.
- `runs/run_*/mcp_evaluation_output.json`: Claude's MCP-consumer evaluation.
- `runs/run_*/clinical.debug.log` and `runs/run_*/mcp_evaluation.debug.log`: Claude debug logs.
- `runs/run_*/docker_*.log`: Docker logs captured around each run.
- `summary/runs.tsv`: timing and exit status.

Assess:
- scientific correctness signals: claim citation density, groundedness audit quality, absence of unsupported recommendations, consistency of PMIDs/metadata within the answer
- overlap between generated texts: recurring claims, recurring PMIDs, recurring source choices
- variability: differences in corpus selection, wording, recommendations, caveats, residual gaps, and audit trails
- MCP experience ratings: score distribution by quality aspect and common complaints
- operational behavior: timing, errors, retries, empty retrievals, Docker-side warnings or failures
- adversarial/self-improvement implications: where the prompt or MCP let weak outputs pass

Produce exactly these sections:
1. Executive summary
2. Run-by-run table
3. Scientific rigor assessment
4. Overlap and variability assessment
5. MCP usability assessment
6. Debug and Docker log assessment
7. Improvement plan, prioritized into P0/P1/P2
8. Suggested next benchmark changes
