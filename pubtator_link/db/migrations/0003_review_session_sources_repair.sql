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
