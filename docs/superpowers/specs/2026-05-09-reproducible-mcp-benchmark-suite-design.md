# Reproducible MCP Benchmark Suite Design

## Purpose

PubTator-Link needs a benchmark suite that measures the MCP server as the
target system, not only the answer model. The suite must separate model priors,
prompt effects, retrieval quality, evidence coverage, MCP ergonomics, and final
answer quality.

The first version should turn the existing ignored
`benchmarks/pubtator_mcp_claude/` experiment into a repo-tracked benchmark
framework with fixed seeds, prompt versions, paired baselines, database-backed
run logs, self-judgment, and reproducible summaries.

## Background From Smoke Runs

The design is based on the larger smoke tests run on 2026-05-09:

| Dataset | Mode | Cases | Accuracy | Macro F1 | Runtime | Cost |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| PubMedQA PQA-L | MCP oracle-PMID | 60 | 65.0% | 0.636 | 396.5s | ~$0.65 |
| PubMedQA PQA-L | no tools | 60 | 40.0% | 0.355 | 117.1s | ~$0.22 |
| BioASQ yes/no | MCP oracle-PMID | 40 | 95.0% | 0.950 | 435.8s | ~$0.66 |
| BioASQ yes/no | no tools | 40 | 87.5% | 0.873 | 80.2s | ~$0.11 |

These are single-run point estimates from small smoke samples. They are useful
for shaping the benchmark, not for acceptance gates. The combined accuracy
across PubMedQA and BioASQ is an unweighted mixed-task diagnostic only and must
not be used as a headline quality number.

Additional CLI/model smoke tests on 2026-05-09 confirmed that PubTator-Link can
be consumed by Claude Code, Codex CLI, and Gemini CLI through the same local
Streamable HTTP MCP endpoint. A 10-case PubMedQA PQA-L paired smoke compared
`mcp_oracle_pmid` against `no_tools` for each stack:

| Answer stack | MCP correct | No-tools correct | Delta | MCP runtime | No-tools runtime |
| --- | ---: | ---: | ---: | ---: | ---: |
| Claude Code + `claude-sonnet-4-6` | 7/10 | 4/10 | +30 pp | 68s | 38s |
| Codex CLI + `gpt-5.4` | 8/10 | 2/10 | +60 pp | 39s | 15s |
| Gemini CLI + `gemini-3.1-pro-preview` | 8/10 | 4/10 | +40 pp | 39s | 21s |

The smoke used fixed seed `20260509`, hid gold labels from prompts, hid PMIDs in
the no-tools condition, and verified that no-tools runs made zero MCP calls.
These numbers are directional only at `n=10`, but they prove that the benchmark
must treat the answer stack as `CLI adapter + model + MCP configuration`, not as
model identity alone.

The main observed MCP failure modes were:

- shared `max_chars` batch budgets dropping passages or degrading to title-only
  output,
- metadata-only fallback for PubMedQA cases where abstracts were not returned,
- poor `maybe` recall in PubMedQA,
- long single-session runtime for 40-60 case Claude runs,
- ambiguity between truly missing passages and budget-pressure retryable drops.

Self-judgment from resumed MCP runs scored the PubMedQA MCP experience 7/10 and
BioASQ 8/10. Those absolute scores are diagnostics only and are not acceptance
criteria. The recurring recommendations were auto-splitting large PMID batches,
better budget hints, `pmids_needing_retry`, minimal output mode, and clearer
fallback reasons.

## Goals

- Provide reproducible benchmark runs for PubTator-Link MCP quality.
- Store raw artifacts for audit and normalized database rows for analysis.
- Decompose model prior, evidence value, MCP transport/retrieval effects, and
  open-retrieval value without attributing all evidence gains to the MCP server.
- Make answer-model and judge-model effects explicit and comparable.
- Support deterministic scoring where gold labels exist.
- Support LLM self-judgment for MCP consumer experience and improvement mining.
- Store statistical uncertainty for reported scores and paired comparisons.
- Parse structured MCP server events into queryable run diagnostics, using
  CLI debug or event logs only as a secondary signal.
- Keep smoke runs cheap enough for local pre-release use.
- Keep public hosted MCP benchmark tasks research-use scoped.

## Non-Goals

- Do not make LLM-as-judge the source of truth for PubMedQA or BioASQ labels.
- Do not require paid LLM calls for the default deterministic scorer tests.
- Do not store full article text in the database unless an existing repository
  policy explicitly allows it.
