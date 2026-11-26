"""The ``_meta`` every tool result leaves with.

Response-Envelope v1 section 4 (``request_id``, ``elapsed_ms`` on every result) and v1.2
(``source``, ``data_version``, ``retrieved_at`` on every success that carries upstream
data). Stamped once, at the egress every tool shares, after the tool body has shaped its
payload -- so no tool argument (``include_meta=false``) can switch a required field off.
"""

from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from pubtator_link.services.provenance import start_fetch_log, utc_now, utc_z

# Tools that orient a client and return no upstream data (outside the v1.2 rule).
OPS_TOOLS = frozenset({"get_server_capabilities", "workflow_help", "diagnostics"})
# Tools that answer from NCBI E-utilities / the PMC ID converter, not from PubTator3.
_NCBI_TOOLS = frozenset(
    {"convert_article_ids", "get_mesh", "get_citation", "find_related_articles"}
)


async def _review_evidence_fetched_at(review_id: Any) -> list[str]:
    """When a review index's stored evidence was fetched: its oldest passage."""
    if not isinstance(review_id, str):
        return []
    from pubtator_link.api.routes.dependencies import review
    from pubtator_link.api.routes.dependencies.resources import current_app_resources

    resources = current_app_resources()
    repository = resources.review_repository if resources else review._review_repository
    if repository is None:  # no review database in this process
        return []
    try:
        async with repository._acquire() as connection:
            oldest = await connection.fetchval(
                "select min(created_at) from review_passages where review_id = $1", review_id
            )
    except Exception:  # provenance lookup must never fail a tool result
        return []
    return [utc_z(oldest)] if oldest is not None else []


class EgressCall:
    """One tool call, from the moment it reached the server."""

    def __init__(self) -> None:
        self._request_id = uuid.uuid4().hex[:12]
        self._started = perf_counter()
        self._started_at = utc_now()
        self._fetches = start_fetch_log()

    async def stamp(
        self, envelope: dict[str, Any], *, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Add the required ``_meta`` fields to a success or error envelope, in place."""
        existing = envelope.get("_meta")
        meta: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
        meta["request_id"] = self._request_id
        meta["elapsed_ms"] = round((perf_counter() - self._started) * 1000, 1)
        if envelope.get("success") is True and tool_name not in OPS_TOOLS:
            # The oldest fetch dates the result: the start of this call (every live
            # upstream request follows it), an earlier fetch that filled a cache entry
            # served now, or the stored evidence of the review index that was read.
            stored = await _review_evidence_fetched_at(arguments.get("review_id"))
            meta.setdefault("source", "ncbi" if tool_name in _NCBI_TOOLS else "pubtator")
            # PubTator3 and the NCBI services behind it publish no release identifier.
            meta.setdefault("data_version", "live")
            meta.setdefault("retrieved_at", min([self._started_at, *self._fetches, *stored]))
        envelope["_meta"] = meta
        return envelope
