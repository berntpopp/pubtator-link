from __future__ import annotations

from pubtator_link.models.review_rerag import ReviewPassageRow, SampleSectionPolicy

SECTION_PRIORITY = {
    "results": 0,
    "result": 0,
    "discussion": 1,
    "discuss": 1,
    "conclusion": 2,
    "conclusions": 2,
    "concl": 2,
    "abstract": 3,
    "abstr": 3,
    "summary": 4,
    "title": 6,
    "body": 7,
    "introduction": 8,
    "intro": 8,
    "background": 8,
    "methods": 9,
    "method": 9,
    "materials and methods": 9,
    "table": 9,
    "ref": 50,
    "references": 50,
}

ORIGINAL_SECTION_PRIORITY = {
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


def rerank_key(
    row: ReviewPassageRow,
    *,
    section_policy: SampleSectionPolicy = "evidence_first",
) -> tuple[float, int, int, str, str]:
    section_priority = (
        ORIGINAL_SECTION_PRIORITY if section_policy == "original_order" else SECTION_PRIORITY
    )
    return (
        -row.lexical_rank,
        section_priority.get(row.section.strip().lower(), 100),
        SOURCE_PRIORITY.get(row.source_kind, 100),
        row.pmid or "",
        row.passage_id,
    )
