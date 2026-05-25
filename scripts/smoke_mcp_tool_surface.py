from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


CALLS: list[tuple[str, dict[str, Any], int]] = [
    (
        "pubtator_convert_article_ids",
        {
            "ids": ["24166952", "PMC12758588", "10.1038/s41431-022-01127-3"],
            "source": "auto",
        },
        12_000,
    ),
    (
        "pubtator_preflight_review_sources",
        {"pmids": ["24166952", "42135612"]},
        12_000,
    ),
    (
        "pubtator_submit_text_annotation",
        {
            "text": (
                "Familial Mediterranean fever is associated with MEFV variants "
                "and colchicine."
            ),
            "bioconcepts": "Gene,Disease,Chemical",
        },
        12_000,
    ),
    (
        "pubtator_find_entity_relations",
        {
            "entity_id": "@GENE_MEFV",
            "limit": 10,
            "response_mode": "compact",
            "max_response_chars": 12_000,
        },
        12_000,
    ),
    (
        "pubtator_export_review_audit_bundle",
        {"review_id": "mefv-vus-smoke", "fallback_inline": True},
        20_000,
    ),
]


def call_tool(base_url: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
    response.raise_for_status()
    envelope = response.json()
    if "error" in envelope:
        return {"success": False, "transport_error": envelope["error"]}
    text = envelope["result"]["content"][0]["text"]
    payload = json.loads(text)
    payload["_response_chars"] = len(text)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    args = parser.parse_args()

    failed = False
    for name, arguments, max_chars in CALLS:
        payload = call_tool(args.base_url, name, arguments)
        summary = {
            "tool": name,
            "success": payload.get("success"),
            "error_code": payload.get("error_code"),
            "response_chars": payload.get("_response_chars"),
        }
        print(json.dumps(summary, sort_keys=True))
        if payload.get("success") is not True:
            failed = True
        if int(payload.get("_response_chars") or 0) > max_chars:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
