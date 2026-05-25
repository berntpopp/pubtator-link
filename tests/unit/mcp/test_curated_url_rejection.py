import json

from pubtator_link.mcp.errors import McpErrorContext, mcp_tool_error
from pubtator_link.services.url_safety import UrlSafetyError


def test_url_safety_error_maps_to_structured_mcp_error() -> None:
    exc = UrlSafetyError("Host 'evil.example.com' not in allowlist for curated_urls")
    error = mcp_tool_error(
        exc,
        McpErrorContext(tool_name="pubtator_index_review_evidence"),
    )
    payload = json.loads(str(error))
    assert payload["error_code"] == "curated_url_rejected"
    assert "evil.example.com" not in payload["message"]
