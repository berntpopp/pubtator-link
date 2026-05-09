# Continue MCP Experience Over 9 Prompt

Use this prompt to start the next implementation session.

```text
Repo: /home/bernt-popp/development/pubtator-link

Use superpowers. Read first:
- AGENTS.md
- benchmarks/reports/focused-51-delta-corrected-interpretation.md
- benchmarks/reports/focused-51-delta-corrected-report.md
- docs/superpowers/plans/2026-05-09-mcp-experience-over-9-improvement-plan.md

Goal:
Implement the MCP Experience Over 9 plan task-by-task. The acceptance target is
every LLM MCP-consumer experience dimension >9.0 while preserving deterministic
scoring separate from judge/self-assessment diagnostics.

Important benchmark correction:
The old flat 51-case delta was invalid because abstract_context was injected
into the no-MCP baseline. The corrected runner now renders no-MCP prompts with
question only and allows native provider tools such as web search, while blocking
PubTator-Link MCP. The MCP arm receives question + PMIDs only and must retrieve
evidence through PubTator-Link. Do not reintroduce abstract injection into answer
prompts.

Current corrected 51-case result:
- no-MCP open baseline: accuracy 0.588, macro F1 0.537
- PubTator MCP: accuracy 0.725, macro F1 0.672
- delta: +0.137 accuracy, +0.135 macro F1
- MCP retrieved/cited PMIDs: 51/51
- source access: 51/51 abstract_only

Main MCP experience gaps:
- error_recovery: 6.82
- citation_support: 7.92
- tool_discoverability: 7.96
- workflow_ergonomics: 8.02
- latency: 8.06
- context_quality: 8.20
- context_size_control: 8.37

Implementation order:
1. Use superpowers:subagent-driven-development if appropriate; otherwise use
   superpowers:executing-plans.
2. Follow the saved plan task-by-task with TDD where specified.
3. Start with preflight error recovery and full_abstract mode.
4. Keep raw benchmark outputs ignored under benchmarks/results/ and
   benchmarks/logs/.
5. Do not use Inspect AI or any external evaluation framework.
6. Do not implement sharding, resume, checkpoint merging, or aggregate batch
   semantics.
7. Do not render gold labels, gold answers, reference answers, or abstract
   context into answer prompts.
8. After each task, run the focused verification command from the plan.

Before claiming completion, run:
- uv run pytest tests/unit/benchmarks -q
- uv run pytest tests/unit/test_mcp_errors.py tests/unit/test_publication_passage_service.py -q
- uv run ruff check pubtator_link scripts tests
- make lint
- make typecheck

If PostgreSQL or local environment blocks broader checks, report the exact
blocker and the commands that did run.
```