- Do not benchmark clinical decision support or patient-management advice.
- Do not benchmark unauthorized or paywalled full-text access.
- Do not average scores across models by default.
- Do not use self-judgment scores as acceptance criteria.
- Do not claim cross-time reproducibility when the answer model, PubTator API,
  or MCP server image is not snapshot-pinned.

## Benchmark Modes

Each case can run in one or more modes:

- `no_tools`: the answer stack receives only the question and must not use tools.
  This estimates model prior and prompt leakage. For PubMedQA and similar
  oracle-PMID datasets, PMIDs are hidden in this condition.
- `oracle_context`: the answer stack receives gold abstract snippets or
  benchmark-provided context directly, without MCP. This estimates answer-model
  performance when evidence context is already available.
- `mcp_oracle_pmid`: the answer stack receives question plus target or gold
  evidence PMIDs and must use PubTator-Link MCP to retrieve evidence.
- `mcp_open_retrieval`: the answer stack receives only the question or topic and
  must use PubTator-Link MCP to discover evidence.
- `mcp_self_judge`: a resumed run asks the same or another model to evaluate the
  MCP consumer experience from the run trace only.
- `grounding_judge`: optional judged evaluation for synthesis answers where no
  deterministic gold label exists.

## Delta Metrics

The suite should compute these deltas whenever paired runs share dataset,
sample seed, case order, answer model, and prompt version:

- Evidence value: `oracle_context - no_tools`
- MCP oracle-PMID overhead or benefit: `mcp_oracle_pmid - oracle_context`
- Open-retrieval penalty: `mcp_open_retrieval - mcp_oracle_pmid`
- Open-retrieval value over model prior: `mcp_open_retrieval - no_tools`
- MCP-attributable open-retrieval contribution:
  `mcp_open_retrieval - no_tools - evidence_value`
- Answer-model effect: same mode and prompt, different answer models
- Judge-model effect: same candidate outputs, different self or grounding judge
  models
- Cost per correct answer
- Runtime per correct answer

`mcp_oracle_pmid - no_tools` must not be called "MCP lift". It mostly measures
the value of having evidence in context. The MCP server's oracle-PMID
contribution is measured against `oracle_context`, while the MCP server's
real-world value is measured in open retrieval where source discovery is part of
the task.

Paired comparisons must also store:

- Wilson 95% confidence interval for each accuracy,
- paired McNemar p-value for label accuracy deltas,
- bootstrap confidence interval for macro F1,
- minimum detectable effect for the suite size.

## Datasets

### PubMedQA PQA-L

Use PubMedQA for article-local yes/no/maybe classification.

Inputs:

- question,
- target PMID for article-local mode,
- hidden gold label.

Metrics:

- accuracy,
- Wilson 95% confidence interval for accuracy,
- macro F1,
- bootstrap confidence interval for macro F1,
- per-class precision/recall/F1,
- confusion matrix,
- predicted label distribution versus gold label distribution,
- passage coverage rate,
- metadata-only fallback rate.

Special focus:

- `maybe` recall,
- metadata-only overcommitment,
- difference between article-local and evidence-landscape prompts.

PubMedQA has contamination risks because PQA-L labels are derived from article
abstract conclusions and many cases predate frontier-model training cutoffs.
The benchmark therefore needs these variants before making any PubMedQA quality
claim:

- article-local full abstract,
- article-local conclusion-stripped abstract,
- no-tools memorization probe,
- optional publication-year stratification where metadata is available,
- balanced-label smoke sampling for per-class behavior,
- natural-distribution sampling for published-number style reporting.

Balanced-label smoke accuracy is not comparable to published PubMedQA numbers.

### BioASQ

Use BioASQ for yes/no, factoid, and list-style biomedical question answering.

Modes:

- oracle-PMID mode with BioASQ evidence PMIDs,
- later open-retrieval mode.

Metrics:

- yes/no accuracy,
- official BioASQ yes/no macro F1,
- official BioASQ strict and lenient factoid accuracy,
- official BioASQ factoid MRR,
- official BioASQ list precision/recall/F1,
- evidence PMID recall,
- citation/provenance correctness.

The suite must pin the BioASQ edition, task, batch, and split in
`dataset_metadata`. If the official BioASQ evaluation scripts are not vendored
or invoked, summaries must state that scores are internal diagnostics and not
directly comparable to BioASQ leaderboard numbers.

### SciFact-Style Claim Verification

Use SciFact-style cases after PMID mapping is explicit and audited.

Inputs:

- claim,
- required PMIDs or evidence source identifiers,
- gold verdict.

Metrics:

- required evidence recall,
- verdict accuracy,
- scope-limitation detection,
- unsupported or overgeneralized claim count.

