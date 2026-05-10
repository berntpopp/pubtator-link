# Reproducible MCP Benchmark Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small, executable in-house benchmark suite for PubTator-Link MCP runs with tracked suite/case/prompt inputs, raw artifact bundles, deterministic scoring, database-backed run metadata, and pairwise summaries.

**Architecture:** Add a focused `pubtator_link.benchmarks` package with explicit boundaries for suite loading, case loading, prompt rendering, CLI adapters, artifact writing, scoring, storage, comparisons, and summaries. Keep v1 single-process and single-concurrency, with sharding/resume and Inspect AI out of scope.

**Tech Stack:** Python 3.12, Pydantic v2, Typer-style module CLI or argparse-compatible subcommands, asyncpg migrations, Ruff, mypy, pytest, JSONL/YAML benchmark inputs, gitignored artifact bundles under `benchmarks/results/`.

---

## Context From Inspection

Existing reusable material:

- `benchmarks/pubtator_mcp_claude/run_benchmark.sh` demonstrates artifact conventions: timestamped output directories, prompt copies, Claude JSON output, debug logs, status files, Docker snapshots, and summary inputs.
- `benchmarks/pubtator_mcp_claude/results/20260509T070756Z-pubmedqa-delta-10/` contains useful PubMedQA smoke shapes: `cases_with_gold.json`, `cases_mcp_prompt.json`, `cases_no_tools_prompt.json`, adapter output files, `codex_*.events.jsonl`, and `scores.json`.
- `benchmarks/pubtator_mcp_claude/results/20260509T074458Z-bioasq-ideal-smoke/` contains useful BioASQ ideal-answer smoke shapes: `cases_with_gold.json`, prompt files, `scores.json`, `judge_scores.json`, and a hand-authored `summary.md` showing the source-access and citation metrics v1 should emit.
- `pubtator_link/db/migrate.py` already applies lexical SQL migrations from `pubtator_link/db/migrations/` and tracks versions in `schema_migrations`.
- `pubtator_link/cli.py` is argparse-based and can delegate benchmark subcommands to `pubtator_link.benchmarks.cli`.

Constraints to preserve:

- Do not include Inspect AI.
- Do not implement sharding or resume in v1.
- Deterministic scoring must be separate from judge diagnostics.
- Gold labels and reference answers must never render into answer prompts.
- Source access must distinguish `full_text`, `abstract_only`, `metadata_only`, and `missing`.
- Generated-answer dangerous biomedical error fields must exist in schemas and reports even when v1 deterministic scorers only count structured flags supplied by fixtures or judge diagnostics.
- Evidence Inference 2.0 is planned as the next directionality benchmark after BioASQ ideal-answer smoke, not implemented in v1.

## File Map

Create tracked benchmark inputs:

- `benchmarks/README.md` - benchmark layout, safety scope, and manual run notes.
- `benchmarks/suites/pubmedqa_smoke.yaml` - PubMedQA smoke suite, 30-case target, seed `20260509`, modes `no_tools` and `mcp_oracle_pmid`.
- `benchmarks/suites/bioasq_ideal_smoke.yaml` - BioASQ generated-answer smoke, 3-5 cases, seed `20260509`, modes `no_tools` and `mcp_oracle_pmid`.
- `benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl` - pinned public/open smoke cases adapted from old artifacts for test/manual use.
- `benchmarks/cases/bioasq/ideal_answer_smoke_3.jsonl` - pinned BioASQ ideal-answer smoke cases adapted from old artifacts.
- `benchmarks/prompts/answer_pubmedqa_article_local_v1.md` - JSON-only PubMedQA prompt.
- `benchmarks/prompts/answer_bioasq_ideal_v1.md` - JSON-only generated-answer prompt with citation requirements.
- `benchmarks/prompts/self_judge_mcp_consumer_v1.md` - trace-bound diagnostic self-judge prompt.
- `benchmarks/prompts/grounding_judge_v1.md` - optional frozen-output pairwise prose judge prompt.

Create package code:

- `pubtator_link/benchmarks/__init__.py` - package marker and exported version.
- `pubtator_link/benchmarks/__main__.py` - `python -m pubtator_link.benchmarks` entry point.
- `pubtator_link/benchmarks/models.py` - Pydantic models for suites, cases, prompts, predictions, JSONB payloads, artifacts, scores, comparisons, and self-judgments.
- `pubtator_link/benchmarks/cases.py` - YAML suite loading, JSONL case loading, deterministic sampling, and gold/prompt-context split.
- `pubtator_link/benchmarks/prompts.py` - prompt template loading/rendering and SHA-256 hashing.
- `pubtator_link/benchmarks/adapters.py` - `CliAdapter` protocol plus `ClaudeCodeAdapter`, `CodexCliAdapter`, `GeminiCliAdapter`, and `DryRunAdapter`.
- `pubtator_link/benchmarks/artifacts.py` - timestamped artifact bundle writer, file hashing, manifest writing, and JSON/JSONL helpers.
- `pubtator_link/benchmarks/scoring.py` - PubMedQA, BioASQ generated-answer, citation/source-access, Wilson CI, macro F1, and dangerous-error aggregation.
- `pubtator_link/benchmarks/compare.py` - aligned run comparison models, McNemar counts/p-value, bootstrap CI scaffolding, and pairwise table generation.
- `pubtator_link/benchmarks/storage.py` - asyncpg persistence with JSONB Pydantic validation before insert.
- `pubtator_link/benchmarks/summaries.py` - `summary.md` and `scores.json` generation.
- `pubtator_link/benchmarks/runner.py` - v1 orchestration: load suite, render prompts, call adapter, write artifacts, score, optionally persist.
- `pubtator_link/benchmarks/cli.py` - `run`, `analyze`, `compare`, and `judge` command parsing.
- `pubtator_link/benchmarks/log_parser.py` - v1 parser for Codex JSONL and structured MCP event fixtures; server-side events remain authoritative when present.

