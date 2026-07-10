from __future__ import annotations

from typing import Any


def compact_audit_bundle_summary(bundle_json: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": bundle_json.get("review_id"),
        "session_id": bundle_json.get("session_id"),
        "generated_at": bundle_json.get("generated_at"),
        "preparation_status": bundle_json.get("preparation_status"),
        "totals": bundle_json.get("totals"),
        "coverage_distribution": bundle_json.get("coverage_distribution"),
        "source_count": len(bundle_json.get("sources") or []),
        "failed_source_count": len(bundle_json.get("failed_sources") or []),
        "resolver_attempt_count": len(bundle_json.get("resolver_attempts") or []),
        "search_run_count": len(bundle_json.get("search_runs") or []),
        "retrieval_run_count": len(bundle_json.get("retrieval_runs") or []),
        "evidence_certainty_count": len(bundle_json.get("evidence_certainty") or []),
        "research_session_count": len(bundle_json.get("research_sessions") or []),
        "passage_id_count": len(bundle_json.get("passage_ids") or []),
        "stable_citation_key_count": len(bundle_json.get("stable_citation_keys") or {}),
        "index_snapshot_date": bundle_json.get("index_snapshot_date"),
        "omitted_fields": [
            "sources",
            "failed_sources",
            "resolver_attempts",
            "search_runs",
            "retrieval_runs",
            "evidence_certainty",
            "research_sessions",
            "passage_ids",
            "stable_citation_keys",
        ],
        "next_tools": ["export_review_audit_bundle"],
        "recovery": [
            "Pass save_to_file=true to write the full audit bundle without inline token cost."
        ],
    }