SciFact support requires a checked-in mapping file such as
`benchmarks/cases/scifact/pmid_mapping_v1.tsv` with:

- SciFact corpus ID,
- PMID,
- mapping method,
- mapping confidence,
- inclusion or exclusion reason.

Cases are excluded when the gold rationale depends on full-text sentences that
are absent from the PubMed abstract available through PubTator-Link.

### PubTator-Link Review Synthesis Cases

Use curated local cases for realistic MCP-assisted review workflows, including
the existing MEFV/FM F clinical-genetics benchmark pattern.

Metrics:

- required source coverage,
- required claim coverage,
- citation correctness,
- provenance honesty,
- abstract-only overclaiming,
- research-use safety language,
- self-judgment ratings.

## Prompt Versioning

Prompts are immutable once released. New behavior requires a new prompt version.

Initial prompts:

- `answer_pubmedqa_article_local_v1.md`
- `answer_pubmedqa_evidence_landscape_v1.md`
- `answer_bioasq_yesno_v1.md`
- `answer_bioasq_factoid_v1.md`
- `answer_scifact_v1.md`
- `answer_review_synthesis_v1.md`
- `self_judge_mcp_consumer_v1.md`
- `grounding_judge_v1.md`
- `rerank_passages_v1.md`

Every run stores:

- prompt file path,
- prompt version,
- prompt template hash,
- resolved prompt hash after case/model/mode substitution.

New prompt versions are minted only when a benchmark-design change is reviewed
and documented. Old prompt files remain immutable.

## Model Configuration

Model configuration is a first-class benchmark variable. Each run must store:

- answer stack name,
- CLI adapter name,
- CLI version,
- CLI invocation mode,
- CLI config scope and config snapshot hash,
- provider,
- model alias,
- exact model name/version where available,
- dated model snapshot where the provider exposes one,
- model role,
- model settings,
- token counts,
- cost,
- duration.

Supported model roles:

- `answer_model`,
- `self_judge_model`,
- `grounding_judge_model`,
- `rerank_model`.

Supported CLI adapters:

- `claude_code`: Claude Code non-interactive `--print` runner.
- `codex_cli`: Codex CLI `codex exec` runner.
- `gemini_cli`: Gemini CLI headless `--prompt` runner.

Each adapter must normalize its output to the same benchmark record:

- final answer text,
- parsed prediction JSON,
- raw event or debug log path,
- CLI exit status,
- CLI version,
- resolved model name when exposed by the CLI,
- token and cost fields when exposed by the CLI,
- MCP tool call events when exposed by the CLI,
- tool policy or allowlist used for the run.

Adapter-specific notes:

- Claude Code should use `--allowedTools` for MCP runs, `--tools ""` for
  no-tools runs, `--output-format json`, and `--debug-file`.
- Codex CLI should run from a neutral benchmark working directory with
  `--ephemeral`, `--ignore-rules`, `--json`, and `--output-last-message`.
  For no-tools runs, use a config profile or `--ignore-user-config` that removes
  MCP servers while preserving authentication.
- Gemini CLI should use `--allowed-mcp-server-names pubtator-link` for MCP runs,
  `--skip-trust` in headless automation when needed, and a policy file that
  denies all MCP tools for no-tools runs. The benchmark must record the resolved
  model because aliases such as `gemini-3-pro-preview` can resolve to a
  different served model such as `gemini-3.1-pro-preview`.

Reports must label comparisons as answer-stack comparisons unless the same CLI
adapter and prompt wrapper are used. Comparing Claude Code, Codex CLI, and
Gemini CLI mixes model behavior with agent harness behavior, tool discovery,
policy defaults, schema enforcement, and logging differences.

Example run:

```bash
python -m pubtator_link.benchmarks run \
  --suite pubmedqa-smoke \
  --mode mcp_oracle_pmid \
  --answer-stack codex_cli:gpt-5.4 \
  --answer-model gpt-5.4 \
  --self-judge-stack claude_code:claude-opus-4-7 \
  --sample-seed 20260509
```

Comparison rules:

- Do not compare answer models if prompt versions differ.
- Do not compare answer models if sample seeds differ.
- Do not describe different CLI adapters as pure model comparisons.
- Do not compare self-judge models unless they evaluate identical candidate
  outputs and traces.
- Do not average scores across models unless the report explicitly says it is a
  cross-model aggregate.

`model_settings` must include temperature, top_p where available,
max output tokens, tool-choice behavior, and any CLI flags that affect tool use.
If the provider exposes only an alias rather than a dated snapshot, the run is
reproducible only within that provider alias window.

