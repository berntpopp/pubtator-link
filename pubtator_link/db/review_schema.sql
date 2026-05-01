create table if not exists reviews (
    review_id text primary key,
    created_at timestamptz not null default now()
);

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
