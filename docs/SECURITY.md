# Security & Deployment Posture

PubTator-Link is **unauthenticated by design**. Edge authentication is owned by the
GeneFoundry router / reverse proxy at the trust boundary; the backend must be reachable
**only** through that proxy, never published directly to a LAN or the internet.

## MCP tool profiles (`PUBTATOR_LINK_MCP_PROFILE`)

- `lean` (default) — read + the review-index write tool (`index_review_evidence`).
- `readonly` — strips all write tools (`index_review_evidence`, `record_review_context`,
  `submit_text_annotation`, `export_review_audit_bundle`, `stage_research_session`, ...).
  Use this for any instance that could be reached without the proxy in front.
- `full` — enables the complete write surface, including audit-bundle file export.
  Run `full` **only** behind the router/proxy.

## Write-surface hardening (issue #85)

- `PUBTATOR_LINK_REVIEW_EXPORT_BASE_DIR` — base directory that `export_review_audit_bundle`
  `export_path` writes must canonically resolve within. **Unset disables file export**
  (inline/compact responses still work). Set it to a dedicated, mounted export volume.
- `index_review_evidence` caps `pmids` and `curated_urls` at 200 entries each.
- `PUBTATOR_LINK_TRUST_PROXY_HEADERS` — set `true` only when a known reverse proxy sits in
  front; the inbound rate limiter then keys on the rightmost `X-Forwarded-For` entry.
  Leave `false` (default) when directly reachable — the leftmost XFF value is client-spoofable.
- The default `docker/docker-compose.yml` publishes the app port to `127.0.0.1` only;
  `docker-compose.prod.yml` drops published ports entirely (expose-only behind the proxy).

## trust_proxy_headers

See `PUBTATOR_LINK_TRUST_PROXY_HEADERS` above. When enabled, the rate limiter keys on the
rightmost entry in `X-Forwarded-For`. When disabled (default), the socket peer IP is used,
preventing header-spoofing attacks.

## review_export_base_dir

See `PUBTATOR_LINK_REVIEW_EXPORT_BASE_DIR` above. The mcp_profile `full` is required to
expose `export_review_audit_bundle` at all; the base dir setting then confines writes within
a dedicated directory, preventing path traversal.

Research use only. Not clinical decision support.