The manifest must also record:

- MCP server git commit,
- dirty worktree flag,
- Docker image ID and digest when running in Docker,
- PubTator API base URL,
- PubTator API health-check payload or status at run start,
- corpus or API snapshot dates returned by MCP tool responses.

## Repository Layout

Add tracked benchmark code and cases under `benchmarks/`, while keeping raw
outputs ignored:

```text
benchmarks/
  README.md
  cases/
    pubmedqa/
      article_local_smoke_30.jsonl
      article_local_eval_300.jsonl
    bioasq/
      yesno_oracle_smoke_40.jsonl
      factoid_oracle_smoke_40.jsonl
    scifact/
      claim_oracle_smoke_30.jsonl
    pubtator_review/
      mefv_guideline_synthesis.yaml
  prompts/
    answer_pubmedqa_article_local_v1.md
    answer_pubmedqa_evidence_landscape_v1.md
    answer_bioasq_yesno_v1.md
    self_judge_mcp_consumer_v1.md
    grounding_judge_v1.md
  runners/
    cli_adapters.py
    run_benchmark.py
    score_pubmedqa.py
    score_bioasq.py
    summarize_run.py
  results/
  logs/
```

`benchmarks/results/` and `benchmarks/logs/` remain gitignored.

Add benchmark support package:

```text
pubtator_link/benchmarks/
  __init__.py
  __main__.py
  cases.py
  cli.py
  log_parser.py
  models.py
  scoring.py
  storage.py
  summaries.py
```

## Artifact Bundle

Each run writes a timestamped artifact directory:

```text
benchmarks/results/2026-05-09T123000Z/
  manifest.json
  cases.jsonl
  gold.jsonl
  predictions.jsonl
  scores.json
  summary.md
  self_judgment.json
  answer_output.json
  answer_events.jsonl
  answer_debug.log
  mcp_server_before.log
  mcp_server_after.log
  docker_ps.txt
  prompt_answer.md
  prompt_self_judge.md
```

`manifest.json` includes:

- run ID,
- suite,
- mode,
- dataset,
- case count,
- sample seed,
- prompt versions and hashes,
- model roles and exact model names,
- answer stack, CLI adapter, CLI version, requested model, and resolved model
  when available,
- CLI config scope and config snapshot hash,
- git commit,
- dirty worktree flag,
- MCP server Docker image ID and digest when available,
- MCP URL,
- PubTator API base URL,
- PubTator API health-check payload or status,
- Docker container IDs,
- start and end timestamps,
- token counts,
- total cost,
- duration,
- artifact file hashes.

## Database Schema

Add benchmark tables through an idempotent migration.

### `benchmark_runs`

One row per benchmark batch.

Fields:

- `run_id uuid primary key`
- `suite text not null`
- `mode text not null`
- `dataset text not null`
- `case_count integer not null`
- `sample_seed integer`
- `status text not null`
- `artifact_dir text not null`
- `git_commit text`
- `dirty_worktree boolean`
- `mcp_url text`
- `started_at timestamptz not null`
- `finished_at timestamptz`
- `duration_ms integer`
- `cost_usd numeric(12,6)`
- `answer_stack text`
- `cli_adapter text`
- `cli_version text`
- `cli_invocation jsonb not null default '{}'::jsonb`
- `cli_config_hash text`
- `cli_config_snapshot jsonb not null default '{}'::jsonb`
- `claude_cli_version text`
- `claude_session_id text`
- `model_provider text`
- `answer_model text`
- `self_judge_model text`
- `grounding_judge_model text`
- `rerank_model text`
- `model_settings jsonb not null default '{}'::jsonb`
- `token_usage jsonb not null default '{}'::jsonb`
- `mcp_server_image_id text`
- `mcp_server_image_digest text`
- `pubtator_api_base_url text`
- `pubtator_api_health jsonb not null default '{}'::jsonb`
- `run_metadata jsonb not null default '{}'::jsonb`

Use UUIDv7 when available so run IDs remain time-sortable.

`claude_cli_version` and `claude_session_id` are retained for backward
compatibility with the first Claude-only experiments. New code should populate
the generic `cli_*` fields for all adapters, including Claude Code.

### `benchmark_dataset_cases`

One canonical row per dataset case version.

Fields:

- `dataset text not null`
- `dataset_version text not null`
- `case_id text not null`
- `question text`
- `target_pmids text[]`
- `gold_label text`
- `gold_answer jsonb`
- `gold_evidence_pmids text[]`
- `case_metadata jsonb not null default '{}'::jsonb`
- primary key `(dataset, dataset_version, case_id)`

