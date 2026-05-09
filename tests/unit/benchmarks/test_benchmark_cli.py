from __future__ import annotations

from pathlib import Path

from pubtator_link.benchmarks.cli import main


def test_benchmark_cli_dry_run_writes_bundle(tmp_path: Path) -> None:
    exit_code = main(
        [
            "run",
            "--suite",
            "benchmarks/suites/pubmedqa_smoke.yaml",
            "--answer-stack",
            "dry_run:deterministic",
            "--artifact-dir",
            str(tmp_path),
            "--no-db",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert next(tmp_path.glob("*/manifest.json")).exists()


def test_v1_rejects_resume_flag() -> None:
    assert main(["run", "--suite", "benchmarks/suites/pubmedqa_smoke.yaml", "--resume"]) == 2


def test_compare_rejects_missing_inputs() -> None:
    assert main(["compare", "--left", "/does/not/exist", "--right", "/also/missing"]) == 2
