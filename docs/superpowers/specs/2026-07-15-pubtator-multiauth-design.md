# PubTator-Link MultiAuth (OAuth + service token) — Design

**Date:** 2026-07-15
**Status:** Draft for review
**Author:** Bernt Popp (with Claude)
**Repo:** `pubtator-link`

## 1. Problem

PubTator-Link is the only fleet backend with a **write-capable** surface (the
review / re-RAG tools backed by PostgreSQL). Its production deployment currently
mandates a static router-owned bearer token on `/mcp` while running the
`readonly` profile — so it demands a credential to serve a read-only surface, and
direct clients (notably the claude.ai connector) hit a bare `401 WWW-Authenticate:
Bearer` that they interpret as a broken OAuth challenge. That is the regression
users are reporting.

We want **one** deployment that serves two audiences from the same `/mcp`:

- **Standalone users** ("only PubTator") — claude.ai connectors and
  header-capable clients (Claude Code / API / scripts) — log in via **OAuth
  (Keycloak)** and get the **full, writeable** tool surface.
- **The GeneFoundry router** — reaches the same full surface **without forwarding
  the caller's token** (the no-token-passthrough / confused-deputy rule).

## 2. Goals / Non-goals

**Goals**
- Single instance, single `/mcp`, `full` profile, serving both audiences.
- Standalone auth via Keycloak OAuth; router auth via its existing static service
  token — both accepted on the same endpoint.
- Default policy: **every authenticated caller can write** (authn ⇒ full), with a
  one-env-var path to tighten to scope-gated writes later.
- Backwards-compatible and safe to release **before** Keycloak is configured.

**Non-goals**
- Anonymous (no-login) access on the OAuth endpoint. MCP auth is transport-level
  all-or-nothing; anonymous reads + authed writes cannot share one mount. (If ever
  needed, a second mount path is the future extension — out of scope here.)
- Configuring Keycloak. Real realm/client/redirect values live in the deploy
  environment; this repo ships only env-driven code + an operator runbook.
- Changing the router. It already sends its static token and already gates
  federated PubTator writes on `pubtator:write` at its own edge.

## 3. Locked decisions

| # | Decision | Choice |
|---|----------|--------|
| D1 | Base branch | Stack on `fix/mcp-contract-hardening-126`; **commit only non-WIP files**, leave the contract-hardening WIP uncommitted and untouched. |
| D2 | Write default | Port `WriteAuthorizationMiddleware`; add `require_write_scope` (**default False** = write-for-all-authenticated). |
| D3 | Release | Implement + commit the feature now; **defer** version bump / CHANGELOG / tag until the WIP lands (both files are WIP-owned). |
| D4 | Keycloak | PubTator gets its **own** Keycloak client + **own** audience (its resource URI), reusing the router's realm. |
| D5 | Auth mode | New `PUBTATOR_LINK_AUTH_MODE` (`none` \| `oauth`), **default `none`** for a safe, back-compatible release. |
| D6 | Wiring point | Attach `mcp.auth` in `server_manager.py` **after** `create_pubtator_mcp()` — avoids editing WIP `facade.py`. |

## 4. Architecture

### 4.1 New module `pubtator_link/auth.py`
`build_auth(settings) -> AuthProvider | None`, mirroring the router's `auth.py`:

- **`auth_mode == "none"`** → return `None`. `/mcp` behaves exactly as today: open,
  or bearer-gated iff `mcp_service_token` is set (the existing
  `MCPServiceAuthMiddleware` path is retained for this mode). Fully backwards
  compatible.
- **`auth_mode == "oauth"`** → return:
  ```
  MultiAuth(
      server=OAuthProxy(
          upstream_authorization_endpoint=<keycloak authorize>,
          upstream_token_endpoint=<keycloak token>,
          upstream_client_id=<pubtator client id>,
          upstream_client_secret=<pubtator client secret>,
          token_verifier=jwt_verifier,
          base_url=<public root origin>,
          resource_base_url=<public ROOT origin>,   # NOT the audience — avoids /mcp/mcp
          jwt_signing_key=<fixed key>,
          require_authorization_consent="external",
      ),
      verifiers=[
          jwt_verifier,                              # Keycloak JWTs (M2M / header clients)
          StaticTokenVerifier({service_token: {     # the router's credential
              "client_id": "genefoundry-router",
              "scopes": ["pubtator:read", "pubtator:write"],
          }}),
      ],
  )
  ```
  where `jwt_verifier = JWTVerifier(jwks_uri, issuer, audience=<pubtator resource
  URI>, base_url=<public root>)`.

