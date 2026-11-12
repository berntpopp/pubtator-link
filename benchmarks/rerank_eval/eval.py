"""Offline, deterministic eval of lexical vs embedding ranking (#182).

    uv run python benchmarks/rerank_eval/eval.py review               # score get_review_context
    uv run python benchmarks/rerank_eval/eval.py search               # score search_literature
    uv run python benchmarks/rerank_eval/eval.py review --record      # refresh (needs DATABASE_URL)
    uv run python benchmarks/rerank_eval/eval.py search --record      # refresh (live PubTator3)

Fixtures freeze the candidate sets (lexical order + text), so every strategy is scored
on identical candidates. Embeddings are recomputed from the pinned ONNX model, which is
deterministic on CPU. ``make embeddings-model`` fetches it to .models/.

review: PubMedQA questions whose local review index holds the gold PMID. Relevant
        passages = passages of that PMID (PubMedQA's gold context). Candidates are the
        production lexical top-k from Postgres FTS (``search_passages``).
search: curated gene/variant/phenotype queries (#243 + discovery papers) plus BioASQ
        questions with expert gold PMIDs; candidates = PubTator3 relevance pages 1-5.
"""

# ruff: noqa: T201
from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cases import CASES  # noqa: E402

SEARCH_FIXTURE = HERE / "search_fixture.json.gz"
REVIEW_FIXTURE = HERE / "review_fixture.json.gz"
CASES_DIR = HERE.parent / "cases"
BIOASQ_CASES = 40
RECORD_PAGES = 5
REVIEW_RECORD_DEPTH = 100
TEXT_CHARS = 1500
DEFAULT_MODEL_DIR = ".models/bge-small-en-v1.5"


def _save(path: Path, data: object) -> None:
    path.write_bytes(gzip.compress(json.dumps(data, sort_keys=True).encode(), mtime=0))


def _load(path: Path) -> list[dict[str, Any]]:
    return json.loads(gzip.decompress(path.read_bytes()))


def metrics(ranked: Sequence[str], relevant: set[str]) -> dict[str, float]:
    """Binary-relevance hit@k and nDCG@10 over an ordered list of ids."""
    top = list(ranked[:10])
    dcg = sum(1 / math.log2(i + 2) for i, item in enumerate(top) if item in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), 10)))
    return {
        "hit@1": float(bool(set(ranked[:1]) & relevant)),
        "hit@5": float(bool(set(ranked[:5]) & relevant)),
        "hit@10": float(bool(set(top) & relevant)),
        "ndcg@10": dcg / ideal if ideal else 0.0,
    }


def fuse(lexical: Sequence[str], dense: Sequence[str], *, rrf_k: int) -> list[str]:
    """Reciprocal-rank fusion of two orderings of the same ids; ties keep lexical order."""
    dense_rank = {item: rank for rank, item in enumerate(dense, start=1)}
    score = {
        item: 1 / (rrf_k + rank) + 1 / (rrf_k + dense_rank.get(item, len(dense) + 1))
        for rank, item in enumerate(lexical, start=1)
    }
    return sorted(lexical, key=lambda item: -score[item])


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))]


class Table:
    def __init__(self) -> None:
        self.rows: dict[str, list[tuple[str, dict[str, float]]]] = {}

    def add(self, name: str, kind: str, values: dict[str, float]) -> None:
        self.rows.setdefault(name, []).append((kind, values))

    def print(self, subsets: Sequence[str]) -> None:
        for subset in subsets:
            print(f"\n### subset: {subset}")
            print("| strategy | n | hit@1 | hit@5 | hit@10 | nDCG@10 |")
            print("|---|---:|---:|---:|---:|---:|")
            for name, values in self.rows.items():
                picked = [m for kind, m in values if subset in {"all", kind}]
                if not picked:
                    continue
                mean = {key: sum(m[key] for m in picked) / len(picked) for key in picked[0]}
                print(
                    f"| {name} | {len(picked)} | {mean['hit@1']:.2f} | {mean['hit@5']:.2f} | "
                    f"{mean['hit@10']:.2f} | {mean['ndcg@10']:.3f} |"
                )


def _provider(model_dir: str) -> Any:
    from pubtator_link.services.review_context.embeddings import OnnxEmbeddingProvider

    return OnnxEmbeddingProvider(model_dir=model_dir, model_name=model_dir, dim=384)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


# --------------------------------------------------------------------------- review


