from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from pubtator_link.benchmarks.runner import run_suite


def test_runner_persists_when_database_url_is_supplied(tmp_path: Path) -> None:
    storage = AsyncMock()

    with patch("pubtator_link.benchmarks.runner.BenchmarkStorage", return_value=storage):
        run_suite(
            suite_path=Path("benchmarks/suites/pubmedqa_smoke.yaml"),
            answer_stack="dry_run:deterministic",
            artifact_dir=tmp_path,
            database_url="postgresql://example/test",
        )

    storage.insert_run.assert_awaited_once()
    storage.insert_cases.assert_awaited_once()
    storage.insert_predictions.assert_awaited_once()
    storage.insert_scores.assert_awaited_once()
