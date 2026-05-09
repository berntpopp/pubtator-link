from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pubtator_link.benchmarks.artifacts import ArtifactBundleWriter
from pubtator_link.benchmarks.cases import load_cases


def test_artifact_writer_records_hashes(tmp_path: Path) -> None:
    writer = ArtifactBundleWriter(root=tmp_path, run_id=UUID(int=1), suite="pubmedqa_smoke")

    writer.write_json("manifest.json", {"run_id": str(UUID(int=1))})
    records = writer.finalize_artifact_records()

    assert records[0].relative_path == "manifest.json"
    assert len(records[0].sha256) == 64


def test_artifact_writer_writes_gold_separately(tmp_path: Path) -> None:
    cases = load_cases(Path("benchmarks/cases/pubmedqa/article_local_smoke_10.jsonl"))[:1]
    writer = ArtifactBundleWriter(root=tmp_path, run_id=UUID(int=1), suite="pubmedqa_smoke")

    writer.write_cases(cases)

    assert (writer.path / "cases.jsonl").exists()
    assert (writer.path / "gold.jsonl").exists()
    assert "gold_label" not in (writer.path / "cases.jsonl").read_text()
