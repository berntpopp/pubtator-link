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

PREFERRED_TOOL_NAMES = {
    "search_literature": "pubtator.search_literature",
    "retrieve_review_context_batch": "pubtator.retrieve_review_context_batch",
    "index_review_evidence": "pubtator.index_review_evidence",
    "diagnostics": "pubtator.diagnostics",
}

SAMPLE_CALLS = {
    "pubtator.search_literature": {
        "text": "MEFV colchicine familial Mediterranean fever guideline",
        "response_mode": "compact",
        "metadata": "basic",
    },
    "pubtator.search_guidelines": {
        "text": "MEFV familial Mediterranean fever EULAR recommendations",
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
    },
}

SCHEMA_POLICY = {
    "argument_style": "flat",
    "list_inputs": "Use arrays for list inputs; do not pass a singleton string.",
    "preferred_tool_names": PREFERRED_TOOL_NAMES,
    "tool_name_policy": (
        "Registered tools retain the pubtator. prefix for backward compatibility and to "
        "disambiguate clients that do not include the MCP server name in display text. "
        "Future aliases must be additive only."
    ),
    "guideline_search": {
        "tool": "pubtator.search_guidelines",
        "relationship": (
            "Filtered convenience wrapper over pubtator.search_literature, not an "
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
