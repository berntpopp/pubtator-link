from typing import Any
from uuid import UUID

import pytest

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    PreparationStatus,
    RecordReviewContextRequest,
    ResearchSessionCandidate,
    ReviewIndexInventoryItem,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
)
from pubtator_link.repositories.review_rerag import (
    PostgresReviewReragRepository,
    ReviewPassageEmbeddingRecord,
    ReviewReragRepository,
)


class FakeAcquire:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    async def __aenter__(self) -> "FakeConnection":
        return self.connection

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakePool:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def acquire(self, **_kwargs: Any) -> FakeAcquire:
        return FakeAcquire(self.connection)


class FakeTransaction:
    def __init__(self, calls: list[dict[str, Any]], options: dict[str, Any]) -> None:
        self.calls = calls
        self.options = options

    async def __aenter__(self) -> None:
        self.calls.append(self.options)
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []
        self.fetched_rows: list[dict[str, Any]] = []
        self.fetched_row_batches: list[list[dict[str, Any]]] = []
        self.same_pmid_sample_rows: list[dict[str, Any]] = []
        self.fetchrow_rows: list[dict[str, Any] | None] = []
        self.executemany_calls: list[tuple[str, list[tuple[Any, ...]]]] = []
        self.transaction_calls: list[dict[str, Any]] = []

    def transaction(self, **kwargs: Any) -> FakeTransaction:
        return FakeTransaction(self.transaction_calls, kwargs)

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "EXECUTE"

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.executed.append((sql, args))
        if self.fetchrow_rows:
            return self.fetchrow_rows.pop(0)
        return None

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.executed.append((sql, args))
        if self.fetched_row_batches:
            return self.fetched_row_batches.pop(0)
        if self.same_pmid_sample_rows and "row_number()" in sql.lower():
            if "partition by coalesce(pmid, source_id)" in sql.lower():
                return self.same_pmid_sample_rows[:1]
            return self.same_pmid_sample_rows
        return self.fetched_rows

    async def executemany(self, sql: str, args: list[tuple[Any, ...]]) -> str:
        self.executemany_calls.append((sql, args))
        return "EXECUTEMANY"


@pytest.mark.asyncio
async def test_enqueue_preparation_job_creates_review_and_returns_newly_queued() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [None]
    repository = PostgresReviewReragRepository(FakePool(connection))

    result = await repository.enqueue_preparation_job(
        review_id="review-1",
        source_id="40234174",
        source_kind="pubtator_abstract",
    )

    assert result == "newly_queued"
    assert len(connection.executed) == 3
    assert "insert into reviews" in connection.executed[0][0].lower()
    assert connection.executed[0][1] == ("review-1",)
    status_sql, status_args = connection.executed[1]
    assert "for update" in status_sql.lower()
    assert status_args == ("review-1", "40234174")
    upsert_sql, upsert_args = connection.executed[2]
    assert "insert into review_preparation_jobs" in upsert_sql.lower()
    assert isinstance(upsert_args[0], UUID)
    assert upsert_args[1:] == ("review-1", "40234174", "pubtator_abstract")


@pytest.mark.asyncio
async def test_enqueue_preparation_job_returns_already_indexed_for_terminal_job() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [{"status": "complete"}]
    repository = PostgresReviewReragRepository(FakePool(connection))

    result = await repository.enqueue_preparation_job(
        review_id="review-1",
        source_id="PMID:1",
        source_kind="pubtator_full_bioc",
    )

    assert result == "already_indexed"
    assert not any(
        "insert into review_preparation_jobs" in sql.lower() for sql, _ in connection.executed
    )


@pytest.mark.asyncio
async def test_enqueue_preparation_job_requeues_failed_job() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [{"status": "failed"}]
    repository = PostgresReviewReragRepository(FakePool(connection))

    result = await repository.enqueue_preparation_job(
        review_id="review-1",
        source_id="PMID:1",
        source_kind="pubtator_full_bioc",
    )

    assert result == "previously_failed_requeued"
    assert any("status = 'queued'" in sql.lower() for sql, _ in connection.executed)