Modify existing files:

- `.gitignore` - unignore tracked benchmark inputs and keep `benchmarks/results/` and `benchmarks/logs/` ignored.
- `Makefile` - add benchmark convenience targets and include `benchmarks` in format/lint where Python files exist under package only; no direct formatting of ignored artifacts.
- `pubtator_link/cli.py` - add `pubtator-link benchmark ...` delegation.
- `pubtator_link/db/migrate.py` - extend required schema diagnostics to include benchmark tables after migration.

Database migration:

- Create `pubtator_link/db/migrations/0006_benchmark_suite.sql` with benchmark tables, indexes, and views from the spec.
- Include `create extension if not exists pgcrypto;`.
- Use JSONB defaults and Pydantic `_schema_version` validation in Python before insertion.

Create tests:

- `tests/unit/benchmarks/test_cases.py`
- `tests/unit/benchmarks/test_prompts.py`
- `tests/unit/benchmarks/test_adapters.py`
- `tests/unit/benchmarks/test_artifacts.py`
- `tests/unit/benchmarks/test_scoring_pubmedqa.py`
- `tests/unit/benchmarks/test_scoring_bioasq.py`
- `tests/unit/benchmarks/test_compare.py`
- `tests/unit/benchmarks/test_storage_models.py`
- `tests/unit/benchmarks/test_summaries.py`
- `tests/unit/benchmarks/test_cli.py`
- `tests/unit/test_review_schema_sql.py` additions for benchmark migration surface.
- `tests/integration/test_benchmark_storage_postgres.py`

## Phase 1: Tracked Inputs And Gitignore

### Task 1: Unignore Benchmark Inputs

**Files:**
- Modify: `.gitignore`
- Create: `benchmarks/README.md`
- Create directories: `benchmarks/cases/pubmedqa/`, `benchmarks/cases/bioasq/`, `benchmarks/prompts/`, `benchmarks/suites/`, `benchmarks/results/`, `benchmarks/logs/`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write the failing test**

Add a test asserting benchmark inputs are not globally ignored while raw outputs remain ignored:

```python
def test_gitignore_allows_tracked_benchmark_inputs() -> None:
    text = Path(".gitignore").read_text()
    assert "benchmarks/results/" in text
    assert "benchmarks/logs/" in text
    assert "!benchmarks/cases/**" in text
    assert "!benchmarks/prompts/**" in text
    assert "!benchmarks/suites/**" in text
```

Run: `uv run pytest tests/unit/test_development_tooling.py::test_gitignore_allows_tracked_benchmark_inputs -q`

Expected: FAIL because `.gitignore` currently ignores all `benchmarks/`.

- [ ] **Step 2: Update `.gitignore`**

Replace the broad benchmark ignore with explicit rules:

```gitignore
# benchmark raw artifacts
benchmarks/results/
benchmarks/logs/
benchmarks/**/results/
benchmarks/**/logs/

# tracked benchmark definitions
!benchmarks/
!benchmarks/README.md
!benchmarks/cases/
!benchmarks/cases/**
!benchmarks/prompts/
!benchmarks/prompts/**
!benchmarks/suites/
!benchmarks/suites/**
!benchmarks/pubtator_mcp_claude/
!benchmarks/pubtator_mcp_claude/README.md
!benchmarks/pubtator_mcp_claude/*.md
!benchmarks/pubtator_mcp_claude/*.sh
!benchmarks/pubtator_mcp_claude/docs/
!benchmarks/pubtator_mcp_claude/docs/**
```

- [ ] **Step 3: Add `benchmarks/README.md`**

Include:

```markdown
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
```

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_development_tooling.py::test_gitignore_allows_tracked_benchmark_inputs -q`

Expected: PASS.

## Phase 2: Core Models, Suite Loading, Case Loading

### Task 2: Pydantic Models And JSONB Contracts

**Files:**
- Create: `pubtator_link/benchmarks/__init__.py`
- Create: `pubtator_link/benchmarks/models.py`
- Test: `tests/unit/benchmarks/test_storage_models.py`

- [ ] **Step 1: Write model tests**

Test these behaviors:

```python
def test_jsonb_models_include_schema_version() -> None:
    payload = CliInvocation(command=["claude", "--print"], env_hash="abc")
    assert payload.model_dump()["_schema_version"] == 1

def test_cli_invocation_rejects_string_command() -> None:
    with pytest.raises(ValidationError):
        CliInvocation(command="claude --print", env_hash="abc")

