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

Generate a dedicated token with `openssl rand -hex 32`. Configure the same value as
`PUBTATOR_LINK_MCP_SERVICE_TOKEN` on this backend and `GF_PUBTATOR_TOKEN` on the router. The
token is a service credential, not a caller credential; do not reuse or forward caller OAuth
tokens and do not place the value in Compose YAML, logs, issue comments, or source control.
The service token protects the MCP transport only. REST routes remain dependent on edge
authentication, so the reverse proxy must not publish this backend as a general REST origin.

For the initial rollout, configure and deploy the router first while the old backend still
ignores the header, then deploy the backend that requires it. Rotation of the single configured
token requires a coordinated router/backend deployment window; verify router read calls after
rotation and revoke the old value immediately. A direct unauthenticated `/mcp` request must
return `401`, while `/health` remains available.

Direct host development may set `PUBTATOR_LINK_ALLOW_UNAUTHENTICATED_WRITES=true` only while
binding to `127.0.0.1`, `::1`, or `localhost`. Docker binds inside its container to `0.0.0.0`, so
the base Compose stack stays read-only by default. To exercise writes in Compose, set a random
service token and explicitly select `PUBTATOR_LINK_MCP_PROFILE=lean` or `full`.

## Direct OAuth access (`PUBTATOR_LINK_AUTH_MODE=oauth`)

`oauth` mode lets PubTator-Link be **published directly** and still serve one `/mcp` to two
audiences at once: standalone users (claude.ai connectors, Claude Code, scripts) who log in via
**Keycloak OAuth**, and the **router**, which presents its own static service token (never the
caller's token — no passthrough). FastMCP `MultiAuth` accepts a valid Keycloak JWT **or** the
service token; both reach the configured (`full`) tool surface. `/health` stays public.

- **Audience binding is enforced.** The JWT verifier requires `audience == PUBLIC_BASE_URL + /mcp`,
  and `PUBLIC_BASE_URL` must be a bare origin (no path) — this is validated at startup so the
  advertised protected-resource URI is never doubled to `/mcp/mcp`, and tokens minted for other
  backends are rejected.
- **REST bypass is closed.** In `oauth` mode the mutating REST review routes (`/api/reviews/*`)
  are **not registered** — they live outside the MCP mount and would otherwise be an unauthenticated
  write path to the same database. The writable surface is MCP-only.
- **Client-store persistence.** OAuthProxy stores DCR clients + upstream tokens under
  `FASTMCP_HOME` (`/home/app/.fastmcp`); mount a persistent volume there or interactive clients
  break on restart.

### Keycloak operator runbook

1. In the router's realm, create a **confidential client** for PubTator (its own id + secret).
2. Set `PUBTATOR_LINK_JWT_AUDIENCE` to PubTator's resource URI
   (`https://pubtator-link.genefoundry.org/mcp`) and add a Keycloak **audience mapper** emitting it.
3. Register the **OAuthProxy callback** `PUBLIC_BASE_URL/auth/callback` as the client's redirect URI
   in Keycloak. (claude.ai / loopback redirects are the *downstream* clients — list them in
   `PUBTATOR_LINK_OAUTH_ALLOWED_CLIENT_REDIRECT_URIS`, **not** in Keycloak.)
4. Add a Keycloak **scope/claim mapper** that emits `pubtator:read`/`pubtator:write` into the token
   `scope`/`scp` claim (the JWT verifier reads those, not `realm_access.roles`).
5. Populate the `oauth`/`jwt` env vars and set `AUTH_MODE=oauth`, `MCP_PROFILE=full`.

### Write authorization and a known risk

By default `PUBTATOR_LINK_REQUIRE_WRITE_SCOPE=false` — **every authenticated caller can write**.
On a shared review database with no per-subject ownership this means any authenticated user can
modify or exhaust another user's reviews. This is accepted for a trusted user group. To reserve
writes for a Keycloak-granted role, set `REQUIRE_WRITE_SCOPE=true` (gates the authoritative
`WRITE_TOOLS` on `pubtator:write`). **Follow-up:** bind reviews to `AccessToken.subject` + add
quotas for a genuinely multi-tenant public deployment.

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
