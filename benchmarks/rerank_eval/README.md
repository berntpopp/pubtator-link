# Rerank eval (#182)

Deterministic, offline. Fixtures freeze each query's candidate set; embeddings are
recomputed from the pinned ONNX model (`make embeddings-model`).

```bash
make eval-rerank                 # SUITE=review (default) or SUITE=search
```

## Review retrieval (`get_review_context`) -- shipped

36 PubMedQA questions whose local review index (8-10 PMIDs, ~100-4,700 passages) contains
the gold PMID; relevant = that PMID's passages. Candidates = production FTS top-k.

| strategy (d = candidate depth) | hit@1 | hit@5 | hit@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| lexical FTS only (<= 7.2.1), d=50 | 0.61 | 0.97 | 1.00 | 0.624 |
| lexical + dense RRF k=60, d=50 | 0.89 | 1.00 | 1.00 | 0.876 |
| **lexical + dense RRF k=10, d=50 (7.3.0 default)** | **0.89** | **1.00** | **1.00** | **0.902** |
| dense only, d=50 | 1.00 | 1.00 | 1.00 | 0.956 |

Caveats: PubMedQA questions paraphrase the gold article's title, which favors dense
similarity; n=36. Dense-only scores best here but drops the lexical signal entirely
(gene symbols, HGVS) and the reference-section guard, so the shipped rank stays a fusion.
k=10 vs k=60 is a small, consistent gain at every depth (d=25/50/100), not a large one.
Request-time cost: one query embedding, p50 3 ms.

## `search_literature` -- not shipped

29 curated queries (#243's TBC1D8B/KATNIP/ZNF423/DDX59/FXYD2/SYNPO/ADAMTS9 plus 22
gene/variant/phenotype discovery papers, PMIDs verified) + 40 BioASQ questions (expert
gold PMIDs). Candidates = PubTator3 relevance pages 1-5.

| strategy (all 69) | hit@1 | hit@5 | hit@10 | nDCG@10 |
|---|---:|---:|---:|---:|
| PubTator3 relevance (pre-7.2.0) | 0.00 | 0.00 | 0.00 | 0.000 |
| + title boost (7.2.0, shipped) | 0.01 | 0.03 | 0.04 | 0.027 |
| pool recall, d=50 (ceiling for any reranker) | 0.12 | 0.12 | 0.12 | 0.116 |
| title boost + dense RRF k=60, d=50 | 0.03 | 0.03 | 0.04 | 0.034 |
| dense only, d=50 | 0.06 | 0.07 | 0.12 | 0.050 |

The bottleneck is candidate recall, not ordering: PubTator3 relevance favours recent
full-text hits, and the labeled paper is in its top 50 for only 12% of queries. Dense-only
at d=50 reaches that ceiling but costs 4 extra upstream page fetches plus ~1.6 s p50 of
embedding per search for +0.08 hit@10. Not worth shipping; a recall fix (another
candidate source) is the real lever.
