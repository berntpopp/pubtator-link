from __future__ import annotations

import json

from pubtator_link.mcp.resources import get_capabilities_resource


def test_default_capabilities_are_small_and_skeletal() -> None:
    payload = get_capabilities_resource()
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)

    assert len(serialized) <= 2500
    assert payload["core_workflow_tools"]
    assert payload["tool_categories"]
    assert "sample_calls" not in payload
    assert "schema_policy" not in payload
    assert "recommended_workflows" not in payload


def test_capabilities_details_are_opt_in() -> None:
    payload = get_capabilities_resource(details=["sample_calls", "schema_policy"])

    assert payload["details"]["sample_calls"]["pubtator.search_literature"]["text"]
    assert "singleton string" in payload["details"]["schema_policy"]["list_inputs"].lower()


def test_batch_retrieval_sample_omits_auto_fit_budget_arguments() -> None:
    payload = get_capabilities_resource(details=["sample_calls"])
    sample = payload["details"]["sample_calls"]["pubtator.retrieve_review_context_batch"]

    assert "max_chars" not in sample
    assert "max_response_chars" not in sample


def test_capabilities_document_guideline_search_as_filtered_literature_search() -> None:
    payload = get_capabilities_resource(details=["sample_calls", "schema_policy"])
    sample_call = payload["details"]["sample_calls"]["pubtator.search_guidelines"]
    guideline_search = payload["details"]["schema_policy"]["guideline_search"]
    guideline_search_text = json.dumps(guideline_search).lower()

    assert "relationship" not in sample_call
    assert "search_literature" in guideline_search_text
    assert "publication_types" in guideline_search_text
    assert "filtered" in guideline_search_text
    assert "guideline" in guideline_search_text


def test_preferred_tool_names_are_documented_without_breaking_existing_names() -> None:
    payload = get_capabilities_resource(details=["schema_policy"])
    preferred = payload["details"]["schema_policy"]["preferred_tool_names"]

    assert preferred["retrieve_review_context_batch"] == "pubtator.retrieve_review_context_batch"
    assert "pubtator.retrieve_review_context_batch" in payload["core_workflow_tools"]
