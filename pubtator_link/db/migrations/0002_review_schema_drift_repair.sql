alter table reviews add column if not exists updated_at timestamptz;

update reviews set updated_at = coalesce(updated_at, created_at, now())
where updated_at is null;

alter table reviews alter column updated_at set default now();
alter table reviews alter column updated_at set not null;

create index if not exists reviews_updated_at_idx
    on reviews(updated_at);

alter table full_text_retrieval_attempts
    add column if not exists coverage_reason text not null default 'unknown',
    add column if not exists attempt_count integer not null default 1,
    add column if not exists last_status_code integer,
    add column if not exists retry_after_ms integer,
    add column if not exists backoff_ms integer,
    add column if not exists terminal_reason text,
    add column if not exists pmcid text,
    add column if not exists doi text,
    add column if not exists license_or_access_hint text,
    add column if not exists pmc_fallback_available boolean not null default false;

create index if not exists review_attempts_audit_idx
    on full_text_retrieval_attempts(review_id, source_id, source_kind, created_at);

create table if not exists review_audit_events (
    review_id text not null references reviews(review_id),
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists review_audit_events_review_id_idx
    on review_audit_events(review_id, created_at);

create table if not exists review_research_sessions (
    session_id text not null,
    review_id text not null references reviews(review_id),
    query text,
    status text not null default 'active',
    request jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id)
);

create index if not exists review_research_sessions_review_id_idx
    on review_research_sessions(review_id, updated_at);

create table if not exists review_research_session_candidates (
    review_id text not null,
    session_id text not null,
    pmid text not null,
    rank integer,
    title text,
    status text not null,
    decision_reason text not null,
    coverage_hint jsonb,
    source_id text,
    error text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(review_id, session_id, pmid),
    unique(review_id, session_id, pmid),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id)
);

create index if not exists review_research_session_candidates_session_idx
    on review_research_session_candidates(review_id, session_id, rank, pmid);

create unique index if not exists review_research_session_candidates_unique_pmid_idx
    on review_research_session_candidates(review_id, session_id, pmid);

create table if not exists review_evidence_certainty (
    certainty_id uuid primary key,
    review_id text not null references reviews(review_id),
    outcome text not null,
    question text,
    study_design text,
    risk_of_bias_notes text,
    inconsistency_notes text,
    indirectness_notes text,
    imprecision_notes text,
    publication_bias_notes text,
    overall_certainty text not null,
    certainty_rationale text,
    passage_ids text[] not null default '{}',
    unresolved_passage_ids text[] not null default '{}',
    created_by text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists review_evidence_certainty_review_id_idx
    on review_evidence_certainty(review_id, updated_at);
