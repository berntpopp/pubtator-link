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
