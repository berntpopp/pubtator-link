from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow

SECTION_PRIORITY = {
    "title": 0,
    "abstract": 1,
    "abstr": 1,
    "summary": 2,
    "introduction": 3,
    "intro": 3,
    "background": 4,
    "methods": 5,
    "method": 5,
    "materials and methods": 5,
    "results": 6,
    "result": 6,
    "discussion": 7,
    "discuss": 7,
    "conclusion": 8,
    "conclusions": 8,
    "concl": 8,
    "table": 9,
    "body": 10,
    "ref": 50,
    "references": 50,
}

SOURCE_PRIORITY = {
    "pubtator_full_bioc": 0,
    "pmc_bioc": 1,
    "europe_pmc_jats": 2,
    "curated_pdf": 3,
    "curated_html": 4,
    "docling_pdf": 5,
    "pubtator_abstract": 6,
}

SOURCE_COVERAGE_SCARCITY_PRIORITY = {
    "title_only": 0,
    "abstract_only": 1,
    "curated_url": 2,
    "full_text": 3,
    "unknown": 4,
}


def rerank_key(row: ReviewPassageRow) -> tuple[float, int, int, str, str]:
    return (
        -row.lexical_rank,
        SECTION_PRIORITY.get(row.section.strip().lower(), 100),
        SOURCE_PRIORITY.get(row.source_kind, 100),
        row.pmid or "",
        row.passage_id,
    )
