from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx


CALLS: list[tuple[str, dict[str, Any], dict[str, Any] | None]] = [
    ("pubtator_search_literature", {"query": "MEFV colchicine pediatric", "limit": 3}, None),
    ("pubtator_search_guidelines", {"query": "familial mediterranean fever pediatric"}, None),
    ("pubtator_search_biomedical_entities", {"text": "MEFV", "concept": "Gene"}, None),
    ("pubtator_lookup_mesh", {"text": "familial Mediterranean fever", "limit": 3}, None),
    ("pubtator_get_publication_passages", {"pmid": "42135612", "mode": "compact_passages"}, None),
    ("pubtator_estimate_publication_context", {"pmid": "42135612"}, None),
    (
        "pubtator_submit_text_annotation",
        {"text": "MEFV and colchicine are relevant to FMF.", "bioconcepts": "Gene,Chemical"},
        None,
    ),
    (
        "pubtator_search_biomedical_entities",
        {"query": "MEFV", "bogus": True},
        {"query": "MEFV"},
    ),
]


def call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], int, int]:
    started = time.perf_counter()
    response = httpx.post(
        f"{base_url.rstrip('/')}/mcp",
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": name,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        timeout=60,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.raise_for_status()
    envelope = response.json()
    if "error" in envelope:
        text = json.dumps(envelope["error"], sort_keys=True)
        return {"success": False, "transport_error": envelope["error"]}, len(text), elapsed_ms
    text = envelope["result"]["content"][0]["text"]
    return json.loads(text), len(text), elapsed_ms


def summarize_call(
    *,
    tool: str,
    payload: dict[str, Any],
    response_chars: int,
    elapsed_ms: int,
    retry_payload: dict[str, Any] | None = None,
    retry_response_chars: int | None = None,
    retry_elapsed_ms: int | None = None,
) -> dict[str, Any]:
    first_call_success = _payload_succeeded(payload)
    one_retry_success = _payload_succeeded(retry_payload or payload)
    return {
        "tool": tool,
        "success": payload.get("success"),
        "error_code": payload.get("error_code"),
        "first_call_success": first_call_success,
        "one_retry_success": one_retry_success,
        "response_chars": response_chars,
        "retry_response_chars": retry_response_chars,
        "elapsed_ms": elapsed_ms,
        "retry_elapsed_ms": retry_elapsed_ms,
    }


def _payload_succeeded(payload: dict[str, Any]) -> bool:
    if payload.get("success") is False:
        return False
    return "error_code" not in payload and "transport_error" not in payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--max-response-chars", type=int, default=20_000)
    args = parser.parse_args()

    failed = False
    for name, arguments, retry_arguments in CALLS:
        payload, response_chars, elapsed_ms = call_tool(args.base_url, name, arguments)
        retry_payload = None
        retry_response_chars = None
        retry_elapsed_ms = None
        if payload.get("success") is not True and retry_arguments is not None:
            retry_payload, retry_response_chars, retry_elapsed_ms = call_tool(
                args.base_url, name, retry_arguments
            )
        summary = summarize_call(
            tool=name,
            payload=payload,
            response_chars=response_chars,
            elapsed_ms=elapsed_ms,
            retry_payload=retry_payload,
            retry_response_chars=retry_response_chars,
            retry_elapsed_ms=retry_elapsed_ms,
        )
        print(json.dumps(summary, sort_keys=True))
        if summary["one_retry_success"] is not True:
            failed = True
        if response_chars > args.max_response_chars:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
