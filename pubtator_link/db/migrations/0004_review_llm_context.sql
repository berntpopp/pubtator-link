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
