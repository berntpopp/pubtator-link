# PubTator-Link Claude MCP Benchmark

This benchmark runs Claude Code repeatedly against the PubTator-Link MCP to
evaluate two things:

1. Whether a strict PubTator-grounded clinical-genetics prompt produces stable,
   cited report text.
2. How Claude, as an MCP consumer, rates PubTator-Link on usability dimensions
   such as speed, context management, discoverability, argument clarity,
   retrieval quality, provenance, diagnostics, and workflow fit.

The benchmark was created during the MEFV recurrent-fever experiment documented
in [`docs/2026-05-02-mefv-claude-mcp-benchmark.md`](docs/2026-05-02-mefv-claude-mcp-benchmark.md).

## Files

- `clinical_prompt.md` - the strict clinical-genetics literature-review prompt.
- `mcp_evaluation_prompt.md` - the second-turn MCP consumer evaluation prompt.
- `judge_prompt.md` - optional LLM-as-judge prompt for summarized artifacts.
- `run_benchmark.sh` - sequential runner for repeated Claude Code sessions.
- `docs/` - curated experiment summaries intended for version control.
- `results/` - ignored raw timestamped outputs, debug logs, and Docker logs.

## Prerequisites

- Claude Code must be installed and authenticated.
- The local Claude MCP config must expose `pubtator-link`.
- Docker Compose should have the PubTator-Link stack running with the MCP
  endpoint reachable, for example at `http://localhost:8011/mcp`.
- `jq` must be installed because the harness extracts Claude session IDs from
  JSON output.

Useful checks:

```bash
claude --version
claude mcp get pubtator-link
docker compose -f docker/docker-compose.yml ps
```

## Running

Run the default 10-session benchmark:

```bash
benchmarks/pubtator_mcp_claude/run_benchmark.sh 10
```

Run a shorter smoke test:

```bash
benchmarks/pubtator_mcp_claude/run_benchmark.sh 1
```

Each run performs:

1. A clinical report turn using only PubTator-Link MCP tools.
2. A resumed-session MCP self-evaluation turn.
3. Per-run Claude debug log capture.
4. Per-run Docker log snapshots.
5. A final summarized evidence bundle and optional judge output.

The harness writes timestamped artifacts under:

```text
benchmarks/pubtator_mcp_claude/results/YYYYMMDDTHHMMSSZ/
```

That directory is intentionally ignored by git.

## Known Harness Issues From The First Experiment

- A Claude process can exit successfully with an empty `result`; `run_04` in the
  first 10-run experiment did this. Future harness work should fail such runs.
- The final judge step originally attempted to pass a large evidence bundle as a
  command-line argument. This can exceed practical CLI limits; use stdin or a
  file path for large judge inputs.
- Docker log snapshots can include stale container history. Use per-run
  timestamp windows or diffs before attributing server-side errors to a specific
  benchmark run.

## Interpreting Results

Do not treat one generated clinical paragraph as a stable answer. Compare runs
for:

- repeated claims and repeated PMIDs,
- unsupported or inferred treatment language,
- whether guideline papers were retrieved at passage level or only through
  secondary summaries,
- empty outputs despite successful process status,
- MCP friction reported repeatedly across evaluation turns.

The first MEFV experiment showed that PubTator-Link's passage provenance was
strong, while MCP ergonomics around list arguments, retrieval naming, enum
normalization, and guideline discovery need improvement.