def test_source_access_values_are_closed_enum() -> None:
    assert SourceAccess("abstract_only") == SourceAccess.ABSTRACT_ONLY
    with pytest.raises(ValueError):
        SourceAccess("pdf_only")
```

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py -q`

Expected: FAIL because models do not exist.

- [ ] **Step 2: Implement models**

Define at minimum:

```python
class SourceAccess(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT_ONLY = "abstract_only"
    METADATA_ONLY = "metadata_only"
    MISSING = "missing"

class BenchmarkMode(StrEnum):
    NO_TOOLS = "no_tools"
    ORACLE_CONTEXT = "oracle_context"
    MCP_ORACLE_PMID = "mcp_oracle_pmid"
    MCP_OPEN_RETRIEVAL = "mcp_open_retrieval"

class VersionedJsonModel(BaseModel):
    schema_version: int = Field(default=1, alias="_schema_version")
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

class CliInvocation(VersionedJsonModel):
    command: list[str]
    cwd: str | None = None
    env_hash: str
    timeout_s: int | None = None

class SuiteConfig(BaseModel):
    name: str
    dataset: str
    dataset_version: str
    case_file: Path
    modes: list[BenchmarkMode]
    sample_seed: int
    case_count: int
    sampling_mode: Literal["balanced", "natural"]
    prompt_versions: dict[str, str]
    defaults: SuiteDefaults
```

Also define `BenchmarkCase`, `PromptContext`, `GoldCase`, `PredictionRecord`, `ScoreDetails`, `RunManifest`, `ArtifactRecord`, `PairwiseComparison`, `SelfJudgmentPayload`, `ModelSettings`, `TokenUsage`, `RunMetadata`, `CliConfigSnapshot`, and `PubTatorApiHealth`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py -q`

Expected: PASS.

### Task 3: Suite YAML And Pinned Case Loading

**Files:**
- Create: `pubtator_link/benchmarks/cases.py`
- Create: `benchmarks/suites/pubmedqa_smoke.yaml`
- Create: `benchmarks/suites/bioasq_ideal_smoke.yaml`
- Create: `benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl`
- Create: `benchmarks/cases/bioasq/ideal_answer_smoke_3.jsonl`
- Test: `tests/unit/benchmarks/test_cases.py`

- [ ] **Step 1: Write failing tests**

Test deterministic loading and hidden-gold split:

```python
def test_load_suite_resolves_case_file_from_repo_root() -> None:
    suite = load_suite(Path("benchmarks/suites/pubmedqa_smoke.yaml"))
    assert suite.name == "pubmedqa_smoke"
    assert suite.case_file == Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl")

def test_case_prompt_context_excludes_gold_label() -> None:
    case = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))[0]
    context = case.to_prompt_context(mode=BenchmarkMode.NO_TOOLS)
    assert "gold_label" not in context.model_dump()
    assert context.target_pmids == []

def test_seeded_sampling_is_stable() -> None:
    cases = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))
    assert [c.case_id for c in sample_cases(cases, seed=20260509, count=3)] == [
        "pubmedqa_21618245",
        "pubmedqa_12630042",
        "pubmedqa_24142776",
    ]
```

Run: `uv run pytest tests/unit/benchmarks/test_cases.py -q`

Expected: FAIL.

- [ ] **Step 2: Add pinned cases**

Use the old smoke cases as the source. Each PubMedQA JSONL row includes:

```json
{"dataset":"pubmedqa","dataset_version":"pqa_l_article_local_v1","case_id":"pubmedqa_21618245","question":"Does surgery or radiation therapy impact survival for patients with extrapulmonary small cell cancers?","target_pmids":["21618245"],"gold_label":"yes","gold_answer":{"long_answer":"Although outcomes for EPSCC remains poor, both surgery and radiation is shown to significantly improve median, 5- and 10-year survival rates. EPSCC patients who are potential candidates for surgical resection or radiation therapy may benefit from these treatments."},"gold_evidence_pmids":["21618245"],"dataset_license":"PubMedQA public/open smoke artifact","dataset_use_restriction":"research_use","case_metadata":{"source_artifact":"benchmarks/pubtator_mcp_claude/results/20260509T070756Z-pubmedqa-delta-10/cases_with_gold.json"}}
```

Each BioASQ ideal row includes:

```json
{"dataset":"bioasq_ideal","dataset_version":"jmhb_bioasq_summary_smoke_v1","case_id":"bioasq_532f0511d6d3ac6a34000024","question":"What is the effect of ivabradine in heart failure with preserved ejection fraction?","target_pmids":["23916925","23274284","22833515","21212673","20005474"],"gold_label":null,"gold_answer":{"reference_ideal_answer":"I(f)-channel inhibition potentially exhibits beneficial effects in diastolic heart failure. In patients with heart failure with preserved ejection fraction (HFpEF), short-term treatment with ivabradine increased exercise capacity, with a contribution from improved left ventricular filling pressure response to exercise as reflected by the ratio of peak early diastolic mitral flow velocity to peak early diastolic mitral annular velocity. Ivabradine has demonstrated benefits in HFpEF without improving mortality."},"gold_evidence_pmids":["23916925","23274284","22833515","21212673","20005474"],"dataset_license":"jmhb/BioASQ public Hugging Face mirror smoke artifact","dataset_use_restriction":"research_use","case_metadata":{"source_dataset":"jmhb/BioASQ summary split mirror of BioASQ"}}
```

- [ ] **Step 3: Implement loader**

Implement `load_suite(path)`, `load_cases(path)`, `sample_cases(cases, seed, count)`, and `case.to_prompt_context(mode)` with these rules:

- JSONL parse errors include line number.
- `no_tools` hides `target_pmids` and `gold_evidence_pmids`.
- `mcp_oracle_pmid` exposes target/gold PMIDs but not labels or reference answers.
- v1 balanced sampling groups by `gold_label` when present and falls back to deterministic natural order for generated-answer cases.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_cases.py -q`