`MultiAuth.verify_token` tries the OAuth server, then each verifier in order;
`get_routes`/`get_well_known_routes` delegate to the OAuthProxy so PubTator serves
proper Protected-Resource-Metadata (RFC 9728) and claude.ai completes the flow.
All classes (`MultiAuth`, `OAuthProxy`, `JWTVerifier`, `StaticTokenVerifier`,
`RemoteAuthProvider`) exist in the installed `fastmcp 3.4.2`; JWT deps (pyjwt,
cryptography, authlib) are already present — **no dependency changes**.

### 4.2 Wiring — `pubtator_link/server_manager.py` (not a WIP file)
In `create_app`, between building the MCP server and its HTTP app:
```python
mcp = create_pubtator_mcp()
mcp.auth = build_auth(settings)     # NEW — None in `none` mode
mcp_http_app = mcp.http_app(path=settings.mcp_path, json_response=True, ...)
```
`http_app()` reads `self.auth` at call time (`fastmcp/server/mixins/transport.py`),
installing `RequireAuthMiddleware` and mounting the well-known auth routes. No
change to `facade.py` (WIP). The existing token-only `MCPServiceAuthMiddleware`
install stays for `none` mode; in `oauth` mode the `StaticTokenVerifier` covers the
router, so the standalone middleware is skipped to avoid double-gating.

### 4.3 Write authorization — new `pubtator_link/authorization.py`
Port the router's `WriteAuthorizationMiddleware` (FastMCP `Middleware.on_call_tool`)
that maps PubTator's `full`-only write tools and requires `pubtator:write` in the
access-token scopes — **guarded by `settings.require_write_scope` (default False)**,
so by default it is a no-op and every authenticated caller may write. Registered
only when `auth_mode == "oauth"`.

### 4.4 Profile
`full` is selected purely via `PUBTATOR_LINK_MCP_PROFILE` (already falls back to
`settings.mcp_profile` in `create_pubtator_mcp`). No code change; a deployment
selects `full` in its env. The existing config validator still refuses a
write-capable profile on a non-loopback bind without a token — preserved.

## 5. Config surface (`config.py`, not a WIP file)

| Env var | Default | Meaning |
|---------|---------|---------|
| `PUBTATOR_LINK_AUTH_MODE` | `none` | `none` \| `oauth` |
| `PUBTATOR_LINK_OAUTH_AUTHORIZE_URL` / `_TOKEN_URL` | — | Keycloak endpoints (oauth) |
| `PUBTATOR_LINK_OAUTH_CLIENT_ID` / `_CLIENT_SECRET` | — | PubTator's own Keycloak client |
| `PUBTATOR_LINK_JWT_ISSUER` / `_JWKS_URL` / `_AUDIENCE` | — | audience = PubTator resource URI (MUST) |
| `PUBTATOR_LINK_PUBLIC_BASE_URL` | — | public ROOT origin (PRM / resource base) |
| `PUBTATOR_LINK_OAUTH_JWT_SIGNING_KEY` | — | stable key for OAuthProxy token/client store |
| `PUBTATOR_LINK_REQUIRE_WRITE_SCOPE` | `false` | tighten writes to `pubtator:write` |
| `PUBTATOR_LINK_MCP_SERVICE_TOKEN` | — | router credential (StaticTokenVerifier in oauth mode) |

`oauth` mode validates that the required OAuth/JWT vars are present and raises a
clear `ConfigurationError` if not (same pattern as the router). `none` mode ignores
them.

## 6. Auth / authz flows

