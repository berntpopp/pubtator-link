from __future__ import annotations

from typing import Any

from pubtator_link.config import api_config, text_processing_config

RESEARCH_USE_NOTICE = (
    "Research and biomedical literature exploration use only; not for diagnosis, "
    "treatment, triage, patient management, or clinical decision support. Do not "
    "submit identifiable patient data to public demo instances."
)


def get_capabilities_resource() -> dict[str, Any]:
    return {
        "server": "pubtator-link",
        "transport": "streamable_http",
        "endpoint": "/mcp",
        "tools": [
            "pubtator.search_literature_v2",
            "pubtator.search_literature",
            "pubtator.get_publication_passages_v2",
            "pubtator.get_publication_passages",
            "pubtator.estimate_publication_context",
            "pubtator.fetch_publication_annotations",
            "pubtator.fetch_pmc_annotations",
            "pubtator.search_biomedical_entities_v2",
            "pubtator.search_biomedical_entities",
            "pubtator.find_entity_relations",
            "pubtator.submit_text_annotation",
            "pubtator.get_text_annotation_results",
            "pubtator.index_review_evidence",
            "pubtator.inspect_review_index_v2",
            "pubtator.inspect_review_index",
            "pubtator.retrieve_review_context_v2",
            "pubtator.retrieve_review_context",
            "pubtator.retrieve_review_context_batch_v2",
            "pubtator.retrieve_review_context_batch",
            "pubtator.get_server_capabilities",
        ],
        "recommended_workflows": [
            "search -> index -> inspect -> retrieve for review-grounded answers",
            "publication passages -> context estimate -> compact passage retrieval before raw BioC",
        ],
        "tool_groups": {
            "literature_search": [
                "pubtator.search_literature_v2",
                "pubtator.search_literature",
            ],
            "publication_grounding": [
                "pubtator.get_publication_passages_v2",
                "pubtator.get_publication_passages",
                "pubtator.estimate_publication_context",
                "pubtator.fetch_publication_annotations",
                "pubtator.fetch_pmc_annotations",
            ],
            "review_grounding": [
                "pubtator.index_review_evidence",
                "pubtator.inspect_review_index_v2",
                "pubtator.inspect_review_index",
                "pubtator.retrieve_review_context_v2",
                "pubtator.retrieve_review_context",
                "pubtator.retrieve_review_context_batch_v2",
                "pubtator.retrieve_review_context_batch",
            ],
            "entities_relations": [
                "pubtator.search_biomedical_entities_v2",
                "pubtator.search_biomedical_entities",
                "pubtator.find_entity_relations",
            ],
            "text_annotation": [
                "pubtator.submit_text_annotation",
                "pubtator.get_text_annotation_results",
            ],
        },
        "large_output_guidance": {
            "prefer": "pubtator.get_publication_passages_v2",
            "avoid_by_default": "pubtator.fetch_publication_annotations full=true",
            "reason": "raw full BioC can be multi-megabyte; compact tools return citable passages",
        },
        "sample_calls": {
            "pubtator.search_literature_v2": {
                "text": "MEFV colchicine familial Mediterranean fever guideline",
                "sort": "score desc",
            },
            "pubtator.get_publication_passages_v2": {
                "pmids": ["40234174"],
                "mode": "compact_passages",
                "max_chars": 12000,
            },
            "pubtator.retrieve_review_context_batch_v2": {
                "review_id": "fmf-colchicine-guidelines",
                "queries": [
                    "MEFV colchicine",
                    "familial Mediterranean fever child",
                    "EULAR PReS recommendation",
                ],
                "response_mode": "compact",
                "max_chars": 12000,
                "max_response_chars": 24000,
            },
            "pubtator.retrieve_review_context_batch_v2_diagnostics": {
                "review_id": "fmf-colchicine-guidelines",
                "queries": ["MEFV colchicine", "FMF guideline"],
                "response_mode": "diagnostics",
            },
        },
        "output_cheatsheet": {
            "search_pmids": "results[].pmid",
            "single_context_passages": "context_pack.passages[]",
            "batch_merged_passages": "merged_context_pack.passages[]",
            "batch_query_summaries": "query_summaries[]",
            "citation_map": "merged_context_pack.citation_map",
            "budget": "budget",
        },
        "budgeting_defaults": {
            "batch_response_mode": "compact",
            "batch_max_chars": 12000,
            "batch_max_response_chars": 24000,
            "max_chars_per_passage": 2200,
            "tables": "excluded by default for review retrieval unless explicitly requested",
        },
        "review_rerag": {
            "tools": [
                "pubtator.index_review_evidence",
                "pubtator.inspect_review_index_v2",
                "pubtator.inspect_review_index",
                "pubtator.retrieve_review_context_v2",
                "pubtator.retrieve_review_context",
                "pubtator.retrieve_review_context_batch_v2",
                "pubtator.retrieve_review_context_batch",
            ],
            "prompt": "review_rerag_workflow",
            "scope": "research-use review-scoped evidence preparation and retrieval",
            "workflow": [
                "index candidate PMIDs or curated URLs for a stable review_id",
                "inspect the review index before retrieval to check source coverage",
                "wait for preparation_status to show complete or partial records",
                "retrieve with short keyword-style questions first",
                "retry with PMID filters for paper-specific evidence",
                "fall back to fetch_publication_annotations full=true when retrieval returns no passages",
            ],
            "limitations": [
                "single-tenant trusted POC",
                "no backend LLM",
                "retrieval depends on prepared review passages and index coverage",
                "no clinical decision support",
            ],
        },
        "notice": RESEARCH_USE_NOTICE,
    }


def get_bioconcepts_resource() -> dict[str, Any]:
    return {"bioconcepts": list(api_config.bioconcept_types)}


def get_relation_types_resource() -> dict[str, Any]:
    return {"relation_types": list(api_config.relation_types)}


def get_formats_resource() -> dict[str, Any]:
    return {"publication_formats": list(api_config.export_formats)}


def get_research_use_resource() -> dict[str, str]:
    return {"notice": RESEARCH_USE_NOTICE}


def get_text_processing_resource() -> dict[str, Any]:
    return {"supported_bioconcepts": list(text_processing_config.supported_bioconcepts)}