async def record_review() -> None:
    import asyncpg

    from pubtator_link.repositories.review_rerag import PostgresReviewReragRepository

    questions: dict[str, str] = {}
    for path in sorted((CASES_DIR / "pubmedqa").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            questions.setdefault(row["gold_evidence_pmids"][0], row["question"])
    pool = await asyncpg.create_pool(
        os.environ["PUBTATOR_LINK_DATABASE_URL"], min_size=1, max_size=2
    )
    try:
        rows = await pool.fetch(
            "select review_id, array_agg(distinct pmid) as pmids from review_passages "
            "where review_id like 'quickstart-%' group by review_id order by review_id"
        )
        repository = PostgresReviewReragRepository(pool)
        cases: list[dict[str, Any]] = []
        seen_gold: set[str] = set()
        for row in rows:
            gold = sorted(p for p in row["pmids"] if p in questions)
            if not gold or gold[0] in seen_gold or len(row["pmids"]) < 3:
                continue
            seen_gold.add(gold[0])
            question = questions[gold[0]]
            candidates = await repository.search_passages(
                row["review_id"], question, limit=REVIEW_RECORD_DEPTH
            )
            cases.append(
                {
                    "query": question,
                    "review_id": row["review_id"],
                    "relevant_pmid": gold[0],
                    "kind": "pubmedqa",
                    "candidates": [
                        {
                            "passage_id": c.passage_id,
                            "review_id": c.review_id,
                            "source_id": c.source_id,
                            "source_kind": c.source_kind,
                            "section": c.section,
                            "pmid": c.pmid,
                            "lexical_rank": c.lexical_rank,
                            "text": c.text[:TEXT_CHARS],
                        }
                        for c in candidates
                    ],
                }
            )
    finally:
        await pool.close()
    _save(REVIEW_FIXTURE, cases)
    print(f"recorded {len(cases)} review cases", file=sys.stderr)


async def evaluate_review(model_dir: str, depths: Sequence[int]) -> None:
    from pubtator_link.models.review_rerag import ReviewPassageRow
    from pubtator_link.services.review_context.embedding_rerank import rerank_with_embeddings
    from pubtator_link.services.review_context.ranking import rerank_key

    provider = _provider(model_dir)
    table = Table()
    query_ms: list[float] = []
    for case in _load(REVIEW_FIXTURE):
        rows = [ReviewPassageRow(**c) for c in case["candidates"]]
        relevant = {r.passage_id for r in rows if r.pmid == case["relevant_pmid"]}
        started = time.perf_counter()
        query_vector = await provider.embed_query(case["query"])
        query_ms.append((time.perf_counter() - started) * 1000)
        vectors = await provider.embed_passages([r.text for r in rows])
        dense = {r.passage_id: _cosine(query_vector, v) for r, v in zip(rows, vectors, strict=True)}
        for depth in depths:
            # The repository returns FTS rank order; the service takes the top-k of it.
            pool = rows[:depth]
            lexical = [r.passage_id for r in sorted(pool, key=rerank_key)]
            table.add(
                f"lexical FTS only (<= 7.2.1) d={depth}", "pubmedqa", metrics(lexical, relevant)
            )
            table.add(
                f"pool recall (oracle) d={depth}",
                "pubmedqa",
                dict.fromkeys(
                    metrics([], set()), float(bool({r.passage_id for r in pool} & relevant))
                ),
            )
            dense_order = sorted(lexical, key=lambda pid: -dense[pid])
            table.add(f"dense only d={depth}", "pubmedqa", metrics(dense_order, relevant))
            for rrf_k in (10, 60):
                ranked, _ = rerank_with_embeddings(pool, {p: dense[p] for p in lexical}, rrf_k)
                table.add(
                    f"lexical + dense RRF k={rrf_k}{' (7.3.0 default)' if rrf_k == 10 else ''} d={depth}",
                    "pubmedqa",
                    metrics([r.passage_id for r in ranked], relevant),
                )
    table.print(["all"])
    print(
        f"\nquery embedding latency (request-time cost of rerank): "
        f"p50={percentile(query_ms, 0.5):.0f} ms p95={percentile(query_ms, 0.95):.0f} ms "
        f"(n={len(query_ms)})"
    )


# --------------------------------------------------------------------------- search


def search_cases() -> list[dict[str, object]]:
    """Curated cases plus the first BIOASQ_CASES BioASQ questions with >= 3 gold PMIDs."""
    bioasq: list[dict[str, object]] = []
    path = CASES_DIR / "bioasq" / "summary_full_1283.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if len(row["gold_evidence_pmids"]) >= 3 and len(bioasq) < BIOASQ_CASES:
            bioasq.append(
                {"query": row["question"], "relevant": row["gold_evidence_pmids"], "kind": "bioasq"}
            )
    return [*CASES, *bioasq]


async def record_search() -> None:
    from pubtator_link.api.client import PubTator3Client

    out: list[dict[str, Any]] = []
    async with PubTator3Client() as client:
        for case in search_cases():
            pages: list[list[dict[str, str]]] = []
            total_pages = 1
            for page in range(1, RECORD_PAGES + 1):
                raw = await client.search_publications(text=str(case["query"]), page=page)
                total_pages = int(raw.get("total_pages", 1) or 1)
                pages.append(
                    [
                        {"pmid": str(item.get("pmid")), "title": str(item.get("title") or "")}
                        for item in raw.get("results", [])
                    ]
                )
                if page >= total_pages:
                    break
            pmids = list(dict.fromkeys(i["pmid"] for page_items in pages for i in page_items))
            abstracts: dict[str, str] = {}
            if pmids:
                exported = await client.export_publications(pmids=pmids, format="pubtator")
                for line in str(exported.get("content", "")).splitlines():
                    pmid, sep, text = line.partition("|a|")
                    if sep and text.strip():
                        abstracts[pmid] = text.strip()[:TEXT_CHARS]
            out.append({**case, "total_pages": total_pages, "pages": pages, "abstracts": abstracts})
            print(f"recorded {case['query']!r}: {len(pmids)} candidates", file=sys.stderr)
    _save(SEARCH_FIXTURE, out)


class RecordedClient:
    """Serves recorded upstream pages to promote_title_matches."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.case = case

    async def search_publications(self, *, text: str, page: int, **_: Any) -> dict[str, Any]:
        pages = self.case["pages"]
        results = pages[page - 1] if page <= len(pages) else []
        return {"results": [dict(i) for i in results], "total_pages": self.case["total_pages"]}


def _pool(case: dict[str, Any], depth: int) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for page in case["pages"]:
        for item in page:
            unique.setdefault(item["pmid"], item)
    return list(unique.values())[:depth]


async def evaluate_search(model_dir: str, depths: Sequence[int]) -> None:
    from pubtator_link.services.search_shaping import promote_title_matches

    provider = _provider(model_dir)
    cases = _load(SEARCH_FIXTURE)
    table = Table()
    embed_ms: list[float] = []
    for case in cases:
        relevant, kind = set(case["relevant"]), case["kind"]
        table.add(
            "PubTator3 relevance (pre-7.2.0)",
            kind,
            metrics([i["pmid"] for i in case["pages"][0]], relevant),
        )
        page_one = {
            "results": [dict(i) for i in case["pages"][0]],
            "total_pages": case["total_pages"],
        }
        promoted = await promote_title_matches(
            RecordedClient(case),
            page_one,
            text=case["query"],
            filters=None,
            sections=None,
            wanted=10,
        )
        title_order = [i["pmid"] for i in promoted["results"]]
        table.add("+ title boost (7.2.0, shipped)", kind, metrics(title_order, relevant))
        deep = _pool(case, max(depths))
        texts = [f"{i['title']} {case['abstracts'].get(i['pmid'], '')}".strip() for i in deep]
        started = time.perf_counter()
        query_vector = await provider.embed_query(case["query"])
        vectors = await provider.embed_passages(texts)
        embed_ms.append((time.perf_counter() - started) * 1000)
        dense = {i["pmid"]: _cosine(query_vector, v) for i, v in zip(deep, vectors, strict=True)}
        for depth in depths:
            candidates = [i["pmid"] for i in _pool(case, depth)]
            in_pool = float(bool(set(candidates) & relevant))
            table.add(
                f"pool recall (oracle) d={depth}", kind, dict.fromkeys(metrics([], set()), in_pool)
            )
            lexical = list(dict.fromkeys(title_order + candidates))
            dense_order = sorted(lexical, key=lambda p: -dense[p])
            table.add(f"dense only d={depth}", kind, metrics(dense_order, relevant))
            table.add(
                f"title boost + dense RRF k=60 d={depth}",
                kind,
                metrics(fuse(lexical, dense_order, rrf_k=60), relevant),
            )
    table.print(["all", *dict.fromkeys(str(c["kind"]) for c in cases)])
    print(
        f"\nembedding latency (query + {max(depths)} title+abstract docs): "
        f"p50={percentile(embed_ms, 0.5):.0f} ms p95={percentile(embed_ms, 0.95):.0f} ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("suite", choices=["review", "search"])
    parser.add_argument("--record", action="store_true", help="refresh the fixture (network/DB)")
    parser.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    parser.add_argument("--depth", type=int, action="append", default=[])
    args = parser.parse_args()
    jobs: dict[tuple[str, bool], Callable[[], Any]] = {
        ("review", True): record_review,
        ("search", True): record_search,
        ("review", False): lambda: evaluate_review(args.model_dir, args.depth or [25, 50, 100]),
        ("search", False): lambda: evaluate_search(args.model_dir, args.depth or [10, 30, 50]),
    }
    asyncio.run(jobs[(args.suite, args.record)]())


if __name__ == "__main__":
    main()