| Caller | Credential | Verified by | Writes (default) |
|--------|-----------|-------------|------------------|
| claude.ai connector | Keycloak OAuth (Authorization Code + PKCE via OAuthProxy) | JWT verifier | yes |
| Claude Code / API / script | Keycloak JWT (or same OAuth) | JWT verifier | yes |
| GeneFoundry router | static `GF_PUBTATOR_TOKEN` → `PUBTATOR_LINK_MCP_SERVICE_TOKEN` | StaticTokenVerifier | yes |

All hit the same `/mcp`, same `full` tools, one container. "Write for standalone
users" is the default; flipping `REQUIRE_WRITE_SCOPE=true` reserves writes for
Keycloak-granted `pubtator:write` without a code change.

## 7. Security invariants

- **No token passthrough** — the router uses its own static credential, a distinct
  `StaticTokenVerifier` principal; the caller's OAuth token is never forwarded.
- **Audience binding** — `JWTVerifier(audience=<pubtator resource URI>)` rejects
  tokens minted for the router or any other backend (no cross-resource replay).
- **`/mcp/mcp` trap avoided** — `resource_base_url` is the root origin, not the
  audience (the router documented and test-pinned this exact bug).
- **Write-capable self-gating** — the existing validator blocks `full` on a public
  bind without a token, so the endpoint can never be simultaneously open and
  writeable.

## 8. Backwards compatibility & safe release

`AUTH_MODE=none` default ⇒ the published image boots identically to today
everywhere, before Keycloak exists. Go-live is an **operator flip**: configure
Keycloak → set `AUTH_MODE=oauth`, `MCP_PROFILE=full`, the OAuth/JWT env, the service
token, and a persistent `FASTMCP_HOME` volume (OAuthProxy client store) → redeploy.
The prod compose ships this as a **commented, ready-to-enable block** — never
forced — so a deploy cannot crash on missing Keycloak config.

## 9. Keycloak operator runbook (deploy-time, not in this repo)

1. In the router's existing realm, create a **confidential client** for PubTator
   (its own `client_id` + secret).
2. Set the token **audience** to PubTator's resource URI
   (`https://pubtator-link.genefoundry.org/mcp`).
3. Define roles/scopes `pubtator:read`, `pubtator:write` (and optionally
   `pubtator:admin` for destructive index deletion). For the "everyone can write"
   default, `pubtator:write` gating stays off (`REQUIRE_WRITE_SCOPE=false`); to
   tighten later, grant `pubtator:write` to the intended role and flip the flag.
4. Register the claude.ai connector redirect URI(s).
5. Populate the PubTator env vars from §5 and set `AUTH_MODE=oauth`, `MCP_PROFILE=full`.

## 10. Commit discipline (D1)

Work on `fix/mcp-contract-hardening-126`. Stage **only** these (all non-WIP):
`pubtator_link/config.py`, new `pubtator_link/auth.py`, `pubtator_link/server_manager.py`,
new `pubtator_link/authorization.py`, `docker/docker-compose.prod.yml`,
`.env.example` / `.env.docker.example`, new test files under `tests/`,
`docs/SECURITY.md`, and this spec. **Never** `git add -A`; never stage the
contract-hardening WIP (`facade.py`, `mcp/**`, `pyproject.toml`, `uv.lock`,
`CHANGELOG.md`, `docs/mcp-tool-catalog.md`, WIP test files, etc.).

## 11. Testing (TDD)

- `none` mode: no auth provider; `/mcp` open (and token-gated when a token is set) —
  back-compat.
- `oauth` mode unit tests (verifier-level, no live Keycloak):
  - service token accepted → principal with `pubtator:write`.
  - Keycloak JWT: valid accepted; bad signature rejected; **wrong audience rejected**.
  - write-default-open: a write tool succeeds for any authenticated principal.
  - `require_write_scope=true`: write tool denied without `pubtator:write`, allowed with.
  - PRM served; advertised resource URI == audience (no `/mcp/mcp`).
- `make ci-local` green (format, lint, lint-loc 600-LOC budget, mypy, tests).

## 12. Release plan (deferred — D3)

After the contract-hardening WIP lands: minor bump `7.0.0 → 7.1.0`, CHANGELOG entry,
tag, push (triggers `container-release` + registry publish). Release notes include
the §9 Keycloak runbook and the go-live flip from §8.

