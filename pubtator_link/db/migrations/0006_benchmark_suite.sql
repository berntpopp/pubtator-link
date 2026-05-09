create extension if not exists pgcrypto;

create table if not exists benchmark_runs (
    run_id text primary key,
    suite text not null,
    dataset text not null,
    dataset_version text not null,
    mode text not null,
    sample_seed integer not null,
    answer_model text,
    self_judge_model text,
    prompt_template_hash text not null,
    prompt_resolved_hash text not null,
    manifest jsonb not null default '{}'::jsonb,
    started_at timestamptz not null default now(),
    completed_at timestamptz
);

create table if not exists benchmark_dataset_cases (
    dataset text not null,
    dataset_version text not null,
    case_id text not null,
    case_payload jsonb not null default '{}'::jsonb,
    primary key(dataset, dataset_version, case_id)
);

create table if not exists benchmark_run_cases (
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    case_id text not null,
    case_order integer not null,
    prompt_context jsonb not null default '{}'::jsonb,
    prompt_resolved_hash text,
    primary key(run_id, case_id)
);

create table if not exists benchmark_predictions (
    prediction_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    case_id text not null,
    prediction jsonb not null default '{}'::jsonb,
    cited_pmids text[] not null default '{}',
    retrieved_pmids text[] not null default '{}',
    cost_source text not null default 'unknown',
    created_at timestamptz not null default now()
);

create table if not exists benchmark_scores (
    score_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    dataset text not null,
    scores jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_pairwise_comparisons (
    comparison_id uuid primary key default gen_random_uuid(),
    left_run_id text references benchmark_runs(run_id) on delete cascade,
    right_run_id text references benchmark_runs(run_id) on delete cascade,
    comparison jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_tool_calls (
    tool_call_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    case_id text,
    tool_name text not null,
    status text not null,
    retrieved_pmids text[] not null default '{}',
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_log_events (
    event_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    event_type text not null,
    tool_name text,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_self_judgments (
    judgment_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    judge_model text not null,
    judgment jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_recommendations (
    recommendation_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    recommendation text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists benchmark_artifacts (
    artifact_id uuid primary key default gen_random_uuid(),
    run_id text not null references benchmark_runs(run_id) on delete cascade,
    artifact_type text not null,
    relative_path text not null,
    sha256 text not null,
    size_bytes bigint not null,
    created_at timestamptz not null default now()
);

create index if not exists benchmark_runs_dataset_suite_mode_seed_idx
    on benchmark_runs(dataset, suite, mode, sample_seed);
create index if not exists benchmark_runs_answer_judge_model_idx
    on benchmark_runs(answer_model, self_judge_model);
create index if not exists benchmark_runs_started_at_idx on benchmark_runs(started_at);
create index if not exists benchmark_run_cases_prompt_hash_idx
    on benchmark_run_cases(prompt_resolved_hash);
create index if not exists benchmark_tool_calls_run_tool_idx
    on benchmark_tool_calls(run_id, tool_name);
create index if not exists benchmark_tool_calls_run_status_idx
    on benchmark_tool_calls(run_id, status);
create index if not exists benchmark_log_events_run_event_type_idx
    on benchmark_log_events(run_id, event_type);
create index if not exists benchmark_log_events_run_tool_idx
    on benchmark_log_events(run_id, tool_name);
create index if not exists benchmark_predictions_cited_pmids_gin_idx
    on benchmark_predictions using gin(cited_pmids);
create index if not exists benchmark_predictions_retrieved_pmids_gin_idx
    on benchmark_predictions using gin(retrieved_pmids);
create index if not exists benchmark_tool_calls_retrieved_pmids_gin_idx
    on benchmark_tool_calls using gin(retrieved_pmids);
create index if not exists benchmark_artifacts_run_type_idx
    on benchmark_artifacts(run_id, artifact_type);

create or replace view benchmark_model_comparisons as
select
    dataset,
    suite,
    mode,
    sample_seed,
    answer_model,
    count(*) as run_count
from benchmark_runs
group by dataset, suite, mode, sample_seed, answer_model;

create or replace view benchmark_paired_comparisons as
select
    c.comparison_id,
    left_run.dataset,
    left_run.suite,
    left_run.sample_seed,
    c.left_run_id,
    c.right_run_id,
    c.comparison
from benchmark_pairwise_comparisons c
join benchmark_runs left_run on left_run.run_id = c.left_run_id
join benchmark_runs right_run on right_run.run_id = c.right_run_id
where left_run.dataset = right_run.dataset
  and left_run.sample_seed = right_run.sample_seed;