@pytest.mark.asyncio
async def test_list_preparation_jobs_by_status_returns_durable_jobs() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "review_id": "review-1",
            "source_id": "PMID:40234174",
            "source_kind": "pubtator_full_bioc",
        },
        {
            "review_id": "review-2",
            "source_id": "URL:https://example.test/paper.pdf",
            "source_kind": "curated_pdf",
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    jobs = await repository.list_preparation_jobs_by_status("queued")

    assert jobs == [
        ("review-1", "PMID:40234174", "pubtator_full_bioc"),
        ("review-2", "URL:https://example.test/paper.pdf", "curated_pdf"),
    ]
    sql, args = connection.executed[0]
    assert "from review_preparation_jobs" in sql.lower()
    assert "where status = $1" in sql.lower()
    assert args == ("queued",)


@pytest.mark.asyncio
async def test_repository_round_trips_research_session() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {
            "review_id": "review-1",
            "session_id": "session-1",
            "query": "FMF colchicine",
            "status": "active",
            "created_at": "2026-05-02T00:00:00Z",
            "updated_at": "2026-05-02T00:01:00Z",
        }
    ]
    connection.fetched_rows = [
        {
            "pmid": "37747561",
            "rank": 1,
            "title": None,
            "status": "queued",
            "decision_reason": "selected_by_rank",
            "coverage_hint": None,
            "source_id": "PMID:37747561",
            "error": None,
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.upsert_research_session(
        review_id="review-1",
        session_id="session-1",
        query="FMF colchicine",
        status="active",
        request={"query": "FMF colchicine"},
    )
    await repository.upsert_research_session_candidate(
        review_id="review-1",
        session_id="session-1",
        candidate=ResearchSessionCandidate(
            pmid="37747561",
            rank=1,
            status="queued",
            decision_reason="selected_by_rank",
            source_id="PMID:37747561",
        ),
    )

    manifest = await repository.get_research_session("review-1", "session-1")

    assert manifest is not None
    assert manifest.review_id == "review-1"
    assert manifest.session_id == "session-1"
    assert manifest.candidate_count == 1
    assert manifest.candidates[0].pmid == "37747561"


@pytest.mark.asyncio
async def test_link_review_session_source_inserts_link() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.link_review_session_source("review-1", "session-1", "PMID:40234174")

    sql, args = connection.executed[0]
    assert "insert into review_session_sources" in sql.lower()
    assert args == ("review-1", "session-1", "PMID:40234174")


@pytest.mark.asyncio
async def test_search_passages_with_session_joins_session_sources() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.search_passages("review-1", "MEFV", session_id="session-1")

    sql, args = connection.executed[0]
    assert "review_session_sources" in sql.lower()
    assert args[7] == "session-1"


@pytest.mark.asyncio
async def test_lookup_and_neighbor_queries_with_session_join_session_sources() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [None]
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.get_passages_by_id("review-1", ["PMID:1:abstract:0"], session_id="session-1")
    await repository.neighboring_passages(
        "review-1",
        "PMID:1:abstract:0",
        before=1,
        after=1,
        same_section=True,
        session_id="session-1",
    )

    lookup_sql, lookup_args = connection.executed[0]
    neighbor_anchor_sql, neighbor_anchor_args = connection.executed[1]
    assert "review_session_sources" in lookup_sql.lower()
    assert lookup_args[2] == "session-1"
    assert "review_session_sources" in neighbor_anchor_sql.lower()
    assert neighbor_anchor_args[2] == "session-1"


@pytest.mark.asyncio
async def test_summary_queries_with_session_join_session_sources() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.list_review_sources("review-1", session_id="session-1")
    await repository.list_review_failed_sources("review-1", session_id="session-1")
    await repository.review_index_totals("review-1", session_id="session-1")
    await repository.available_sections("review-1", session_id="session-1")
    await repository.indexed_pmids("review-1", session_id="session-1")
    await repository.list_review_passage_ids("review-1", session_id="session-1")

    for sql, args in connection.executed:
        assert "review_session_sources" in sql.lower()
        assert "session-1" in args


@pytest.mark.asyncio
async def test_list_research_sessions_groups_candidates_with_bounded_queries() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "review_id": "review-1",
                "session_id": "session-new",
                "query": "new query",
                "status": "active",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:03:00Z",
            },
            {
                "review_id": "review-1",
                "session_id": "session-old",
                "query": "old query",
                "status": "complete",
                "created_at": "2026-05-02T00:00:00Z",
                "updated_at": "2026-05-02T00:01:00Z",
            },
        ],
        [
            {
                "session_id": "session-new",
                "pmid": "37747561",
                "rank": 1,
                "title": "Full text candidate",
                "status": "queued",
                "decision_reason": "selected_by_rank",
                "coverage_hint": {
                    "pmid": "37747561",
                    "expected_coverage": "full_text",
                    "coverage_reason": "full_text_available",
                    "pmc_fallback_available": True,
                    "resolver_attempts": [],
                },
                "source_id": "PMID:37747561",
                "error": None,
            },
            {
                "session_id": "session-new",
                "pmid": "111",
                "rank": 2,
                "title": "Skipped candidate",
                "status": "skipped",
                "decision_reason": "over_candidate_limit",
                "coverage_hint": None,
                "source_id": "PMID:111",
                "error": None,
            },
            {
                "session_id": "session-old",
                "pmid": "222",
                "rank": 1,
                "title": "Abstract candidate",
                "status": "abstract_only",
                "decision_reason": "selected_by_rank",
                "coverage_hint": {
                    "pmid": "222",
                    "expected_coverage": "abstract_only",
                    "coverage_reason": "abstract_fallback_used",
                    "pmc_fallback_available": False,
                    "resolver_attempts": [],
                },
                "source_id": "PMID:222",
                "error": None,
            },
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sessions = await repository.list_research_sessions("review-1")

    assert [session.session_id for session in sessions] == ["session-new", "session-old"]
    assert sessions[0].candidate_count == 2
    assert sessions[0].queued_count == 1
    assert sessions[0].skipped_count == 1
    assert [candidate.pmid for candidate in sessions[0].candidates] == ["37747561", "111"]
    assert sessions[0].coverage_summary == {"full_text": 1, "unknown": 1}
    assert sessions[1].candidate_count == 1
    assert sessions[1].coverage_summary == {"abstract_only": 1}
    assert len(connection.executed) == 2
    assert connection.transaction_calls == [{"isolation": "repeatable_read", "readonly": True}]
    assert all("from review_research_sessions" not in sql for sql, _args in connection.executed[1:])
    assert connection.executed[0][1] == ("review-1",)
    assert connection.executed[1][1] == ("review-1",)


def test_repository_protocol_includes_global_research_session_lookup_methods() -> None:
    assert hasattr(ReviewReragRepository, "list_research_sessions_global")
    assert hasattr(ReviewReragRepository, "find_research_sessions_by_session_id")
    assert hasattr(PostgresReviewReragRepository, "list_research_sessions_global")
    assert hasattr(PostgresReviewReragRepository, "find_research_sessions_by_session_id")


@pytest.mark.asyncio
async def test_list_research_sessions_global_orders_and_groups_candidates() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "review_id": "review-2",
                "session_id": "session-2",
                "query": "new query",
                "status": "active",
                "created_at": "2026-05-02T00:02:00Z",
                "updated_at": "2026-05-02T00:04:00Z",
            },
            {
                "review_id": "review-1",
                "session_id": "session-1",
                "query": "old query",
                "status": "active",
                "created_at": "2026-05-02T00:01:00Z",
                "updated_at": "2026-05-02T00:03:00Z",
            },
        ],
        [
            {
                "review_id": "review-2",
                "session_id": "session-2",
                "pmid": "37747561",
                "rank": 1,
                "title": "Candidate",
                "status": "queued",
                "decision_reason": "selected_by_rank",
                "coverage_hint": None,
                "source_id": "PMID:37747561",
                "error": None,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sessions = await repository.list_research_sessions_global(limit=20)

    assert [session.review_id for session in sessions] == ["review-2", "review-1"]
    assert sessions[0].candidate_count == 1
    assert sessions[0].candidates[0].pmid == "37747561"
    session_sql, session_args = connection.executed[0]
    candidate_sql, candidate_args = connection.executed[1]
    assert "order by updated_at desc, created_at desc" in session_sql.lower()
    assert "limit $1" in session_sql.lower()
    assert "review_research_session_candidates" in candidate_sql.lower()
    assert session_args == (20,)
    assert candidate_args == (20,)


@pytest.mark.asyncio
async def test_find_research_sessions_by_session_id_returns_all_matches() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "review_id": "review-2",
                "session_id": "shared-session",
                "query": "new query",
                "status": "active",
                "created_at": "2026-05-02T00:02:00Z",
                "updated_at": "2026-05-02T00:04:00Z",
            },
            {
                "review_id": "review-1",
                "session_id": "shared-session",
                "query": "old query",
                "status": "active",
                "created_at": "2026-05-02T00:01:00Z",
                "updated_at": "2026-05-02T00:03:00Z",
            },
        ],
        [
            {
                "review_id": "review-1",
                "session_id": "shared-session",
                "pmid": "111",
                "rank": 1,
                "title": "Candidate",
                "status": "queued",
                "decision_reason": "selected_by_rank",
                "coverage_hint": None,
                "source_id": "PMID:111",
                "error": None,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sessions = await repository.find_research_sessions_by_session_id("shared-session")

    assert [session.review_id for session in sessions] == ["review-2", "review-1"]
    assert sessions[1].candidate_count == 1
    assert sessions[1].candidates[0].pmid == "111"
    session_sql, session_args = connection.executed[0]
    candidate_sql, candidate_args = connection.executed[1]
    assert "where session_id = $1" in session_sql.lower()
    assert "order by updated_at desc, created_at desc" in session_sql.lower()
    assert "where session_id = $1" in candidate_sql.lower()
    assert session_args == ("shared-session",)
    assert candidate_args == ("shared-session",)


@pytest.mark.asyncio
async def test_upsert_passages_uses_executemany() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))
    passages = [
        ReviewPassageRow(
            passage_id="PMID:40234174:abstract:0",
            review_id="review-1",
            source_id="40234174",
            source_kind="pubtator_abstract",
            pmid="40234174",
            section="abstract",
            text="Colchicine should start after clinical diagnosis.",
            entity_ids=["MESH:D005201"],
            relation_types=["treats"],
            source_metadata={"rank": 1},
        )
    ]

    await repository.upsert_passages(passages)

    assert len(connection.executemany_calls) == 1
    sql, args = connection.executemany_calls[0]
    assert "insert into review_passages" in sql.lower()
    assert "on conflict (review_id, passage_id)" in sql.lower()
    assert args == [
        (
            "PMID:40234174:abstract:0",
            "review-1",
            "40234174",
            "pubtator_abstract",
            "40234174",
            None,
            None,
            None,
            "abstract",
            None,
            None,
            "Colchicine should start after clinical diagnosis.",
            ["MESH:D005201"],
            ["treats"],
            "candidate",
            '{"rank": 1}',
        )
    ]