Expected: PASS.

## Phase 3: Prompt Rendering And Hashing

### Task 4: Immutable Prompt Files And Renderer

**Files:**
- Create: `benchmarks/prompts/answer_pubmedqa_article_local_v1.md`
- Create: `benchmarks/prompts/answer_bioasq_ideal_v1.md`
- Create: `benchmarks/prompts/self_judge_mcp_consumer_v1.md`
- Create: `benchmarks/prompts/grounding_judge_v1.md`
- Create: `pubtator_link/benchmarks/prompts.py`
- Test: `tests/unit/benchmarks/test_prompts.py`

- [ ] **Step 1: Write failing tests**

```python
def test_prompt_hash_is_sha256_of_template_bytes() -> None:
    path = Path("benchmarks/prompts/answer_pubmedqa_article_local_v1.md")
    template = load_prompt_template(path)
    assert template.template_hash == hashlib.sha256(path.read_bytes()).hexdigest()

def test_render_pubmedqa_prompt_hides_gold() -> None:
    prompt = render_prompt(template_path, prompt_context)
    assert "gold_label" not in prompt.text
    assert "yes" not in prompt.text.lower().split("gold", 1)[-1]
    assert len(prompt.resolved_hash) == 64
```

Run: `uv run pytest tests/unit/benchmarks/test_prompts.py -q`

Expected: FAIL.

- [ ] **Step 2: Add prompts**

PubMedQA prompt requires JSON:

```markdown
You are answering PubMedQA article-local questions for research benchmarking.
Return JSON only:
{"predictions":[{"case_id":"...","predicted_label":"yes|no|maybe","cited_pmids":["..."],"reason_short":"..."}],"friction":[],"confidence":"low|medium|high"}

Cases:
{{ cases_json }}
```

BioASQ ideal prompt requires generated answers and citations:

```markdown
You are answering BioASQ ideal-answer questions for research benchmarking.
Return JSON only:
{"predictions":[{"case_id":"...","predicted_answer":"...","cited_pmids":["..."],"claims":[{"text":"...","cited_pmids":["..."]}]}],"friction":[],"confidence":"low|medium|high"}

Use only evidence available in the current condition. Do not provide clinical advice.
Cases:
{{ cases_json }}
```

- [ ] **Step 3: Implement renderer**

Use simple explicit token replacement for `{{ cases_json }}` and `{{ run_metadata_json }}`. Compute:

- `template_hash = sha256(raw_template_bytes)`
- `resolved_hash = sha256(rendered_prompt_utf8)`

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_prompts.py -q`

Expected: PASS.

## Phase 4: Adapter Boundary And First Executable Adapter

### Task 5: CLI Adapter Interfaces

**Files:**
- Create: `pubtator_link/benchmarks/adapters.py`
- Test: `tests/unit/benchmarks/test_adapters.py`

- [ ] **Step 1: Write failing tests**

```python
def test_parse_answer_stack() -> None:
    stack = parse_answer_stack("codex_cli:gpt-5.4")
    assert stack.adapter == "codex_cli"
    assert stack.model == "gpt-5.4"

def test_dry_run_adapter_returns_one_prediction_per_case() -> None:
    result = DryRunAdapter().run(prompt=prompt, cases=cases, mode=BenchmarkMode.NO_TOOLS)
    assert result.exit_status == 0
    assert [p.case_id for p in result.predictions] == [c.case_id for c in cases]

def test_adapter_registry_exposes_required_adapters() -> None:
    assert set(adapter_registry()) >= {"claude_code", "codex_cli", "gemini_cli", "dry_run"}
```

Run: `uv run pytest tests/unit/benchmarks/test_adapters.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement protocol and adapters**

Define:

```python
class CliAdapter(Protocol):
    name: str
    def version(self) -> str | None: ...
    def run(self, request: AdapterRequest) -> AdapterResult: ...
```

Implement full interface for all three real adapters, but only `DryRunAdapter` and `ClaudeCodeAdapter` need executable v1 behavior. `CodexCliAdapter` and `GeminiCliAdapter` should build normalized command invocations and raise `AdapterNotAvailable` if called before implementation is enabled.

Claude command rules:

