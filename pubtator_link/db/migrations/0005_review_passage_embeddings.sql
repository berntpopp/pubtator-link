create extension if not exists vector;

create table if not exists review_passage_embeddings (
    review_id text not null,
    passage_id text not null,
    model_name text not null,
    embedding_dim integer not null check (embedding_dim = 384),
    text_hash text not null,
    embedding vector(384) not null,
    created_at timestamptz not null default now(),
    primary key (review_id, passage_id, model_name),
    foreign key (review_id, passage_id)
        references review_passages(review_id, passage_id)
        on delete cascade
);

create index if not exists review_passage_embeddings_lookup_idx
    on review_passage_embeddings(review_id, model_name, passage_id);
