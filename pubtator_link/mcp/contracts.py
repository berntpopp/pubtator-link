from __future__ import annotations

from typing import Any

from pubtator_link.mcp.profiles import MCPToolProfile, tool_names_for_profile

READONLY_RETRIEVAL_WORKFLOW_TOOLS = [
    "search_literature",
    "preflight_review_sources",
    "get_publication_passages",
]

LEAN_REVIEW_WORKFLOW_TOOLS = [
    "search_literature",
    "preflight_review_sources",
    "index_review_evidence",
    "inspect_review_index",
    "get_review_context_batch",
]

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


def get_llm_driver_contract(profile: MCPToolProfile | None = None) -> dict[str, Any]:
    contract: dict[str, Any] = {
        "version": "2026-05-02",
        "recommended_entrypoint": "workflow_help",
        "discovery_policy": {
            "strategy": "progressive_discovery",
            "rationale": "Full tool schemas are large; inspect core workflow tools as needed.",
        },
        "core_workflow_tools": [
            "search_biomedical_entities",
            "search_literature",
            "preflight_review_sources",
            "index_review_evidence",
            "inspect_review_index",
            "ground_question",
            "get_review_context_batch",
            "get_review_context",
            "get_review_passages_by_id",
            "get_review_audit_trail",
        ],
        "detail_levels": ["catalog", "schemas", "examples"],
        "schema_bundle": {
            "index_review_evidence": {
                "input_schema": "tools/list.parameters.index_review_evidence",
                "output_schema": "IndexReviewEvidenceResponse",
            },
            "get_review_context_batch": {
                "input_schema": "tools/list.parameters.get_review_context_batch",
                "output_schema": "RetrieveReviewContextBatchResponse",
            },
            "get_review_audit_trail": {
                "input_schema": "tools/list.parameters.get_review_audit_trail",
                "output_schema": "ReviewAuditTrailResponse",
            },
        },
        "response_contracts": {
            "recovery": "Top-level recovery hints appear on empty, degraded, or high-drop retrievals.",
            "quote": "Context passages include optional quote offsets for returned text and original passage text.",
            "confidence_for_grounding": (
                "Deterministic retrieval confidence for source grounding, not clinical "
                "certainty. Serialized passages expose level plus compact basis codes."
            ),
            "dropped_summary": "Structured dropped-passage reason counts plus bounded filter and budget advice.",
        },
    }
    if profile is not None:
        allowed_tools = tool_names_for_profile(profile)
        if profile == "readonly":
            contract["core_workflow_tools"] = list(READONLY_RETRIEVAL_WORKFLOW_TOOLS)
        elif profile == "lean":
            contract["core_workflow_tools"] = list(LEAN_REVIEW_WORKFLOW_TOOLS)
        else:
            contract["core_workflow_tools"] = [
                name for name in contract["core_workflow_tools"] if name in allowed_tools
            ]
        contract["schema_bundle"] = {
            name: schema
            for name, schema in contract["schema_bundle"].items()
            if name in allowed_tools
        }
    return contract