- MCP mode uses `claude --print --disable-slash-commands --allowedTools <pubtator tools> --output-format json --debug-file <path> --permission-mode bypassPermissions`.
- No-tools mode uses `claude --print --disable-slash-commands --tools "" --output-format json --debug-file <path> --permission-mode bypassPermissions`.
- Parse `result`, `session_id`, `usage`, `modelUsage`, `total_cost_usd`, and exit status into `AdapterResult`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_adapters.py -q`

Expected: PASS.

## Phase 5: Artifact Bundle Writer

### Task 6: Manifest, JSONL, Hashes, And Summary Files

**Files:**
- Create: `pubtator_link/benchmarks/artifacts.py`
- Test: `tests/unit/benchmarks/test_artifacts.py`

- [ ] **Step 1: Write failing tests**

```python
def test_artifact_writer_records_hashes(tmp_path: Path) -> None:
    writer = ArtifactBundleWriter(root=tmp_path, run_id=UUID(int=1), suite="pubmedqa_smoke")
    writer.write_json("manifest.json", {"run_id": str(UUID(int=1))})
    records = writer.finalize_artifact_records()
    assert records[0].relative_path == "manifest.json"
    assert len(records[0].sha256) == 64

def test_artifact_writer_writes_gold_separately(tmp_path: Path) -> None:
    writer.write_cases(cases)
    assert (writer.path / "cases.jsonl").exists()
    assert (writer.path / "gold.jsonl").exists()
    assert "gold_label" not in (writer.path / "cases.jsonl").read_text()
```

Run: `uv run pytest tests/unit/benchmarks/test_artifacts.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement writer**

Write the v1 bundle:

```text
manifest.json
cases.jsonl
gold.jsonl
predictions.jsonl
scores.json
summary.md
answer_output.json
answer_events.jsonl
answer_debug.log
prompt_answer.md
```

Artifact records include `artifact_type`, `relative_path`, `sha256`, and `size_bytes`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_artifacts.py -q`

Expected: PASS.

## Phase 6: Deterministic Scoring

### Task 7: PubMedQA Metrics

**Files:**
- Create: `pubtator_link/benchmarks/scoring.py`
- Test: `tests/unit/benchmarks/test_scoring_pubmedqa.py`

- [ ] **Step 1: Write failing tests**

```python
def test_pubmedqa_accuracy_macro_f1_and_confusion() -> None:
    scores = score_pubmedqa(gold_cases, predictions)
    assert scores.accuracy == Decimal("0.700000")
    assert scores.confusion_matrix["yes"]["yes"] == 4
    assert "maybe" in scores.f1_by_class

def test_invalid_label_counts_incorrect_and_parse_failure() -> None:
    scores = score_pubmedqa(gold_cases, [PredictionRecord(case_id="x", predicted_label="unclear")])
    assert scores.empty_output_count == 0
    assert scores.score_details.invalid_label_count == 1
```

Run: `uv run pytest tests/unit/benchmarks/test_scoring_pubmedqa.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement PubMedQA scorer**

Implement:

- accuracy
- Wilson 95% CI
- macro F1
- per-class precision/recall/F1
- confusion matrix
- predicted versus gold label distribution
- metadata-only fallback rate from source access details
- `pubmedqa_memorization_risk = "high"` when no-tools accuracy exceeds `0.70`

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_scoring_pubmedqa.py -q`

Expected: PASS.

### Task 8: BioASQ Generated-Answer Smoke Metrics

**Files:**
- Modify: `pubtator_link/benchmarks/scoring.py`
- Test: `tests/unit/benchmarks/test_scoring_bioasq.py`

- [ ] **Step 1: Write failing tests**

```python
def test_bioasq_citation_precision_recall_and_source_access() -> None:
    scores = score_bioasq_ideal(gold_cases, predictions)
    assert scores.score_details["citation_recall"] == 1.0
    assert scores.score_details["citation_precision"] == 1.0
    assert scores.gold_source_access_rate["abstract_only"] == 1.0

def test_dangerous_error_counts_are_separate_from_lexical_scores() -> None:
    scores = score_bioasq_ideal(gold_cases, predictions_with_wrong_direction)
    assert scores.wrong_direction_count == 1
    assert scores.unsupported_claim_count == 1
```

Run: `uv run pytest tests/unit/benchmarks/test_scoring_bioasq.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement generated-answer metrics**

Implement deterministic checks:

- cited PMID exists in candidate output
- citation precision = cited gold PMIDs / cited PMIDs
- citation recall = cited gold PMIDs / required gold PMIDs
- source access rates across required PMIDs
- token F1 and ROUGE-L F1 as weak diagnostics
- unsupported/contradicted/wrong-direction/wrong-endpoint/wrong-comparator/wrong-population/wrong-significance/wrong-measure/scope-inflation counts from structured `PredictionRecord.score_details` flags

Keep any `grounding_judge` or pairwise prose preference output in `self_judgment` or `comparison` records, not in deterministic score authority.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_scoring_bioasq.py -q`

Expected: PASS.

## Phase 7: Database Migration And Storage

### Task 9: Benchmark Migration

**Files:**
- Create: `pubtator_link/db/migrations/0006_benchmark_suite.sql`
- Modify: `pubtator_link/db/migrate.py`
- Modify: `tests/unit/test_review_schema_sql.py`
- Test: `tests/integration/test_benchmark_storage_postgres.py`

- [ ] **Step 1: Write failing schema tests**

Add unit assertions:

```python
def test_benchmark_migration_defines_required_tables() -> None:
    sql = Path("pubtator_link/db/migrations/0006_benchmark_suite.sql").read_text()
    assert "create table if not exists benchmark_runs" in sql.lower()
    assert "create table if not exists benchmark_pairwise_comparisons" in sql.lower()
    assert "create view benchmark_model_comparisons" in sql.lower()