Gold fields live here, not in run-scoped prompt context.

### `benchmark_run_cases`

One row per case instance in a run.

Fields:

- `run_id uuid references benchmark_runs(run_id)`
- `dataset text not null`
- `dataset_version text not null`
- `case_id text not null`
- `case_order integer not null`
- `mode text not null`
- `prompt_template_hash text`
- `prompt_resolved_hash text`
- `run_case_metadata jsonb not null default '{}'::jsonb`
- primary key `(run_id, case_id)`

Run cases reference canonical dataset cases. Gold labels are used only by
scorers and must not be rendered into answer prompts.

### `benchmark_predictions`

One row per model prediction.

Fields:

- `run_id uuid references benchmark_runs(run_id)`
- `case_id text`
- `predicted_label text`
- `predicted_answer text`
- `confidence text`
- `evidence_status text`
- `retrieved_pmids text[]`
- `cited_pmids text[]`
- `reason_short text`
- `raw_prediction_json jsonb not null default '{}'::jsonb`
- `is_correct boolean`
- `score_details jsonb not null default '{}'::jsonb`
- primary key `(run_id, case_id)`

### `benchmark_scores`

Aggregate scores per run.

Fields:

- `run_id uuid primary key references benchmark_runs(run_id)`
- `accuracy numeric`
- `accuracy_wilson_ci jsonb`
- `macro_f1 numeric`
- `macro_f1_bootstrap_ci jsonb`
- `precision_by_class jsonb`
- `recall_by_class jsonb`
- `f1_by_class jsonb`
- `confusion_matrix jsonb`
- `retrieval_recall_at_k jsonb`
- `coverage_passage_rate numeric`
- `metadata_only_fallback_rate numeric`
- `json_parse_success_rate numeric`
- `empty_output_count integer`
- `paired_mcnemar_p numeric`
- `minimum_detectable_effect jsonb`
- `score_details jsonb not null default '{}'::jsonb`

### `benchmark_tool_calls`

Normalized tool call records from MCP server logs and CLI debug or event logs.

Fields:

- `id bigserial primary key`
- `run_id uuid references benchmark_runs(run_id)`
- `case_id text`
- `tool_name text`
- `started_at timestamptz`
- `finished_at timestamptz`
- `duration_ms integer`
- `input_summary jsonb not null default '{}'::jsonb`
- `output_summary jsonb not null default '{}'::jsonb`
- `status text`
- `error_code text`
- `retryable boolean`
- `pmids text[]`
- `coverage_summary jsonb not null default '{}'::jsonb`
- `raw_log_ref text`

### `benchmark_log_events`

Normalized log events.

Fields:

- `id bigserial primary key`
- `run_id uuid references benchmark_runs(run_id)`
- `source text not null`
- `logged_at timestamptz`
- `level text`
- `event_type text not null`
- `message text`
- `tool_name text`
- `case_id text`
- `pmid text`
- `error_code text`
- `raw_line text`

Event types include:

- `tool_call_started`
- `tool_call_completed`
- `tool_call_failed`
- `char_budget_exceeded`
- `dropped_passage`
- `metadata_only_fallback`
- `title_only_fallback`
- `no_passages_returned`
- `json_parse_failed`
- `empty_result`
- `retry`
- `rate_limit`
- `timeout`
- `oracle_pmid_missing_in_pubmed`

### `benchmark_self_judgments`

One row per self-judge dimension.

Fields:

- `id bigserial primary key`
- `run_id uuid references benchmark_runs(run_id)`
- `judge_model text not null`
- `judge_prompt_version text not null`
- `dimension text not null`
- `score integer not null`
- `observed_evidence text`
- `recommended_improvement text`
- `raw_judgment_json jsonb not null default '{}'::jsonb`

### `benchmark_recommendations`

Deduplicated improvement ideas.

Fields:

- `id bigserial primary key`
- `run_id uuid references benchmark_runs(run_id)`
- `theme text not null`
- `recommendation text not null`
- `severity text`
- `frequency integer not null default 1`
- `source text not null`
- `linked_event_types text[]`
- `example_case_ids text[]`
- `normalized_text_hash text not null`
- `cluster_id text`

Themes include:

- `context_budgeting`
- `passage_fallback`
- `tool_discoverability`
- `schema_clarity`
- `retrieval_coverage`
- `cost_efficiency`
- `model_sensitivity`

Deduplication uses `(theme, normalized_text_hash)` by default. Normalization
lowercases text, collapses whitespace, strips punctuation that does not affect
meaning, removes run-specific IDs, and preserves technical identifiers such as
tool names and field names. Later implementations may add LLM clustering, but
cluster IDs must be stored explicitly and cannot replace the deterministic hash.

