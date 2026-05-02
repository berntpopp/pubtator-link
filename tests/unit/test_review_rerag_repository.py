from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from pubtator_link.models.review_rerag import (
    FailedSourceSummary,
    PreparationStatus,
    ResearchSessionCandidate,
    ReviewIndexInventoryItem,
    ReviewIndexTotals,
    ReviewPassageRow,
    ReviewPassageSample,
    ReviewSourceSummary,
)
from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository


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
async def test_enqueue_preparation_job_creates_review_and_returns_status() -> None:
    connection = FakeConnection()
    connection.fetchrow_rows = [
        {"queued": 1, "running": 0, "complete": 0, "partial": 0, "failed": 0}
    ]
    repository = PostgresReviewReragRepository(FakePool(connection))

    status = await repository.enqueue_preparation_job(
        review_id="review-1",
        source_id="40234174",
        source_kind="pubtator_abstract",
    )

    assert status == PreparationStatus(queued=1)
    assert len(connection.executed) == 3
    assert "insert into reviews" in connection.executed[0][0].lower()
    assert connection.executed[0][1] == ("review-1",)
    upsert_sql, upsert_args = connection.executed[1]
    assert "insert into review_preparation_jobs" in upsert_sql.lower()
    assert "source_kind" in upsert_sql
    assert "on conflict (review_id, source_id)" in upsert_sql.lower()
    assert isinstance(upsert_args[0], UUID)
    assert upsert_args[1:] == ("review-1", "40234174", "pubtator_abstract")


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
    )


@pytest.mark.asyncio
async def test_job_status_methods_execute_expected_sql() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))

    await repository.mark_job_running(review_id="review-1", source_id="PMID:40234174")
    await repository.mark_job_finished(
        review_id="review-1",
        source_id="PMID:40234174",
        status="complete",
        error=None,
    )

    assert len(connection.executed) == 2
    assert "set status = 'running'" in connection.executed[0][0].lower()
    assert "set status = $3" in connection.executed[1][0].lower()


@pytest.mark.asyncio
async def test_advisory_lock_wraps_preparation_callback() -> None:
    connection = FakeConnection()
    repository = PostgresReviewReragRepository(FakePool(connection))
    callback = AsyncMock(return_value="complete")

    result = await repository.with_preparation_lock(
        review_id="review-1",
        source_id="PMID:40234174",
        callback=callback,
    )

    assert result == "complete"
    assert len(connection.executed) == 1
    assert "pg_advisory_xact_lock" in connection.executed[0][0]
    callback.assert_awaited_once()


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
    assert "recall_query" in sql
    assert "websearch_to_tsquery" in sql
    assert "to_tsquery('english', $7)" in sql
    assert "search_vector @@ query.strict_query or search_vector @@ query.recall_query" in (
        normalized_sql
    )
    assert args[-1] == "should | colchicine | start | after | clinical | diagnosis | fmf | children"


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
    assert summary_args == ("review-1", ["111"])
    assert "row_number()" in sample_sql.lower()
    assert sample_args == ("review-1", ["111"], ["111"], 1, "evidence_first", 80)


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
    assert args == ("review-1", ["p2", "missing", "p1"])


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
    assert args == ("review-1", ["40234174"])


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
    assert args == ("review-1",)


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
    assert args == ("review-1",)


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
    assert "delete from review_evidence_certainty" in statements[3]
    assert "delete from full_text_retrieval_attempts" in statements[4]
    assert "delete from review_passages" in statements[5]
    assert "delete from review_preparation_jobs" in statements[6]
    assert "delete from reviews" in statements[7]


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