def test_schema_diagnostics_require_benchmark_tables() -> None:
    required = required_review_schema_items()
    assert "benchmark_runs" in required.tables
    assert "benchmark_predictions" in required.tables
```

Run: `uv run pytest tests/unit/test_review_schema_sql.py -q`

Expected: FAIL.

- [ ] **Step 2: Add SQL migration**

Create the tables from the spec:

- `benchmark_runs`
- `benchmark_dataset_cases`
- `benchmark_run_cases`
- `benchmark_predictions`
- `benchmark_scores`
- `benchmark_pairwise_comparisons`
- `benchmark_tool_calls`
- `benchmark_log_events`
- `benchmark_self_judgments`
- `benchmark_recommendations`
- `benchmark_artifacts`

Add indexes:

- `benchmark_runs(dataset, suite, mode, sample_seed)`
- `benchmark_runs(answer_model, self_judge_model)`
- `benchmark_runs(started_at)`
- `benchmark_run_cases(prompt_resolved_hash)`
- `benchmark_tool_calls(run_id, tool_name)`
- `benchmark_tool_calls(run_id, status)`
- `benchmark_log_events(run_id, event_type)`
- `benchmark_log_events(run_id, tool_name)`
- GIN on retrieved/cited PMIDs
- `benchmark_artifacts(run_id, artifact_type)`

Add views:

- `benchmark_model_comparisons`
- `benchmark_paired_comparisons`

- [ ] **Step 3: Update diagnostics**

Add benchmark tables and key JSONB columns to `required_review_schema_items()`.

- [ ] **Step 4: Verify**

Run: `uv run pytest tests/unit/test_review_schema_sql.py tests/integration/test_benchmark_storage_postgres.py -q`

Expected: PASS or integration SKIP when PostgreSQL is unavailable.

### Task 10: Storage Writer With JSONB Validation

**Files:**
- Create: `pubtator_link/benchmarks/storage.py`
- Test: `tests/unit/benchmarks/test_storage_models.py`
- Test: `tests/integration/test_benchmark_storage_postgres.py`

- [ ] **Step 1: Write failing storage tests**

```python
def test_validate_jsonb_rejects_missing_schema_version() -> None:
    with pytest.raises(ValidationError):
        validate_jsonb(CliInvocation, {"command": ["claude"], "env_hash": "abc"})

async def test_synthetic_run_persists_rows(postgres_url: str) -> None:
    storage = BenchmarkStorage(postgres_url)
    await storage.insert_run(manifest)
    await storage.insert_cases(run_id, cases)
    await storage.insert_predictions(run_id, predictions)
    await storage.insert_scores(run_id, scores)
    assert await storage.count_predictions(run_id) == len(predictions)
```

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py tests/integration/test_benchmark_storage_postgres.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement storage**

Use asyncpg inserts with explicit column lists. Before writing any JSONB column, call:

```python
def jsonb_payload(model_type: type[T], payload: T) -> dict[str, Any]:
    return model_type.model_validate(payload.model_dump(by_alias=True)).model_dump(by_alias=True)
```

Successful predictions must have `cost_source` equal to `exact_from_cli` or `estimated_from_tokens`; only failed pre-call run rows may use `unknown`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py tests/integration/test_benchmark_storage_postgres.py -q`

Expected: PASS or integration SKIP when PostgreSQL is unavailable.

## Phase 8: Runner, CLI, Make Targets

### Task 11: Single-Process Runner

**Files:**
- Create: `pubtator_link/benchmarks/runner.py`
- Create: `pubtator_link/benchmarks/cli.py`
- Create: `pubtator_link/benchmarks/__main__.py`
- Modify: `pubtator_link/cli.py`
- Modify: `Makefile`
- Test: `tests/unit/benchmarks/test_cli.py`

- [ ] **Step 1: Write failing CLI tests**

```python
def test_benchmark_cli_dry_run_writes_bundle(tmp_path: Path) -> None:
    exit_code = main([
        "run",
        "--suite",
        "benchmarks/suites/pubmedqa_smoke.yaml",
        "--answer-stack",
        "dry_run:deterministic",
        "--artifact-dir",
        str(tmp_path),
        "--no-db",
        "--dry-run",
    ])
    assert exit_code == 0
    assert next(tmp_path.glob("*/manifest.json")).exists()

def test_v1_rejects_resume_flag() -> None:
    assert main(["run", "--suite", "benchmarks/suites/pubmedqa_smoke.yaml", "--resume"]) == 2
```

Run: `uv run pytest tests/unit/benchmarks/test_cli.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement CLI**

Support:

```bash
python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_smoke.yaml --answer-stack dry_run:deterministic --no-db --dry-run
python -m pubtator_link.benchmarks analyze --run-id RUN_ID
python -m pubtator_link.benchmarks compare --left LEFT --right RIGHT
python -m pubtator_link.benchmarks judge --run-id RUN_ID --self-judge-model MODEL
pubtator-link benchmark run --suite benchmarks/suites/pubmedqa_smoke.yaml
```

Reject `--shard`, `--shard-of`, and `--resume` with a message saying these are v1.1 features.

- [ ] **Step 3: Add Make targets**

Add:

```make
benchmark-smoke:
	uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_smoke.yaml --answer-stack $${ANSWER_STACK:-dry_run:deterministic} $${BENCHMARK_ARGS:-}