@pytest.mark.asyncio
async def test_upsert_passage_embeddings_writes_embedding_records() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.upsert_passage_embeddings(
        [
            ReviewPassageEmbeddingRecord(
                review_id="review-1",
                passage_id="passage-1",
                model_name="BAAI/bge-small-en-v1.5",
                embedding_dim=384,
                text_hash="hash-1",
                embedding=[0.1, 0.2, 0.3],
            )
        ]
    )

    assert len(connection.executemany_calls) == 1
    sql, args = connection.executemany_calls[0]
    assert "insert into review_passage_embeddings" in sql.lower()
    assert "$6::vector" in sql
    assert "on conflict (review_id, passage_id, model_name)" in sql.lower()
    assert args == [
        (
            "review-1",
            "passage-1",
            "BAAI/bge-small-en-v1.5",
            384,
            "hash-1",
            "[0.1,0.2,0.3]",
        )
    ]


@pytest.mark.asyncio
async def test_get_passage_embeddings_returns_vectors_by_passage_id() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {"passage_id": "passage-1", "text_hash": "hash-1", "embedding": [0.1, 0.2]},
        {"passage_id": "passage-2", "text_hash": "hash-2", "embedding": [0.3, 0.4]},
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    embeddings = await repository.get_passage_embeddings(
        "review-1",
        ["passage-1", "passage-2"],
        model_name="BAAI/bge-small-en-v1.5",
    )

    assert embeddings == {"passage-1": [0.1, 0.2], "passage-2": [0.3, 0.4]}
    sql, args = connection.executed[0]
    assert "from review_passage_embeddings" in sql.lower()
    assert args == ("review-1", ["passage-1", "passage-2"], "BAAI/bge-small-en-v1.5")