### `benchmark_artifacts`

References to raw files.

Fields:

- `id bigserial primary key`
- `run_id uuid references benchmark_runs(run_id)`
- `artifact_type text not null`
- `path text`
- `relative_path text`
- `sha256 text not null`
- `size_bytes bigint not null`
- `retain_until timestamptz`

`relative_path` is relative to `benchmark_runs.artifact_dir`. `path` is optional
and may be null for content-addressed storage.

Artifact retention is manual by default. `retain_until` lets future cleanup
commands distinguish permanent curated summaries from disposable raw logs.

### Indexes

Minimum indexes:

- `benchmark_runs(dataset, suite, mode, sample_seed)`
- `benchmark_runs(answer_model, self_judge_model)`
- `benchmark_tool_calls(run_id, tool_name)`
- `benchmark_tool_calls(run_id, status)`
- `benchmark_log_events(run_id, event_type)`
- `benchmark_log_events(run_id, tool_name)`
- GIN on `benchmark_predictions(retrieved_pmids)`
- GIN on `benchmark_predictions(cited_pmids)`
- `benchmark_artifacts(run_id, artifact_type)`

## Views

Add a comparison view:

```sql
create view benchmark_model_comparisons as
select
    r.dataset,
    r.suite,
    r.mode,
    r.sample_seed,
    r.answer_stack,
    r.cli_adapter,
    r.answer_model,
    r.self_judge_model,
    s.accuracy,
    s.accuracy_wilson_ci,
    s.macro_f1,
    s.macro_f1_bootstrap_ci,
    s.paired_mcnemar_p,
    s.minimum_detectable_effect,
    r.cost_usd,
    r.duration_ms,
    r.run_id
from benchmark_runs r
join benchmark_scores s using (run_id);
```

## Build Versus Buy

Before implementing the runner, evaluate whether to build on an existing
evaluation framework:

- Inspect AI,
- OpenAI Evals,
- promptfoo,
- lm-eval-harness.

The first implementation may still be in-house because PubTator-Link needs:

- database-backed run logs tied to existing project migrations,
- PubTator-specific coverage and fallback event analysis,
- MCP server structured-event analysis,
- custom paired-mode deltas for MCP attribution,
- strict separation of hidden gold from prompts.

If Inspect AI or another framework can provide model abstraction, trace storage,
or dataset execution without weakening those requirements, the implementation
plan should reuse it rather than duplicating generic runner functionality.

## Runner Flow

1. Resolve suite configuration, sample seed, dataset, mode, prompt versions, and
   model settings.
2. Create artifact directory.
3. Create `benchmark_runs` row with `status="running"`.
4. Write `manifest.json`, prompt copies, cases, and gold files.
5. Capture Docker and MCP server pre-run state.
6. Run the selected CLI adapter with either no tools or explicit MCP tools.
7. Store raw answer output, CLI event streams, and debug logs.
8. Parse predictions and persist `benchmark_predictions`.
9. Score against hidden gold and persist `benchmark_scores`.
10. Parse structured MCP server events into `benchmark_tool_calls` and
    `benchmark_log_events`. Parse CLI debug or event logs only as a secondary
    source for model-side behavior that the server cannot observe.
11. Optionally resume the run for MCP self-judgment and persist
    `benchmark_self_judgments` and `benchmark_recommendations`.
12. Generate `summary.md`.
13. Update `benchmark_runs.status`, duration, token usage, and cost.

## CLI

Initial commands:

```bash
python -m pubtator_link.benchmarks run --suite smoke
python -m pubtator_link.benchmarks analyze --run-id RUN_ID
python -m pubtator_link.benchmarks compare --left RUN_ID --right RUN_ID
python -m pubtator_link.benchmarks judge --run-id RUN_ID --self-judge-model sonnet
```

Important flags:

- `--suite`
- `--mode`
- `--dataset`
- `--sample-seed`
- `--case-count`
- `--sampling-mode` (`balanced` or `natural`)
- `--answer-stack` (`claude_code:claude-sonnet-4-6`, `codex_cli:gpt-5.4`,
  `gemini_cli:gemini-3-pro-preview`)
- `--cli-adapter`
- `--answer-model`
- `--self-judge-stack`
- `--self-judge-model`
- `--grounding-judge-model`
- `--rerank-model`
- `--prompt-version`
- `--mcp-url`
- `--artifact-dir`
- `--no-db`
- `--dry-run`
- `--max-cost-usd`
- `--per-case-timeout`
- `--max-concurrency`
- `--shard`
- `--shard-of`
- `--resume`