benchmark-pubmedqa:
	uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_smoke.yaml --mode $${MODE:-mcp_oracle_pmid} --case-count $${CASE_COUNT:-10} --answer-stack $${ANSWER_STACK:-dry_run:deterministic}

benchmark-bioasq:
	uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/bioasq_ideal_smoke.yaml --answer-stack $${ANSWER_STACK:-dry_run:deterministic}

benchmark-compare:
	uv run python -m pubtator_link.benchmarks compare --left "$${LEFT}" --right "$${RIGHT}"
```

- [ ] **Step 4: Verify**

Run:

```bash
uv run pytest tests/unit/benchmarks/test_cli.py -q
uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_smoke.yaml --answer-stack dry_run:deterministic --no-db --dry-run
```

Expected: tests PASS and a timestamped artifact bundle appears under `benchmarks/results/` or the supplied artifact directory.

## Phase 9: Comparison, Analyzer, Summary

### Task 12: Pairwise Comparison Table

**Files:**
- Create: `pubtator_link/benchmarks/compare.py`
- Test: `tests/unit/benchmarks/test_compare.py`

- [ ] **Step 1: Write failing tests**

```python
def test_pairwise_comparison_requires_aligned_cases() -> None:
    with pytest.raises(ValueError, match="same case order"):
        compare_runs(left_run, right_run_with_different_order)

def test_mcnemar_counts_and_accuracy_delta() -> None:
    comparison = compare_runs(left_run, right_run)
    assert comparison.mcnemar_b == 2
    assert comparison.mcnemar_c == 0
    assert comparison.accuracy_diff == Decimal("0.200000")
```

Run: `uv run pytest tests/unit/benchmarks/test_compare.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement comparison**

Require same:

- dataset
- dataset version
- sample seed
- case order
- prompt version for answer-model comparisons

Store pairwise output in `benchmark_pairwise_comparisons`, not `benchmark_scores`.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_compare.py -q`

Expected: PASS.

### Task 13: Log Parser And Analyze Command

**Files:**
- Create: `pubtator_link/benchmarks/log_parser.py`
- Test: `tests/unit/benchmarks/test_summaries.py`

- [ ] **Step 1: Write failing parser tests**

```python
def test_codex_event_parser_extracts_mcp_tool_calls() -> None:
    events = parse_cli_events(Path("tests/fixtures/benchmarks/codex_mcp.events.jsonl"))
    assert events.tool_calls[0].tool_name == "pubtator_get_publication_passages"
    assert events.tool_calls[0].coverage_summary["abstract_only"] == 10

def test_no_tools_summary_records_zero_mcp_calls() -> None:
    analysis = analyze_events([])
    assert analysis.mcp_tool_call_count == 0
```

Run: `uv run pytest tests/unit/benchmarks/test_summaries.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement parser**

Parse server structured events when present. Parse CLI event/debug logs only as secondary evidence. Normalize these event types:

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

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_summaries.py -q`

Expected: PASS.

### Task 14: Summary Generation

**Files:**
- Create: `pubtator_link/benchmarks/summaries.py`
- Test: `tests/unit/benchmarks/test_summaries.py`

- [ ] **Step 1: Write failing summary tests**

```python
def test_summary_includes_source_access_and_dangerous_errors() -> None:
    text = render_summary(run, scores, analysis)
    assert "Source Access" in text
    assert "abstract_only" in text
    assert "wrong_direction_count" in text

def test_summary_refuses_mixed_dataset_combined_accuracy() -> None:
    with pytest.raises(ValueError, match="mixed datasets"):
        render_combined_summary([pubmedqa_scores, bioasq_scores], combine_mixed_task=False)
```

Run: `uv run pytest tests/unit/benchmarks/test_summaries.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement summary**

Include:

- run ID, suite, dataset, mode, seed
- answer stack, CLI adapter, requested model, resolved model
- prompt template hash and resolved prompt hash
- accuracy, Wilson CI, macro F1 when label scoring exists
- citation recall/precision for generated-answer suites
- source-access rates: `full_text`, `abstract_only`, `metadata_only`, `missing`
- unsupported and contradicted claim counts
- dangerous biomedical error counts
- no-tools MCP call count
- artifact hashes
- database row IDs when persisted
- PubTator drift warning when `run_metadata.dataset_drift_detected` is true
- decomposition components only when required paired runs exist

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_summaries.py -q`

Expected: PASS.

## Phase 10: Self-Judgment Diagnostics Boundary

### Task 15: Self-Judgment Parser

**Files:**
- Modify: `pubtator_link/benchmarks/models.py`
- Modify: `pubtator_link/benchmarks/runner.py`
- Test: `tests/unit/benchmarks/test_storage_models.py`

- [ ] **Step 1: Write failing parser tests**

```python
def test_self_judgment_requires_trace_bound_dimensions() -> None:
    payload = SelfJudgmentPayload.model_validate(raw_payload)
    assert payload.dimensions["argument_clarity"].score == 8
    assert payload.overall_score == 7

