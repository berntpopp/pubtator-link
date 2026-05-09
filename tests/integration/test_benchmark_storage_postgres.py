from __future__ import annotations

import os
from pathlib import Path

import asyncpg
import pytest

from pubtator_link.benchmarks.models import (
    BenchmarkCase,
    BenchmarkMode,
    BenchmarkScore,
    ModelSettings,
    PredictionRecord,
    RunManifest,
)
from pubtator_link.benchmarks.storage import BenchmarkStorage

pytestmark = pytest.mark.integration


async def _connect_or_skip(database_url: str) -> asyncpg.Connection:
    try:
        return await asyncpg.connect(database_url)
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL test database is not reachable: {exc}")


@pytest.mark.asyncio
async def test_synthetic_run_persists_rows() -> None:
    database_url = os.getenv("PUBTATOR_LINK_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("PUBTATOR_LINK_TEST_DATABASE_URL is not set")

    schema = Path("pubtator_link/db/migrations/0006_benchmark_suite.sql").read_text()
    conn = await _connect_or_skip(database_url)
    try:
        await conn.execute(schema)
    finally:
        await conn.close()

    run_id = "synthetic-benchmark-run"
    manifest = RunManifest(
        run_id=run_id,
        suite="pubmedqa_smoke",
        dataset="pubmedqa",
        dataset_version="pqa_l_article_local_v1",
        mode=BenchmarkMode.NO_TOOLS,
        sample_seed=20260509,
        case_ids=["case_1"],
        prompt_template_hash="a" * 64,
        prompt_resolved_hash="b" * 64,
        answer_stack="dry_run:deterministic",
        model_settings=ModelSettings(adapter="dry_run", requested_model="deterministic"),
    )
    cases = [
        BenchmarkCase(
            dataset="pubmedqa",
            dataset_version="pqa_l_article_local_v1",
            case_id="case_1",
            question="Question?",
            target_pmids=["1"],
            gold_label="yes",
            gold_evidence_pmids=["1"],
            dataset_license="test",
            dataset_use_restriction="research_use",
        )
    ]
    predictions = [PredictionRecord(case_id="case_1", predicted_label="yes")]
    storage = BenchmarkStorage(database_url)

    await storage.insert_run(manifest)
    await storage.insert_cases(run_id, cases)
    await storage.insert_predictions(run_id, predictions)
    await storage.insert_scores(run_id, BenchmarkScore(dataset="pubmedqa"))

    assert await storage.count_predictions(run_id) == len(predictions)
