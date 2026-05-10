from __future__ import annotations

CORE_WORKFLOW_TOOLS = [
    "pubtator_workflow_help",
    "pubtator_search_literature",
    "pubtator_preflight_review_sources",
    "pubtator_index_review_evidence",
    "pubtator_inspect_review_index",
    "pubtator_retrieve_review_context_batch",
    "pubtator_diagnostics",
]

TOOL_CATEGORIES = {
    "discovery": [
        "pubtator_search_literature",
        "pubtator_lookup_citation",
        "pubtator_convert_article_ids",
    ],
    "review": [
        "pubtator_preflight_review_sources",
        "pubtator_index_review_evidence",
        "pubtator_inspect_review_index",
    ],
    "retrieval": [
        "pubtator_retrieve_review_context_batch",
        "pubtator_get_review_passages_by_id",
        "pubtator_get_review_audit_trail",
    ],
    "diagnostics": ["pubtator_diagnostics"],
}

PREFERRED_TOOL_NAMES = {
    "search_literature": "pubtator_search_literature",
    "retrieve_review_context_batch": "pubtator_retrieve_review_context_batch",
    "index_review_evidence": "pubtator_index_review_evidence",
    "diagnostics": "pubtator_diagnostics",
}

SAMPLE_CALLS = {
    "pubtator_search_literature": {
        "text": "MEFV colchicine familial Mediterranean fever guideline",
        "response_mode": "compact",
        "metadata": "basic",
    },
    "pubtator_search_guidelines": {
        "text": "MEFV familial Mediterranean fever EULAR recommendations",
    },
    "pubtator_lookup_mesh": {
        "query": "familial Mediterranean fever",
        "limit": 5,
    },
    "pubtator_find_related_articles": {
        "pmids": ["40234174"],
        "mode": "similar",
        "limit": 20,
    },
    "pubtator_suggest_corpus": {
        "question": "FMF MEFV VUS colchicine",
        "max_pmids": 8,
    },
    "pubtator_get_publication_metadata": {
        "pmids": ["40234174", "26802180"],
        "include_citations": "none",
        "include_coverage": True,
    },
    "pubtator_retrieve_review_context_batch": {
        "review_id": "fmf-colchicine-guidelines",
        "queries": ["MEFV colchicine", "familial Mediterranean fever child"],
        "response_mode": "compact",
    },
}

SCHEMA_POLICY = {
    "argument_style": "flat",
    "list_inputs": "Use arrays for list inputs; do not pass a singleton string.",
    "preferred_tool_names": PREFERRED_TOOL_NAMES,
    "tool_name_policy": (
        "Registered tools use the pubtator_ prefix (snake_case) so every name conforms "
        "to the Anthropic remote-MCP regex ^[a-zA-Z0-9_-]{1,64}$ required by hosted "
        "Claude clients. Future aliases must be additive only."
    ),
    "guideline_search": {
        "tool": "pubtator_search_guidelines",
        "relationship": (
            "Filtered convenience wrapper over pubtator_search_literature, not an "
            "independent guideline database."
        ),
        "filters": {
            "publication_types": [
                "Guideline",
                "Practice Guideline",
                "Consensus Development Conference",
                "Systematic Review",
            ],
            "guideline_boost": True,
        },
    },
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