def test_self_judgment_rejects_unknown_dimension() -> None:
    raw_payload["dimensions"]["clinical_accuracy"] = {"score": 10}
    with pytest.raises(ValidationError):
        SelfJudgmentPayload.model_validate(raw_payload)
```

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py -q`

Expected: FAIL.

- [ ] **Step 2: Implement parser**

Allow only anchored dimensions from the spec:

- `speed_latency`
- `context_management`
- `tool_discoverability`
- `argument_clarity`
- `schema_output_clarity`
- `retrieval_quality`
- `citation_provenance_support`
- `diagnostics_recovery`
- `workflow_fit_biomedical_review`
- `safety_research_guardrails`
- `token_cost_efficiency`
- `confidence_in_final_answers`

Persist self-judgment rows separately from deterministic scores.

- [ ] **Step 3: Verify**

Run: `uv run pytest tests/unit/benchmarks/test_storage_models.py -q`

Expected: PASS.

## Phase 11: V1 Smoke Verification

### Task 16: End-To-End Dry Run

**Files:**
- Uses all benchmark package files.
- Test: no new test file unless a regression is discovered.

- [ ] **Step 1: Run focused unit tests**

Run:

```bash
uv run pytest tests/unit/benchmarks -q
```

Expected: PASS.

- [ ] **Step 2: Run dry-run PubMedQA smoke**

Run:

```bash
uv run python -m pubtator_link.benchmarks run \
  --suite benchmarks/suites/pubmedqa_smoke.yaml \
  --answer-stack dry_run:deterministic \
  --no-db \
  --dry-run
```

Expected:

- `manifest.json` exists.
- `cases.jsonl` does not contain `gold_label`.
- `gold.jsonl` contains hidden labels.
- `predictions.jsonl`, `scores.json`, and `summary.md` exist.
- summary reports source-access fields and zero MCP calls for no-tools mode.

- [ ] **Step 3: Run dry-run BioASQ ideal smoke**

Run:

```bash
uv run python -m pubtator_link.benchmarks run \
  --suite benchmarks/suites/bioasq_ideal_smoke.yaml \
  --answer-stack dry_run:deterministic \
  --no-db \
  --dry-run
```

Expected:

- citation precision/recall appear in `scores.json`.
- source-access rates appear in `summary.md`.
- dangerous-error count fields appear even when zero.

- [ ] **Step 4: Run local CI**

Run:

```bash
make ci-local
```

Expected: PASS.

## Deferrals And Explicit Non-Scope

Do not implement in v1:

- Inspect AI or any external evaluation framework.
- Sharding, resume, checkpoint merging, or aggregate batch semantics.
- Evidence Inference 2.0 cases. Add a short note in `benchmarks/README.md` that Evidence Inference 2.0 is the next directionality benchmark after BioASQ ideal-answer smoke.
- Full cross-stack live runs in CI. Claude/Codex/Gemini live runs are manual commands gated by local credentials.
- LLM judge scores as deterministic truth. Judge output is diagnostic only.

## Final Verification Commands

Run these before claiming implementation complete:

```bash
uv run pytest tests/unit/benchmarks -q
uv run pytest tests/unit/test_review_schema_sql.py -q
uv run pytest tests/integration/test_benchmark_storage_postgres.py -q
uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/pubmedqa_smoke.yaml --answer-stack dry_run:deterministic --no-db --dry-run
uv run python -m pubtator_link.benchmarks run --suite benchmarks/suites/bioasq_ideal_smoke.yaml --answer-stack dry_run:deterministic --no-db --dry-run
make ci-local
```

Integration tests may skip when PostgreSQL is unavailable. `make ci-local` is still required by repo instructions before completion claims.

## Self-Review

Spec coverage:

- In-house runner: covered by Tasks 5, 11, and 16.
- Suite YAML loading: Task 3.
- Pinned case loading: Task 3.
- Prompt rendering and hashing: Task 4.
- Claude/Codex/Gemini adapter interfaces with simplest first adapter: Task 5.
- Artifact bundle writer: Task 6.
- Deterministic PubMedQA and BioASQ generated-answer scoring: Tasks 7 and 8.
- Source-access and citation metrics: Tasks 8 and 14.
- Pairwise comparison table/design: Task 12 and migration Task 9.
- JSONB Pydantic validation: Tasks 2 and 10.
- Summary generation: Task 14.
- Dangerous biomedical error metrics: Task 8 and Task 14.
- Self-judgment separated from deterministic scoring: Task 15.
- Sharding/resume out of scope: Task 11 and Deferrals.
- Inspect AI excluded: Deferrals.
- Evidence Inference 2.0 next directionality benchmark: Deferrals and README note.

Known implementation risk:

- `.gitignore` currently ignores `benchmarks/`; Task 1 must land first or new tracked benchmark files require forced adds.
- Existing smoke artifacts are ignored raw outputs; copy only small pinned case data into tracked JSONL files and keep raw logs ignored.
- Live CLI adapters should be tested manually, not in CI, because credentials and installed CLIs vary by machine.
