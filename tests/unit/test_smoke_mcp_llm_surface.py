from __future__ import annotations


def test_smoke_surface_summary_tracks_retry_success_and_payload_size() -> None:
    from scripts.smoke_mcp_llm_surface import summarize_call

    summary = summarize_call(
        tool="pubtator_search_literature",
        payload={"success": True, "results": [{"pmid": "42135612"}]},
        response_chars=2048,
        elapsed_ms=123,
        retry_payload={"success": True},
        retry_response_chars=1024,
        retry_elapsed_ms=50,
    )

    assert summary == {
        "tool": "pubtator_search_literature",
        "success": True,
        "error_code": None,
        "first_call_success": True,
        "one_retry_success": True,
        "response_chars": 2048,
        "retry_response_chars": 1024,
        "elapsed_ms": 123,
        "retry_elapsed_ms": 50,
    }
