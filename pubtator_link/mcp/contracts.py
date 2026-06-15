from __future__ import annotations

CORE_WORKFLOW_TOOLS = [
    "workflow_help",
    "search_literature",
    "preflight_review_sources",
    "index_review_evidence",
    "inspect_review_index",
    "get_review_context_batch",
    "diagnostics",
]

TOOL_CATEGORIES = {
    "discovery": [
        "search_literature",
        "get_citation",
        "convert_article_ids",
    ],
    "review": [
        "preflight_review_sources",
        "index_review_evidence",
        "inspect_review_index",
    ],
    "retrieval": [
        "get_review_context_batch",
        "get_review_passages_by_id",
        "get_review_audit_trail",
    ],
    "diagnostics": ["diagnostics"],
}

PREFERRED_TOOL_NAMES = {
    "search_literature": "search_literature",
    "get_review_context_batch": "get_review_context_batch",
    "index_review_evidence": "index_review_evidence",
    "diagnostics": "diagnostics",
}

SAMPLE_CALLS = {
    "search_literature": {
        "text": "MEFV colchicine familial Mediterranean fever guideline",
        "response_mode": "compact",
        "metadata": "basic",
    },
    "search_guidelines": {
        "text": "MEFV familial Mediterranean fever EULAR recommendations",
    },
    "get_mesh": {
        "query": "familial Mediterranean fever",
        "limit": 5,
    },
    "find_related_articles": {
        "pmids": ["40234174"],
        "mode": "similar",
        "limit": 20,
    },
    "suggest_corpus": {
        "question": "FMF MEFV VUS colchicine",
        "max_pmids": 8,
    },
    "get_publication_metadata": {
        "pmids": ["40234174", "26802180"],
        "include_citations": "none",
        "include_coverage": True,
    },
    "get_review_context_batch": {
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
        "Registered tools are unprefixed snake_case names (GeneFoundry Tool-Naming "
        "Standard v1); the genefoundry-router gateway adds the 'pubtator' namespace at "
        "mount time (tools surface as pubtator_<tool>). Every name conforms to the "
        "Anthropic remote-MCP regex ^[a-zA-Z0-9_-]{1,64}$ required by hosted Claude "
        "clients. Future aliases must be additive only."
    ),
    "guideline_search": {
        "tool": "search_guidelines",
        "relationship": (
            "Filtered convenience wrapper over search_literature, not an "
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