The existing project CLI should expose the same functionality as a benchmark
subcommand for discoverability:

```bash
pubtator-link benchmark run --suite smoke
pubtator-link benchmark analyze --run-id RUN_ID
pubtator-link benchmark compare --left RUN_ID --right RUN_ID
```

## Make Targets

Add convenience targets:

```make
benchmark-smoke
benchmark-pubmedqa
benchmark-bioasq
benchmark-analyze
benchmark-compare
benchmark-self-judge
```

Examples:

```bash
make benchmark-smoke ANSWER_STACK=claude_code:claude-sonnet-4-6
make benchmark-smoke ANSWER_STACK=codex_cli:gpt-5.4
make benchmark-smoke ANSWER_STACK=gemini_cli:gemini-3-pro-preview
make benchmark-pubmedqa MODE=mcp_oracle_pmid CASE_COUNT=60
make benchmark-compare LEFT=run_a RIGHT=run_b
```

## Log Evaluation

`benchmark analyze` should compute:

- tool latency percentiles,
- failed tool call counts,
- top repeated log event types,
- PMIDs most often missing passages,
- char-budget drops per run,
- metadata-only fallback rate,
- title-only fallback rate,
- retries per tool,
- JSON parse failure rate,
- empty output rate,
- self-judge low-score dimensions,
- recommendations grouped by theme.

The analyzer should produce both `analysis.json` and a human-readable section in
`summary.md`.

Log analysis depends on structured MCP server events. Before relying on log
analysis in benchmark summaries, PubTator-Link should emit structured events for
the observed failure modes:

- tool call started/completed/failed,
- char budget exceeded,
- dropped passage,
- title-only fallback,
- metadata-only fallback,
- no passages returned,
- retryable budget-pressure drop,
- terminal no-record failure.

CLI debug and event log formats are adapter-specific and may change; they are
useful for audit but must not be the primary source for server-side metrics.

## Self-Judgment Prompt Contract

The self-judgment prompt must be trace-bound:

```text
As an LLM consuming this MCP, evaluate only the PubTator-Link MCP experience
from this run. Do not use web, tools, files, or outside knowledge. Use only your
interaction trace.

Rate each dimension from 1-10:
speed_latency, context_management, tool_discoverability, argument_clarity,
schema_output_clarity, retrieval_quality, citation_provenance_support,
diagnostics_recovery, workflow_fit_biomedical_review,
safety_research_guardrails, token_cost_efficiency, confidence_in_final_answers.

For each dimension return:
score, observed_evidence_from_run, recommended_improvement.

Also return top_5_improvements and overall_score.
Return JSON only.
```

The runner validates JSON output and stores each dimension separately.

Self-judgment is diagnostic. It does not gate benchmark success. If a
self-judge score is used in a report rather than just stored as a diagnostic,
the judge model should be different from the answer model. Cross-run claims
should prefer pairwise trace comparison prompts over absolute 1-10 scores.

## Scoring

### Deterministic Datasets

For PubMedQA and BioASQ yes/no:

- gold-label scoring is authoritative,
- self-judge and grounding-judge outputs cannot override gold scores,
- invalid labels count as incorrect,
- missing predictions count as incorrect and as output failures.

Accuracy reports include Wilson 95% confidence intervals. Paired mode
comparisons include McNemar's test where the same cases were run in both modes.
Macro-F1 reports include bootstrap confidence intervals.

### Retrieval Metrics

For open retrieval:

- target PMID recall@5,
- target PMID recall@10,
- required source recall,
- retrieved evidence coverage,
- full-text versus abstract-only ranking,
- mean reciprocal rank where target sources are ordered.

### Grounding Metrics

For synthesis tasks:

- required claim coverage,
- unsupported claim count,
- citation correctness,
- citation provenance correctness,
- abstract-only overclaiming,
- metadata-only overclaiming,
- forbidden claim violations,
- research-use safety compliance.

## Safety And Data Handling

- Do not store full article text in benchmark database tables by default.
- Store PMIDs, passage IDs, coverage states, short snippets where permitted,
  hashes, and artifact references.
- Keep raw artifacts under gitignored `benchmarks/results/`.
- Public hosted MCP tools remain research-use scoped.
- Do not treat benchmark results as clinical validation.

## Testing Strategy

Unit tests:

- case loading and seed reproducibility,
- prompt hash calculation,
- PubMedQA scoring,
- BioASQ scoring,
- confusion matrix calculation,
- model comparison delta calculation,
- self-judgment JSON parsing,
- log event parser fixtures,
- artifact hashing.