@pytest.mark.asyncio
async def test_get_passage_embeddings_decodes_pgvector_text_values() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {"passage_id": "passage-1", "text_hash": "hash-1", "embedding": "[0.1,0.2]"}
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    embeddings = await repository.get_passage_embeddings(
        "review-1",
        ["passage-1"],
        model_name="BAAI/bge-small-en-v1.5",
    )

    assert embeddings == {"passage-1": [0.1, 0.2]}


@pytest.mark.asyncio
async def test_get_passage_embeddings_filters_stale_text_hashes() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {"passage_id": "fresh", "text_hash": "hash-fresh", "embedding": [0.1]},
        {"passage_id": "stale", "text_hash": "hash-old", "embedding": [0.9]},
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    embeddings = await repository.get_passage_embeddings(
        "review-1",
        ["fresh", "stale"],
        model_name="BAAI/bge-small-en-v1.5",
        passage_text_hashes={"fresh": "hash-fresh", "stale": "hash-current"},
    )

    assert embeddings == {"fresh": [0.1]}


@pytest.mark.asyncio
async def test_list_passages_missing_embeddings_returns_absent_and_stale_rows() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "passage_id": "missing",
            "review_id": "review-1",
            "source_id": "source-1",
            "source_kind": "pubtator_abstract",
            "pmid": "123",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "abstract",
            "heading_path": None,
            "page": None,
            "text": "new missing text",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0.0,
            "embedding_text_hash": None,
        },
        {
            "passage_id": "stale",
            "review_id": "review-1",
            "source_id": "source-2",
            "source_kind": "pubtator_abstract",
            "pmid": "456",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "results",
            "heading_path": None,
            "page": None,
            "text": "current stale text",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0.0,
            "embedding_text_hash": "old-hash",
        },
        {
            "passage_id": "fresh",
            "review_id": "review-1",
            "source_id": "source-3",
            "source_kind": "pubtator_abstract",
            "pmid": "789",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "discussion",
            "heading_path": None,
            "page": None,
            "text": "fresh text",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0.0,
            "embedding_text_hash": (
                "06b05fe41cba3c2910b5069a680d10827f9a8bc13dc16a9cb583ba58f35b276a"
            ),
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    rows = await repository.list_passages_missing_embeddings(
        "review-1",
        model_name="BAAI/bge-small-en-v1.5",
        limit=50,
    )

    assert [row.passage_id for row in rows] == ["missing", "stale"]
    sql, args = connection.executed[0]
    assert "left join review_passage_embeddings" in sql.lower()
    assert args == ("review-1", "BAAI/bge-small-en-v1.5", 50)


@pytest.mark.asyncio
async def test_search_passages_maps_rows_and_uses_none_for_empty_filters() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "passage_id": "PMID:40234174:abstract:0",
            "review_id": "review-1",
            "source_id": "40234174",
            "source_kind": "pubtator_abstract",
            "pmid": "40234174",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "abstract",
            "heading_path": None,
            "page": None,
            "text": "Colchicine should start after clinical diagnosis.",
            "entity_ids": ["MESH:D005201"],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {"source": "pubtator"},
            "lexical_rank": 0.23,
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    rows = await repository.search_passages(
        review_id="review-1",
        query="when start colchicine",
        entity_ids=[],
        pmids=[],
        sections=[],
        limit=8,
    )

    assert rows == [
        ReviewPassageRow(
            passage_id="PMID:40234174:abstract:0",
            review_id="review-1",
            source_id="40234174",
            source_kind="pubtator_abstract",
            pmid="40234174",
            section="abstract",
            text="Colchicine should start after clinical diagnosis.",
            entity_ids=["MESH:D005201"],
            source_metadata={"source": "pubtator"},
            lexical_rank=0.23,
        )
    ]
    sql, args = connection.executed[0]
    assert "websearch_to_tsquery" in sql
    assert "source_kind" in sql
    assert args == (
        "review-1",
        "when start colchicine",
        None,
        None,
        None,
        8,
        "when | start | colchicine",
        None,
        ["when", "start", "colchicine"],
    )


@pytest.mark.asyncio
async def test_claim_preparation_job_claims_queued_job_with_short_advisory_lock() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [{"job_id": UUID("00000000-0000-0000-0000-000000000001")}]
    repository = PostgresReviewReragRepository(FakePool(connection))

    claimed = await repository.claim_preparation_job(
        review_id="review-1",
        source_id="PMID:40234174",
    )

    assert claimed is True
    assert connection.transaction_calls == [{}]
    lock_sql, lock_args = connection.executed[0]
    assert "pg_advisory_xact_lock" in lock_sql
    assert lock_args == ("review-1:PMID:40234174",)
    claim_sql, claim_args = connection.executed[1]
    normalized_claim_sql = " ".join(claim_sql.lower().split())
    assert "update review_preparation_jobs" in normalized_claim_sql
    assert "set status = 'running'" in normalized_claim_sql
    assert "error = null" in normalized_claim_sql
    assert "where review_id = $1 and source_id = $2 and status = 'queued'" in (normalized_claim_sql)
    assert "returning job_id" in normalized_claim_sql
    assert claim_args == ("review-1", "PMID:40234174")
    touch_sql, touch_args = connection.executed[2]
    assert "update reviews" in touch_sql.lower()
    assert touch_args == ("review-1",)


@pytest.mark.asyncio
async def test_claim_preparation_job_returns_false_when_job_is_not_queued() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [None]
    repository = PostgresReviewReragRepository(FakePool(connection))

    claimed = await repository.claim_preparation_job(
        review_id="review-1",
        source_id="PMID:40234174",
    )

    assert claimed is False
    assert connection.transaction_calls == [{}]
    assert len(connection.executed) == 2


@pytest.mark.asyncio
async def test_search_passages_uses_relaxed_or_query_for_candidate_recall() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.search_passages(
        review_id="review-1",
        query="Should colchicine start after clinical diagnosis of FMF in children?",
        entity_ids=[],
        pmids=[],
        sections=[],
        limit=8,
    )

    sql, args = connection.executed[0]
    normalized_sql = " ".join(sql.split())
    assert "strict_query" in sql
    assert "phrase_query" in sql
    assert "recall_query" in sql
    assert "phraseto_tsquery" in sql
    assert "websearch_to_tsquery" in sql
    assert "to_tsquery('english', $7)" in sql
    assert "search_vector @@ query.phrase_query" in normalized_sql
    assert "search_vector @@ query.strict_query" in normalized_sql
    assert "search_vector @@ query.recall_query" in normalized_sql
    assert "recall_overlap_count" in normalized_sql
    assert "char_length(text)" in normalized_sql
    assert args[-3] == "should | colchicine | start | after | clinical | diagnosis | fmf | children"
    assert args[-1] == [
        "should",
        "colchicine",
        "start",
        "after",
        "clinical",
        "diagnosis",
        "fmf",
        "children",
    ]


@pytest.mark.asyncio
async def test_list_review_sources_aggregates_jobs_attempts_passages_and_samples() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "111",
                "pmid": "111",
                "source_kind": "pubtator_abstract",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["abstract"],
                "passage_count": 2,
                "char_count": 30,
                "coverage_reason": "abstract_fallback_used",
                "pmcid": "PMC123",
                "doi": "10.1000/example",
                "license_or_access_hint": "oa",
                "pmc_fallback_available": True,
                "resolver_attempts": [
                    {
                        "source_kind": "pubtator_full_bioc",
                        "status": "not_available",
                        "attempt_count": 2,
                        "last_status_code": 503,
                        "pmid": "111",
                        "pmcid": "PMC123",
                        "doi": "10.1000/example",
                    }
                ],
            }
        ],
        [
            {
                "source_id": "111",
                "passage_id": "p1",
                "section": "abstract",
                "text": "Indexed passage.",
                "char_count": 16,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources(
        "review-1",
        pmids=["111"],
        include_passage_samples=True,
        sample_per_pmid=1,
    )

    assert sources == [
        ReviewSourceSummary(
            source_id="111",
            pmid="111",
            source_kind="pubtator_abstract",
            job_status="complete",
            attempt_statuses=["success"],
            sections=["abstract"],
            passage_count=2,
            char_count=30,
            coverage="abstract_only",
            coverage_reason="abstract_fallback_used",
            pmcid="PMC123",
            doi="10.1000/example",
            license_or_access_hint="oa",
            pmc_fallback_available=True,
            resolver_attempts=[
                {
                    "source_kind": "pubtator_full_bioc",
                    "status": "not_available",
                    "attempt_count": 2,
                    "last_status_code": 503,
                    "pmid": "111",
                    "pmcid": "PMC123",
                    "doi": "10.1000/example",
                }
            ],
            sample_passages=[
                ReviewPassageSample(
                    passage_id="p1",
                    section="abstract",
                    text="Indexed passage.",
                    char_count=16,
                )
            ],
            sample_warning="Only short sample passages were available for this PMID.",
        )
    ]
    summary_sql, summary_args = connection.executed[0]
    sample_sql, sample_args = connection.executed[1]
    assert "review_preparation_jobs" in summary_sql
    assert "full_text_retrieval_attempts" in summary_sql
    assert "review_passages" in summary_sql
    assert summary_args == ("review-1", ["111"], None, None, 0)
    assert "row_number()" in sample_sql.lower()
    assert sample_args == ("review-1", ["111"], ["111"], 1, "evidence_first", 80, None)


@pytest.mark.asyncio
async def test_list_review_sources_applies_limit_and_offset() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "source_id": "222",
            "pmid": "222",
            "source_kind": "pubtator_abstract",
            "job_status": "complete",
            "error": None,
            "attempt_statuses": ["success"],
            "sections": ["abstract"],
            "passage_count": 1,
            "char_count": 20,
            "coverage_reason": "abstract_fallback_used",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources("review-1", limit=1, offset=1)
    _sql, args = connection.executed[0]

    assert [source.pmid for source in sources] == ["222"]
    assert args[-2:] == (1, 1)


@pytest.mark.asyncio
async def test_list_review_sources_prefers_informative_non_stub_samples() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "PMID:33454820",
                "pmid": "33454820",
                "source_kind": "pubtator_abstract",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["Background", "abstract"],
                "passage_count": 2,
                "char_count": 120,
            }
        ],
        [
            {
                "source_id": "PMID:33454820",
                "passage_id": "PMID:33454820:abstract:0",
                "section": "abstract",
                "text": "Familial Mediterranean fever is a clinically diagnosed autoinflammatory disease with MEFV-associated genetic findings.",
                "char_count": 113,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources(
        "review-samples",
        include_passage_samples=True,
        sample_per_pmid=1,
        min_sample_chars=80,
        sample_section_policy="evidence_first",
    )

    assert sources[0].sample_passages[0].passage_id == "PMID:33454820:abstract:0"
    assert sources[0].sample_warning is None
    sample_sql, sample_args = connection.executed[1]
    normalized_sql = " ".join(sample_sql.split())
    assert "char_length(text)" in sample_sql
    assert "abstract" in sample_sql
    assert "results" in sample_sql
    assert "order by" in normalized_sql
    assert sample_args == (
        "review-samples",
        None,
        ["PMID:33454820"],
        1,
        "evidence_first",
        80,
        None,
    )


@pytest.mark.asyncio
async def test_list_review_sources_warns_when_only_stub_samples_exist() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "PMID:33454820",
                "pmid": "33454820",
                "source_kind": "pubtator_abstract",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["Background"],
                "passage_count": 1,
                "char_count": 10,
            }
        ],
        [
            {
                "source_id": "PMID:33454820",
                "passage_id": "PMID:33454820:background:0",
                "section": "Background",
                "text": "Background",
                "char_count": 10,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources(
        "review-stub-samples",
        include_passage_samples=True,
        sample_per_pmid=1,
        min_sample_chars=80,
        sample_section_policy="evidence_first",
    )

    assert sources[0].sample_passages[0].text == "Background"
    assert sources[0].sample_warning == "Only short sample passages were available for this PMID."


@pytest.mark.asyncio
async def test_list_review_sources_original_order_uses_passage_id_not_section() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "PMID:33454820",
                "pmid": "33454820",
                "source_kind": "pubtator_abstract",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["z-section", "a-section"],
                "passage_count": 2,
                "char_count": 200,
            }
        ],
        [
            {
                "source_id": "PMID:33454820",
                "passage_id": "PMID:33454820:z-section:0",
                "section": "z-section",
                "text": "Original first passage.",
                "char_count": 24,
            }
        ],
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.list_review_sources(
        "review-original-order",
        include_passage_samples=True,
        sample_per_pmid=1,
        sample_section_policy="original_order",
    )

    sample_sql, _sample_args = connection.executed[1]
    normalized_sql = " ".join(sample_sql.split())
    assert "when $5::text = 'evidence_first' then section else '' end" in normalized_sql
    assert "when $5::text = 'evidence_first' then null else created_at end, passage_id" in (
        normalized_sql
    )


