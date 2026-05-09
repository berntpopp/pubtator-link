"""Build large benchmark case files from public upstream datasets."""

from __future__ import annotations

import argparse
import ast
import json
import logging
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

PUBMEDQA_URL = "https://raw.githubusercontent.com/pubmedqa/pubmedqa/master/data/ori_pqal.json"
BIOASQ_DATASET = "jmhb/BioASQ"
BIOASQ_ROWS_API = "https://datasets-server.huggingface.co/rows"

LOGGER = logging.getLogger(__name__)


def _load_https_json(url: str, timeout: int) -> Any:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"expected https URL, got: {url}")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        return json.load(response)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))


def _pmid_from_url(value: str) -> str | None:
    marker = "/pubmed/"
    if marker not in value:
        return None
    pmid = value.rsplit(marker, 1)[-1].strip()
    return pmid or None


def _parse_ideal_answer(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(part) for part in value)
    text = str(value)
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(text)
        except (ValueError, SyntaxError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, list):
            return " ".join(str(part) for part in parsed)
        return str(parsed)
    return text


def _parse_pubmedqa_context(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(part) for part in value)
    return str(value or "")


def build_pubmedqa(output: Path) -> int:
    raw = _load_https_json(PUBMEDQA_URL, timeout=60)

    rows: list[dict[str, Any]] = []
    for index, (pmid, item) in enumerate(sorted(raw.items()), start=1):
        label = item["final_decision"]
        rows.append(
            {
                "dataset": "pubmedqa",
                "dataset_version": "pqa_l_full_1000_v1",
                "case_id": f"pubmedqa_full_{index:04d}",
                "question": item["QUESTION"],
                "target_pmids": [pmid],
                "gold_label": label,
                "gold_answer": {"long_answer": item.get("LONG_ANSWER", "")},
                "gold_evidence_pmids": [pmid],
                "dataset_license": "PubMedQA public PQA-L from pubmedqa/pubmedqa",
                "dataset_use_restriction": "research_use",
                "case_metadata": {
                    "source_url": PUBMEDQA_URL,
                    "source_pmid": pmid,
                    "abstract_context": _parse_pubmedqa_context(item.get("CONTEXTS", [])),
                    "year": item.get("YEAR"),
                    "meshes": item.get("MESHES", []),
                    "reasoning_required_pred": item.get("reasoning_required_pred"),
                    "reasoning_free_pred": item.get("reasoning_free_pred"),
                },
            }
        )
    _write_jsonl(output, rows)
    return len(rows)


def build_bioasq_summary(output: Path) -> int:
    rows: list[dict[str, Any]] = []
    offset = 0
    page_size = 100
    while True:
        params = urlencode(
            {
                "dataset": BIOASQ_DATASET,
                "config": "default",
                "split": "summary",
                "offset": offset,
                "length": page_size,
            }
        )
        page = _load_https_json(f"{BIOASQ_ROWS_API}?{params}", timeout=120)
        for item in page["rows"]:
            row = item["row"]
            documents = [str(value) for value in row["documents"]]
            pmids = [pmid for value in documents if (pmid := _pmid_from_url(value))]
            reference = _parse_ideal_answer(row["ideal_answer"])
            rows.append(
                {
                    "dataset": "bioasq_ideal",
                    "dataset_version": "jmhb_bioasq_summary_full_v1",
                    "case_id": f"bioasq_summary_full_{len(rows) + 1:04d}",
                    "question": row["question"],
                    "target_pmids": pmids,
                    "gold_label": None,
                    "gold_answer": {"reference_ideal_answer": reference},
                    "gold_evidence_pmids": pmids,
                    "source_access": dict.fromkeys(pmids, "abstract_only"),
                    "dataset_license": "jmhb/BioASQ public Hugging Face mirror",
                    "dataset_use_restriction": "research_use",
                    "case_metadata": {
                        "source_dataset": BIOASQ_DATASET,
                        "source_api": BIOASQ_ROWS_API,
                        "bioasq_id": row["id"],
                        "asq_challenge": row["asq_challenge"],
                        "folder_name": row["folder_name"],
                        "document_count": len(documents),
                    },
                }
            )
        offset += len(page["rows"])
        if offset >= page["num_rows_total"] or not page["rows"]:
            break
    _write_jsonl(output, rows)
    return len(rows)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pubmedqa-output", default="benchmarks/cases/pubmedqa/pqa_l_full_1000.jsonl"
    )
    parser.add_argument(
        "--bioasq-output",
        default="benchmarks/cases/bioasq/summary_full_1283.jsonl",
    )
    args = parser.parse_args()
    pubmedqa_count = build_pubmedqa(Path(args.pubmedqa_output))
    bioasq_count = build_bioasq_summary(Path(args.bioasq_output))
    LOGGER.info("wrote PubMedQA cases: %s", pubmedqa_count)
    LOGGER.info("wrote BioASQ summary cases: %s", bioasq_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
