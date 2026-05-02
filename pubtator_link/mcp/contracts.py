from __future__ import annotations

CORE_WORKFLOW_TOOLS = [
    "pubtator.workflow_help",
    "pubtator.search_literature",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context_batch",
    "pubtator.diagnostics",
]

TOOL_CATEGORIES = {
    "discovery": [
        "pubtator.search_literature",
        "pubtator.lookup_citation",
        "pubtator.convert_article_ids",
    ],
    "review": [
        "pubtator.preflight_review_sources",
        "pubtator.index_review_evidence",
        "pubtator.inspect_review_index",
    ],
    "retrieval": [
        "pubtator.retrieve_review_context_batch",
        "pubtator.get_review_passages_by_id",
        "pubtator.get_review_audit_trail",
    ],
    "diagnostics": ["pubtator.diagnostics"],
}

PREFERRED_TOOL_NAMES = [
    "pubtator.workflow_help",
    "pubtator.search_literature",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context_batch",
    "pubtator.get_review_passages_by_id",
    "pubtator.get_review_audit_trail",
    "pubtator.diagnostics",
]

SAMPLE_CALLS = {
    "pubtator.search_literature": {
        "text": "MEFV colchicine familial Mediterranean fever guideline",
        "response_mode": "compact",
        "metadata": "basic",
    },
    "pubtator.lookup_mesh": {
        "query": "familial Mediterranean fever",
        "limit": 5,
    },
    "pubtator.find_related_articles": {
        "pmids": ["40234174"],
        "mode": "similar",
        "limit": 20,
    },
    "pubtator.suggest_corpus": {
        "question": "FMF MEFV VUS colchicine",
        "max_pmids": 8,
    },
    "pubtator.get_publication_metadata": {
        "pmids": ["40234174", "26802180"],
        "include_citations": "none",
        "include_coverage": True,
    },
    "pubtator.retrieve_review_context_batch": {
        "review_id": "fmf-colchicine-guidelines",
        "queries": ["MEFV colchicine", "familial Mediterranean fever child"],
        "response_mode": "compact",
        "max_chars": 12000,
        "max_response_chars": 24000,
    },
}

SCHEMA_POLICY = {
    "argument_style": "flat",
    "list_inputs": "Use arrays for list inputs; do not pass a singleton string.",
    "deprecated_shapes": [
        {
            "shape": "request_envelope",
            "status": "unsupported",
            "replacement": "flat_top_level_arguments",
        }
    ],
    "deprecated_fields": [
        {
            "field": "prepare_mode",
            "status": "deprecated",
            "replacement": "omit",
            "removal_after": "next_minor",
        }
    ],
    "deprecated_tools": [],
}
