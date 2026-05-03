create table if not exists reviews (
    review_id text primary key,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists reviews_updated_at_idx
    on reviews(updated_at);

create table if not exists review_preparation_jobs (
    job_id uuid primary key,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    status text not null,
    queued_at timestamptz not null default now(),
    started_at timestamptz,
    finished_at timestamptz,
    error text,
    unique(review_id, source_id)
);

create index if not exists review_preparation_jobs_status_idx
    on review_preparation_jobs(status);

create table if not exists full_text_retrieval_attempts (
    attempt_id uuid primary key,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    status text not null,
    url text,
    reason text,
    coverage_reason text not null default 'unknown',
    attempt_count integer not null default 1,
    last_status_code integer,
    retry_after_ms integer,
    backoff_ms integer,
    terminal_reason text,
    pmcid text,
    doi text,
    license_or_access_hint text,
    pmc_fallback_available boolean not null default false,
    content_type text,
    content_length bigint,
    created_at timestamptz not null default now()
);

create index if not exists review_attempts_audit_idx
    on full_text_retrieval_attempts(review_id, source_id, source_kind, created_at);

create table if not exists review_passages (
    passage_id text not null,
    review_id text not null references reviews(review_id),
    source_id text not null,
    source_kind text not null,
    pmid text,
    pmcid text,
    doi text,
    url text,
    section text not null,
    heading_path text,
    page integer,
    text text not null,
    entity_ids text[] not null default '{}',
    relation_types text[] not null default '{}',
    screening_status text not null default 'candidate',
    source_metadata jsonb not null default '{}',
    search_vector tsvector generated always as (
        to_tsvector('english', coalesce(heading_path, '') || ' ' || section || ' ' || text)
    ) stored,
    created_at timestamptz not null default now(),
    primary key(review_id, passage_id)
);

create index if not exists review_passages_search_vector_idx
    on review_passages using gin(search_vector);

create index if not exists review_passages_entity_ids_idx
    on review_passages using gin(entity_ids);

create index if not exists review_passages_review_id_idx
    on review_passages(review_id);

create index if not exists review_passages_review_id_pmid_idx
    on review_passages(review_id, pmid);

create index if not exists review_passages_review_id_source_id_idx
    on review_passages(review_id, source_id);

create index if not exists review_passages_review_id_section_idx
    on review_passages(review_id, section);

create table if not exists review_audit_events (
    review_id text not null references reviews(review_id),
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists review_audit_events_review_id_idx
    on review_audit_events(review_id, created_at);

CREATE TABLE IF NOT EXISTS review_llm_context (
    context_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id TEXT NOT NULL REFERENCES reviews(review_id),
    session_id TEXT,
    kind TEXT NOT NULL DEFAULT 'retrieval_context',
    topic TEXT,
    research_question TEXT,
    question_hash TEXT,
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected_pmids TEXT[] NOT NULL DEFAULT '{}',
    rejected_pmids TEXT[] NOT NULL DEFAULT '{}',
    preferred_entity_ids TEXT[] NOT NULL DEFAULT '{}',
    active_queries TEXT[] NOT NULL DEFAULT '{}',
    successful_queries TEXT[] NOT NULL DEFAULT '{}',
    failed_queries TEXT[] NOT NULL DEFAULT '{}',
    selected_passage_ids TEXT[] NOT NULL DEFAULT '{}',
    audit_passage_ids TEXT[] NOT NULL DEFAULT '{}',
    open_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_next_commands JSONB NOT NULL DEFAULT '[]'::jsonb,
    stable_citation_keys JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_key TEXT,
    token_estimate INTEGER,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (context_id, review_id)
);

CREATE TABLE IF NOT EXISTS review_llm_context_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_id UUID NOT NULL,
    review_id TEXT NOT NULL REFERENCES reviews(review_id),
    session_id TEXT,
    event_type TEXT NOT NULL,
    summary TEXT,
    pmids TEXT[] NOT NULL DEFAULT '{}',
    passage_ids TEXT[] NOT NULL DEFAULT '{}',
    queries TEXT[] NOT NULL DEFAULT '{}',
    decision JSONB,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (context_id, review_id)
        REFERENCES review_llm_context(context_id, review_id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_events_review
    ON review_llm_context_events (review_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_review_latest
    ON review_llm_context (review_id, updated_at DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_session_latest
    ON review_llm_context (review_id, session_id, updated_at DESC, created_at DESC);

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

create table if not exists review_session_sources (
    review_id text not null,
    session_id text not null,
    source_id text not null,
    created_at timestamptz not null default now(),
    primary key(review_id, session_id, source_id),
    foreign key(review_id, session_id)
        references review_research_sessions(review_id, session_id)
        on delete cascade,
    foreign key(review_id, source_id)
        references review_preparation_jobs(review_id, source_id)
        on delete cascade
);

create index if not exists review_session_sources_source_idx
    on review_session_sources(review_id, source_id);

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
