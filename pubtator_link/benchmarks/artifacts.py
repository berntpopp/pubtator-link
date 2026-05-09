from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from pubtator_link.benchmarks.models import ArtifactRecord, BenchmarkCase, PredictionRecord


class ArtifactBundleWriter(BaseModel):
    root: Path
    run_id: UUID
    suite: str

    @property
    def path(self) -> Path:
        return self.root / f"{self.run_id}-{self.suite}"

    def _ensure_path(self) -> None:
        self.path.mkdir(parents=True, exist_ok=True)

    def write_text(self, relative_path: str, text: str) -> Path:
        self._ensure_path()
        path = self.path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def write_json(self, relative_path: str, payload: object) -> Path:
        return self.write_text(relative_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def write_jsonl(self, relative_path: str, rows: list[dict[str, object]]) -> Path:
        return self.write_text(
            relative_path,
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        )

    def write_cases(self, cases: list[BenchmarkCase]) -> None:
        public_rows: list[dict[str, object]] = []
        gold_rows: list[dict[str, object]] = []
        for case in cases:
            public = case.model_dump(mode="json")
            for key in ("gold_label", "gold_answer", "gold_evidence_pmids"):
                public.pop(key, None)
            public_rows.append(public)
            gold_rows.append(
                {
                    "case_id": case.case_id,
                    "gold_label": case.gold_label,
                    "gold_answer": case.gold_answer,
                    "gold_evidence_pmids": case.gold_evidence_pmids,
                }
            )
        self.write_jsonl("cases.jsonl", public_rows)
        self.write_jsonl("gold.jsonl", gold_rows)

    def write_predictions(self, predictions: list[PredictionRecord]) -> None:
        self.write_jsonl(
            "predictions.jsonl",
            [prediction.model_dump(mode="json") for prediction in predictions],
        )

    def finalize_artifact_records(self) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        if not self.path.exists():
            return records
        for path in sorted(item for item in self.path.rglob("*") if item.is_file()):
            relative = path.relative_to(self.path).as_posix()
            records.append(
                ArtifactRecord(
                    artifact_type=path.suffix.removeprefix(".") or "file",
                    relative_path=relative,
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    size_bytes=path.stat().st_size,
                )
            )
        return records
