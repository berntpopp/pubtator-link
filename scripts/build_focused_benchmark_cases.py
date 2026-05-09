"""Build focused default benchmark case sets from large public case files."""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

LOGGER = logging.getLogger(__name__)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def build_pubmedqa_balanced(config: dict[str, Any]) -> int:
    source = Path(config["source"])
    output = Path(config["output"])
    seed = int(config["seed"])
    labels = [str(label) for label in config["labels"]]
    per_label = int(config["per_label"])
    case_id_prefix = str(config["case_id_prefix"])
    dataset_version = str(config["dataset_version"])
    rows = _read_jsonl(source)
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[str(row["gold_label"])].append(row)
    rng = random.Random(seed)  # noqa: S311 - deterministic benchmark selection, not crypto.
    selected: list[dict[str, Any]] = []
    for label in labels:
        bucket = list(by_label[label])
        rng.shuffle(bucket)
        selected.extend(bucket[:per_label])
    selected.sort(key=lambda row: (str(row["gold_label"]), str(row["case_id"])))
    for index, row in enumerate(selected, start=1):
        row["case_id"] = f"{case_id_prefix}_{index:03d}"
        row["dataset_version"] = dataset_version
        row.setdefault("case_metadata", {})["focused_source_case_id"] = row["case_metadata"].get(
            "source_pmid"
        )
    _write_jsonl(output, selected)
    return len(selected)


def build_bioasq_complex(config: dict[str, Any]) -> int:
    source = Path(config["source"])
    output = Path(config["output"])
    seed = int(config["seed"])
    count = int(config["count"])
    min_gold_pmids = int(config["min_gold_pmids"])
    min_reference_chars = int(config["min_reference_chars"])
    case_id_prefix = str(config["case_id_prefix"])
    dataset_version = str(config["dataset_version"])
    rows = _read_jsonl(source)
    candidates = [
        row
        for row in rows
        if len(row.get("gold_evidence_pmids", [])) >= min_gold_pmids
        and len(row.get("gold_answer", {}).get("reference_ideal_answer", "")) >= min_reference_chars
    ]
    rng = random.Random(seed)  # noqa: S311 - deterministic benchmark selection, not crypto.
    rng.shuffle(candidates)
    selected = sorted(candidates[:count], key=lambda row: str(row["case_id"]))
    for index, row in enumerate(selected, start=1):
        row["case_id"] = f"{case_id_prefix}_{index:03d}"
        row["dataset_version"] = dataset_version
    _write_jsonl(output, selected)
    return len(selected)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="benchmarks/configs/focused_case_selection.yaml")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text())
    pubmedqa_count = build_pubmedqa_balanced(config["pubmedqa"])
    bioasq_count = build_bioasq_complex(config["bioasq"])
    LOGGER.info("wrote PubMedQA balanced cases: %s", pubmedqa_count)
    LOGGER.info("wrote BioASQ complex cases: %s", bioasq_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