@pytest.mark.asyncio
async def test_list_review_sources_infers_full_text_coverage_from_sections() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "111",
                "pmid": "111",
                "source_kind": "pmc_bioc",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["abstract", "results"],
                "passage_count": 2,
                "char_count": 300,
            }
        ]
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources("review-1")

    assert sources[0].coverage == "full_text"


@pytest.mark.asyncio
async def test_get_passages_by_id_returns_requested_order() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "passage_id": "p1",
            "review_id": "review-1",
            "source_id": "s1",
            "source_kind": "pubtator_abstract",
            "pmid": "111",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "abstract",
            "heading_path": None,
            "page": None,
            "text": "one",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0,
        },
        {
            "passage_id": "p2",
            "review_id": "review-1",
            "source_id": "s1",
            "source_kind": "pubtator_abstract",
            "pmid": "111",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "abstract",
            "heading_path": None,
            "page": None,
            "text": "two",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0,
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    rows = await repository.get_passages_by_id("review-1", ["p2", "missing", "p1"])

    assert [row.passage_id for row in rows] == ["p2", "p1"]
    sql, args = connection.executed[0]
    assert "passage_id = any($2::text[])" in sql
    assert args == ("review-1", ["p2", "missing", "p1"], None)


@pytest.mark.asyncio
async def test_neighboring_passages_fetches_anchor_and_same_section_window() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {
            "passage_id": "p2",
            "review_id": "review-1",
            "source_id": "s1",
            "source_kind": "pubtator_abstract",
            "pmid": "111",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "results",
            "heading_path": None,
            "page": None,
            "text": "anchor",
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0,
        }
    ]
    connection.fetched_rows = [
        {
            "passage_id": passage_id,
            "review_id": "review-1",
            "source_id": "s1",
            "source_kind": "pubtator_abstract",
            "pmid": "111",
            "pmcid": None,
            "doi": None,
            "url": None,
            "section": "results",
            "heading_path": None,
            "page": None,
            "text": passage_id,
            "entity_ids": [],
            "relation_types": [],
            "screening_status": "candidate",
            "source_metadata": {},
            "lexical_rank": 0,
        }
        for passage_id in ["p1", "p2", "p3", "p4"]
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    rows = await repository.neighboring_passages(
        "review-1",
        passage_id="p2",
        before=1,
        after=1,
        same_section=True,
    )

    assert [row.passage_id for row in rows] == ["p1", "p2", "p3"]
    assert len(connection.executed) == 2
    assert "section = $4" in connection.executed[1][0]


@pytest.mark.asyncio
async def test_list_review_sources_caps_samples_per_pmid_across_sources() -> None:
    connection = FakeConnection()
    connection.fetched_row_batches = [
        [
            {
                "source_id": "pubtator-111",
                "pmid": "111",
                "source_kind": "pubtator_abstract",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["abstract"],
                "passage_count": 1,
                "char_count": 15,
            },
            {
                "source_id": "pmc-111",
                "pmid": "111",
                "source_kind": "pmc_bioc",
                "job_status": "complete",
                "error": None,
                "attempt_statuses": ["success"],
                "sections": ["results"],
                "passage_count": 1,
                "char_count": 14,
            },
        ]
    ]
    connection.same_pmid_sample_rows = [
        {
            "source_id": "pubtator-111",
            "passage_id": "p1",
            "section": "abstract",
            "text": "First passage.",
            "char_count": 14,
        },
        {
            "source_id": "pmc-111",
            "passage_id": "p2",
            "section": "results",
            "text": "Second passage.",
            "char_count": 15,
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    sources = await repository.list_review_sources(
        "review-1",
        pmids=["111"],
        include_passage_samples=True,
        sample_per_pmid=1,
    )

    assert sum(len(source.sample_passages) for source in sources) == 1
    assert sources[0].sample_passages[0].passage_id == "p1"
    assert sources[1].sample_passages == []


@pytest.mark.asyncio
async def test_list_review_sources_derives_pmid_from_prefixed_source_ids() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.list_review_sources("review-1", pmids=["40234174"])

    sql, args = connection.executed[0]
    assert "PMID:(.+)$" in sql
    assert "s.pmid = any($2::text[])" in sql
    assert args == ("review-1", ["40234174"], None, None, 0)


@pytest.mark.asyncio
async def test_list_review_failed_sources_includes_failure_reasons() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "source_id": "222",
            "pmid": "222",
            "source_kind": "pubtator_full_bioc",
            "job_status": "failed",
            "error": "not available",
            "attempt_statuses": ["not_available"],
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    failed_sources = await repository.list_review_failed_sources("review-1")

    assert failed_sources == [
        FailedSourceSummary(
            source_id="222",
            pmid="222",
            source_kind="pubtator_full_bioc",
            job_status="failed",
            error="not available",
            attempt_statuses=["not_available"],
        )
    ]
    sql, args = connection.executed[0]
    assert "review_preparation_jobs" in sql
    assert "full_text_retrieval_attempts" in sql
    assert "reason" in sql
    assert args == ("review-1", None, None, 0)


@pytest.mark.asyncio
async def test_list_review_failed_sources_applies_limit_and_offset() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "source_id": "222",
            "pmid": "222",
            "source_kind": "pubtator_full_bioc",
            "job_status": "failed",
            "error": "not available",
            "attempt_statuses": ["failed"],
            "coverage_reason": "upstream_404",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        },
        {
            "source_id": "333",
            "pmid": "333",
            "source_kind": "pubtator_full_bioc",
            "job_status": "failed",
            "error": "not available",
            "attempt_statuses": ["failed"],
            "coverage_reason": "upstream_404",
            "pmcid": None,
            "doi": None,
            "license_or_access_hint": None,
            "pmc_fallback_available": False,
            "resolver_attempts": [],
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    failed = await repository.list_review_failed_sources("review-1", limit=2, offset=1)
    _sql, args = connection.executed[0]

    assert [source.pmid for source in failed] == ["222", "333"]
    assert args[-2:] == (2, 1)


@pytest.mark.asyncio
async def test_list_review_failed_sources_joins_curated_url_attempts() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.list_review_failed_sources("review-1")

    sql, _args = connection.executed[0]
    assert "URL:(.+)$" in sql
    assert "a.source_id = substring(s.source_id from '^URL:(.+)$')" in sql


@pytest.mark.asyncio
async def test_review_index_totals_counts_indexed_and_failed_sources() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {
            "pmid_count": 1,
            "source_count": 1,
            "passage_count": 2,
            "char_count": 30,
            "failed_source_count": 1,
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    totals = await repository.review_index_totals("review-1")

    assert totals == ReviewIndexTotals(
        pmid_count=1,
        source_count=1,
        passage_count=2,
        char_count=30,
        failed_source_count=1,
    )
    sql, args = connection.executed[0]
    assert "review_preparation_jobs" in sql
    assert "full_text_retrieval_attempts" in sql
    assert "review_passages" in sql
    assert args == ("review-1", None)


@pytest.mark.asyncio
async def test_list_review_indexes_returns_inventory_items() -> None:
    connection = FakeConnection()
    connection.fetched_rows = [
        {
            "review_id": "review-1",
            "created_at": "2026-05-01T00:00:00Z",
            "updated_at": "2026-05-01T01:00:00Z",
            "queued": 0,
            "running": 0,
            "complete": 1,
            "partial": 0,
            "failed": 0,
            "pmid_count": 1,
            "source_count": 1,
            "passage_count": 2,
            "failed_source_count": 0,
            "approximate_bytes": 400,
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    indexes = await repository.list_review_indexes(limit=10, offset=5, ttl_seconds=3600)

    assert indexes == [
        ReviewIndexInventoryItem(
            review_id="review-1",
            created_at="2026-05-01T00:00:00Z",
            updated_at="2026-05-01T01:00:00Z",
            expires_at="2026-05-01 02:00:00+00:00",
            preparation_status=PreparationStatus(complete=1),
            pmid_count=1,
            source_count=1,
            passage_count=2,
            approximate_bytes=400,
        )
    ]
    sql, args = connection.executed[0]
    assert "from reviews r" in sql
    assert "left join job_stats" in sql
    assert args == (10, 5)


@pytest.mark.asyncio
async def test_get_review_index_summary_returns_none_for_missing_review() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    summary = await repository.get_review_index_summary("missing")

    assert summary is None
    sql, args = connection.executed[0]
    assert "where r.review_id = $3" in sql
    assert args == (1, 0, "missing")


@pytest.mark.asyncio
async def test_delete_review_index_deletes_children_before_review() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    deleted = await repository.delete_review_index("review-1")

    assert deleted is False
    statements = [sql.lower() for sql, _args in connection.executed]
    assert "delete from review_research_session_candidates" in statements[0]
    assert "delete from review_research_sessions" in statements[1]
    assert "delete from review_audit_events" in statements[2]
    assert "delete from review_llm_context_events" in statements[3]
    assert "delete from review_llm_context" in statements[4]
    assert "delete from review_evidence_certainty" in statements[5]
    assert "delete from full_text_retrieval_attempts" in statements[6]
    assert "delete from review_passages" in statements[7]
    assert "delete from review_preparation_jobs" in statements[8]
    assert "delete from reviews" in statements[9]


@pytest.mark.asyncio
async def test_record_llm_context_event_inserts_snapshot_and_event_in_transaction() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {
            "context_id": "00000000-0000-0000-0000-000000000001",
            "review_id": "review-1",
            "session_id": "session-1",
            "kind": "retrieval_context",
            "topic": "MEFV therapy",
            "research_question": "Does colchicine prevent FMF flares?",
            "question_hash": None,
            "request": {"tool": "retrieve_review_context"},
            "response_summary": {"answer_summary": "Colchicine reduced flare frequency."},
            "selected_pmids": ["40234174"],
            "rejected_pmids": [],
            "preferred_entity_ids": [],
            "active_queries": [],
            "successful_queries": ["MEFV colchicine"],
            "failed_queries": [],
            "selected_passage_ids": ["PMID:40234174:abstract:0"],
            "audit_passage_ids": ["PMID:40234174:abstract:0"],
            "open_questions": [{"question": "Dose response?"}],
            "user_decisions": [{"decision": "include"}],
            "last_next_commands": [{"tool": "pubtator_retrieve_review_context"}],
            "stable_citation_keys": {"PMID:40234174:abstract:0": "PMID:40234174"},
            "cache_key": "review-1:session-1",
            "token_estimate": 1200,
            "created_by": "agent",
            "created_at": "2026-05-03T00:00:00Z",
            "updated_at": "2026-05-03T00:01:00Z",
        },
        {
            "event_id": "00000000-0000-0000-0000-000000000002",
            "context_id": "00000000-0000-0000-0000-000000000001",
            "review_id": "review-1",
            "session_id": "session-1",
            "event_type": "decision_recorded",
            "summary": "User selected the key abstract passage.",
            "pmids": ["40234174"],
            "passage_ids": ["PMID:40234174:abstract:0"],
            "queries": ["MEFV colchicine"],
            "decision": {"decision": "include"},
            "payload": {"source": "unit-test"},
            "created_by": "agent",
            "created_at": "2026-05-03T00:01:00Z",
        },
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    response = await repository.record_llm_context_event(
        "review-1",
        RecordReviewContextRequest(
            session_id="session-1",
            topic="MEFV therapy",
            research_question="Does colchicine prevent FMF flares?",
            event_type="decision_recorded",
            summary="User selected the key abstract passage.",
            request={"tool": "retrieve_review_context"},
            response_summary={"answer_summary": "Colchicine reduced flare frequency."},
            selected_pmids=["40234174"],
            successful_queries=["MEFV colchicine"],
            selected_passage_ids=["PMID:40234174:abstract:0"],
            audit_passage_ids=["PMID:40234174:abstract:0"],
            open_questions=[{"question": "Dose response?"}],
            user_decisions=[{"decision": "include"}],
            last_next_commands=[{"tool": "pubtator_retrieve_review_context"}],
            stable_citation_keys={"PMID:40234174:abstract:0": "PMID:40234174"},
            cache_key="review-1:session-1",
            token_estimate=1200,
            pmids=["40234174"],
            passage_ids=["PMID:40234174:abstract:0"],
            queries=["MEFV colchicine"],
            decision={"decision": "include"},
            payload={"source": "unit-test"},
            created_by="agent",
        ),
    )

    assert response.context.context_id == "00000000-0000-0000-0000-000000000001"
    assert response.event.event_type == "decision_recorded"
    assert connection.transaction_calls == [{}]
    statements = [sql.lower() for sql, _args in connection.executed]
    assert "insert into reviews" in statements[0]
    assert "insert into review_llm_context" in statements[1]
    assert "insert into review_llm_context_events" in statements[2]
    assert "update reviews" in statements[3]


@pytest.mark.asyncio
async def test_get_latest_llm_context_filters_by_optional_session() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {
            "context_id": "00000000-0000-0000-0000-000000000001",
            "review_id": "review-1",
            "session_id": "session-1",
            "kind": "retrieval_context",
            "topic": "MEFV therapy",
            "research_question": None,
            "question_hash": None,
            "request": {},
            "response_summary": {"answer_summary": "Compact only."},
            "selected_pmids": ["40234174"],
            "rejected_pmids": [],
            "preferred_entity_ids": [],
            "active_queries": [],
            "successful_queries": [],
            "failed_queries": [],
            "selected_passage_ids": ["PMID:40234174:abstract:0"],
            "audit_passage_ids": [],
            "open_questions": [],
            "user_decisions": [],
            "last_next_commands": [],
            "stable_citation_keys": {},
            "cache_key": None,
            "token_estimate": 300,
            "created_by": None,
            "created_at": "2026-05-03T00:00:00Z",
            "updated_at": "2026-05-03T00:01:00Z",
        }
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    context = await repository.get_latest_llm_context("review-1", session_id="session-1")

    assert context is not None
    assert context.session_id == "session-1"
    assert context.response_summary == {"answer_summary": "Compact only."}
    sql, args = connection.executed[0]
    assert "from review_llm_context" in sql.lower()
    assert "order by updated_at desc" in sql.lower()
    assert args == ("review-1", "session-1")


@pytest.mark.asyncio
async def test_cleanup_expired_review_indexes_deletes_expired_ids(monkeypatch) -> None:
    connection = FakeConnection()
    connection.fetched_rows = [{"review_id": "review-1"}, {"review_id": "review-2"}]
    repository = PostgresReviewReragRepository(FakePool(connection))
    deleted_ids: list[str] = []

    async def fake_delete(review_id: str) -> bool:
        deleted_ids.append(review_id)
        return review_id == "review-1"

    monkeypatch.setattr(repository, "delete_review_index", fake_delete)

    deleted = await repository.cleanup_expired_review_indexes(ttl_seconds=3600)

    assert deleted == ["review-1"]
    assert deleted_ids == ["review-1", "review-2"]
    sql, args = connection.executed[0]
    assert "updated_at < now()" in sql
    assert args == (3600,)