Integration tests:

- database migration creates benchmark tables,
- a synthetic benchmark run persists runs, cases, predictions, scores, and
  artifacts,
- analyzer groups synthetic log events into recommendations,
- compare command reports expected deltas.

No test should require paid LLM calls. Live Claude, Codex, and Gemini runs are
manual benchmark commands, not CI requirements.

## Smoke Suite

Initial local smoke target:

- PubMedQA PQA-L article-local, 30 cases, balanced labels for the default smoke.
- PubMedQA PQA-L article-local, 10 cases, balanced-ish labels, as the
  cross-stack quick smoke for Claude Code, Codex CLI, and Gemini CLI.
- BioASQ yes/no oracle-PMID, 20 cases, balanced labels.
- Modes: `no_tools` and `mcp_oracle_pmid`.
- Answer stacks: at least one canonical Claude Code stack for CI/manual
  continuity; optional local cross-stack smoke with Codex CLI and Gemini CLI
  when credentials are available.
- One self-judgment per MCP run.
- Fixed seed: `20260509`.
- Runtime is measured and reported, not used as a pass/fail gate in the first
  implementation.

Shard semantics:

- `--shard N --shard-of M` runs a deterministic subset of the sampled case list.
- Shards have separate run IDs and artifact directories.
- A merge step creates an aggregate run summary without re-running Claude.
- `--max-concurrency` controls parallel shards and defaults to 1 for local MCP
  stacks.
- Interleaved server logs are attributed by run ID where structured events carry
  run metadata; otherwise they remain run-level diagnostics only.

Smoke pass criteria:

- predictions parse as JSON,
- one prediction per case,
- score file is produced,
- DB rows are written,
- artifact hashes are recorded,
- each no-tools run records zero MCP calls,
- each MCP run records at least one PubTator-Link MCP call unless all cases fail
  before tool discovery,
- summaries report `answer_stack`, `cli_adapter`, requested model, and resolved
  model where available,
- self-judgment dimensions are parsed,
- summary includes paired-mode deltas with confidence information where enough
  paired cases exist,
- cost and timeout controls are enforced.

Safety controls:

- `--max-cost-usd` aborts or prevents additional shards once the configured
  budget would be exceeded.
- `--per-case-timeout` bounds case execution.
- A circuit breaker aborts a run after five consecutive empty outputs or JSON
  parse failures.

## Full Manual Suite

Manual suite target:

- PubMedQA PQA-L article-local, 300 or 500 cases.
- BioASQ yes/no, factoid, and list cases.
- SciFact-style claim verification after PMID mapping audit.
- PubTator-Link review synthesis cases.
- Shard live CLI runs into 20-30 case batches.
- Aggregate batch scores by dataset, mode, answer stack, and model.

## Acceptance Criteria

- A user can run a smoke benchmark and get artifact files plus database rows.
- Gold labels are hidden from answer prompts.
- Paired mode deltas are computed for the same model, prompt version, case set,
  and seed.
- Answer model and judge model are recorded and comparable.
- Self-judgment is stored as structured dimensions and recommendations.
- Tool call and log event analysis identifies common MCP failure modes.
- Results can be compared across commits, models, modes, and prompt versions.
- The smoke summary includes score rows, confidence intervals, artifact hashes,
  parsed self-judgment rows, grouped recommendations, and database IDs.
- Self-judge JSON parses for all required dimensions when self-judgment is
  requested.
- Recommendations are deduplicated and grouped under known themes.
- The MCP-vs-no-tools delta is reported as an observed diagnostic, not as a
  universal acceptance threshold.

## Design Decisions For First Implementation

- Benchmark tables should live in the existing migration path, but the runner
  should treat database persistence as optional. If `PUBTATOR_LINK_DATABASE_URL`
  is unset, the run writes artifacts and `summary.md` only.
- Local benchmark database writes should be enabled automatically when
  `PUBTATOR_LINK_DATABASE_URL` is set, unless the caller passes `--no-db`.
- Raw CLI debug or event logs should be copied into the artifact bundle for
  local runs. The database stores normalized events and artifact references, not
  the full debug log text.
- `oracle_context` should use pre-materialized benchmark case context stored in
  tracked case files or generated artifact files, not live network retrieval
  during the answer run. This keeps the baseline independent of PubTator-Link.
- Live PubMedQA and BioASQ dataset downloaders should be explicit preparation
  commands. Routine smoke runs should use pinned sampled case files checked into
  the repository.