## 13. Risks

- **FastMCP 3.x drift** — symbols verified against installed 3.4.2; the integration
  test is the contract. Re-verify if the pinned version changes.
- **OAuthProxy client-store persistence** — requires the `FASTMCP_HOME` volume, or
  DCR clients are lost on restart (router precedent).
- **600-LOC budget** — `auth.py` + `authorization.py` are new small modules; keep
  each well under budget.
- **WIP interplay** — the contract-hardening branch touches `facade.py`/`mcp/**`;
  the design deliberately avoids those files so the two efforts don't conflict.

---

## Revision 2 — post-Codex (gpt-5.6-sol, high) adversarial review

One adversarial pass (no cycles). Verdict was RETHINK; findings folded in below.
Environment correction: pubtator's real venv is **fastmcp 3.4.4** (not 3.4.2) — all
API re-verified against 3.4.4.

### User decisions
- **REST surface (finding #1):** in `oauth` mode, **disable the mutating REST review
  routes** (the writable surface becomes MCP-only). Read-only REST may remain.
- **Write default (finding #2):** keep write-for-all-authenticated
  (`require_write_scope=false`); the cross-user-corruption / resource-exhaustion risk on
  the shared review DB is **documented and accepted**, with per-subject ownership +
  quotas filed as a follow-up (bind reviews to `AccessToken.subject`).

### Finding resolutions
1. **[CRITICAL] REST bypass** — `server_manager.py:401-410` registers REST routers
   (incl. `reviews_router` writes/DELETE) before `app.mount("/", mcp_http_app)`; MCP auth
   never covers them. Fix: skip the mutating review routes when `auth_mode=="oauth"`;
   add anonymous-denial tests.
2. **[CRITICAL] cross-user writes** — accepted per decision above; documented risk +
   ownership follow-up.
3. **[CRITICAL] open DCR redirect + `"external"` consent** — set OAuthProxy
   `allowed_client_redirect_uris` to the approved claude.ai + loopback patterns (the
   router lacks this too — separate fleet fix). Keep consent configurable.
4. **[HIGH] fastmcp version** — verified against 3.4.4; `http_app` kwargs are valid there.
5. **[HIGH] `Settings`→`ServerSettings`** — the class is `ServerSettings` with a global
   `settings`; all code/tests use those.
6. **[HIGH] write-tool set** — import the authoritative 8-name `WRITE_TOOLS` from
   `pubtator_link.mcp.profiles`; never hand-maintain the list.
7. **[HIGH] `/mcp/mcp`** — `validate_oauth_config` asserts `public_base_url` is an HTTPS
   origin with no path and `jwt_audience == public_base_url.rstrip('/') + mcp_path`.
8. **[HIGH] Keycloak redirect** — register the OAuthProxy callback
   `PUBLIC_BASE_URL/auth/callback` in Keycloak; claude.ai redirects go in
   `allowed_client_redirect_uris`, not Keycloak.
9. **[HIGH] FASTMCP_HOME** — use `/home/app/.fastmcp` (image user `app`), created+chowned
   in the Dockerfile; OAuth-mode smoke test as the real UID.
10. **[HIGH] ALLOWED_HOSTS** — make configurable; include the public host in the go-live
    block.
11. **[HIGH] weak tests** — real `FastMCP` app inside `with TestClient(app)`; assert 200 +
    valid initialize JSON-RPC result, anonymous 401, fetch `/.well-known/oauth-protected-
    resource/mcp`, and crypto JWT valid/bad-sig/wrong-audience.
12. **[HIGH] required inputs** — `oauth` mode requires `oauth_jwt_signing_key` AND
    `mcp_service_token` (else the router verifier is silently absent and token signing
    follows the KC client secret).
13. **[MEDIUM] Keycloak scopes** — JWTVerifier reads `scope`/`scp`, not
    `realm_access.roles`; pass `valid_scopes=["pubtator:read","pubtator:write"]` and
    document a Keycloak mapper emitting the scopes.
14. **[MEDIUM] WIP-leak check** — diff all changed paths from the fixed feature base
    against an exact allowlist; fail on any unmatched path.
