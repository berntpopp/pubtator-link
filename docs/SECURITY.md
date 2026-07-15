# Security & Deployment Posture

Caller authentication and write authorization are owned by the GeneFoundry router at the
trust boundary. Production PubTator-Link additionally requires a router-owned service bearer
token on `/mcp`; `/health` remains unauthenticated for container probes. The backend must be
reachable **only** through the router/proxy, never published directly to a LAN or the internet.

## MCP tool profiles (`PUBTATOR_LINK_MCP_PROFILE`)

- `readonly` (default) — exposes all read tools and strips the canonical write inventory.
- `lean` — read tools plus a subset of review-index write tools. It requires service auth unless
  a direct development process explicitly enables the loopback-only exception.
- `full` — enables the complete write surface, including audit-bundle file export.
  Run `full` **only** behind the authenticated router/proxy.

## Backend service token

The production `/mcp` endpoint serves **read-only** public PubTator3 literature data
(`PUBTATOR_LINK_MCP_PROFILE=readonly`, unauthenticated writes disabled) and is deliberately
left **open**: a direct unauthenticated `/mcp` request returns `200`, and `/health` remains
available. Because only public read-only data is exposed, the transport is not bearer-gated by
default.

`PUBTATOR_LINK_MCP_SERVICE_TOKEN` is an **optional** transport credential. When set, it installs
`MCPServiceAuthMiddleware`, which bearer-gates the entire `/mcp` path (a request without the
token then returns `401`). Use it for private deployments, to restrict the transport to a
trusted caller, or when running a write-capable profile. Generate a dedicated token with
`openssl rand -hex 32`. It is a service credential, not a caller credential; do not reuse or
forward caller OAuth tokens and do not place the value in Compose YAML, logs, issue comments, or
source control. The token protects the MCP transport only; REST routes remain dependent on edge
authentication, so the reverse proxy must not publish this backend as a general REST origin.

When a token is configured, set the same value as `GF_PUBTATOR_TOKEN` on the router. Rotation of
the single configured token then requires a coordinated router/backend deployment window; verify
router read calls after rotation and revoke the old value immediately.

Direct host development may set `PUBTATOR_LINK_ALLOW_UNAUTHENTICATED_WRITES=true` only while
binding to `127.0.0.1`, `::1`, or `localhost`. Docker binds inside its container to `0.0.0.0`, so
the base Compose stack stays read-only by default. To exercise writes in Compose, set a random
service token and explicitly select `PUBTATOR_LINK_MCP_PROFILE=lean` or `full`.

## Write-surface hardening (issue #85)

- `PUBTATOR_LINK_REVIEW_EXPORT_BASE_DIR` — base directory for server-generated
  `export_review_audit_bundle` files. Callers request `save_to_file=true` but never select a
  path. Files use generated names, exclusive no-follow creation, and mode `0600`. **Unset
  disables file export** (inline/compact responses still work). Set it to a dedicated, mounted
  export volume.
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

See `PUBTATOR_LINK_REVIEW_EXPORT_BASE_DIR` above. The mcp_profile `full` is required to expose
`export_review_audit_bundle`; the server creates the leaf beneath the configured directory.

Docker networking is not an egress firewall. Hospital deployments require a host or network
egress policy in addition to the inbound router boundary.

## Repository security settings (F-18: GitHub secret scanning)

GitHub **secret scanning** and **push protection** are repository settings, not something a
workflow or source change can enable. They are the last line of defence against a credential
(service token, DB password, API key) being committed to history — push protection blocks the
push before the secret lands. This repository already runs CodeQL; secret scanning must be
enabled as an operator action.

Enable both (operator, with a token that has admin on the repo):

```bash
gh api -X PATCH repos/berntpopp/pubtator-link \
  -f 'security_and_analysis[secret_scanning][status]=enabled' \
  -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
```

Verify:

```bash
gh api repos/berntpopp/pubtator-link --jq '.security_and_analysis'
```

Both `secret_scanning.status` and `secret_scanning_push_protection.status` must read `enabled`.
If a committed secret is ever detected, treat it as exposed: rotate it immediately (see the
service-token and DB-password rotation notes above) and purge it from history.

Research use only. Not clinical decision support.
