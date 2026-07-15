# PubTator-Link MultiAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve one PubTator `/mcp` (full profile) that accepts a Keycloak OAuth JWT (standalone users) or the router's static service token, with write-for-all-authenticated by default.

**Architecture:** A new `pubtator_link/auth.py` builds a `fastmcp` auth provider gated by `PUBTATOR_LINK_AUTH_MODE` (`none`|`oauth`, default `none`). In `oauth`, it returns `MultiAuth(server=OAuthProxy(<keycloak>), verifiers=[JWTVerifier, ServiceTokenVerifier])`. Auth is attached in `server_manager.py` **after** `create_pubtator_mcp()` (so `facade.py` WIP is untouched); `http_app()` reads `self.auth` at call time and installs enforcement + PRM routes. A ported `WriteAuthorizationMiddleware` gates writes only when `require_write_scope=true`.

**Tech Stack:** Python 3.12, FastMCP 3.4.2 (`MultiAuth`, `OAuthProxy`, `JWTVerifier`, `TokenVerifier`, `AccessToken`), Starlette, pydantic-settings, pytest.

## Global Constraints

- Python **3.12+**; `uv` for deps/venv (`uv run`, `uv sync --group dev`). **No new dependencies** (pyjwt/cryptography/authlib already present via fastmcp).
- **600-LOC per module** budget (`make lint-loc`). New `auth.py` and `authorization.py` stay well under.
- **TDD**: failing test → see it fail → minimal impl → see it pass → commit. One atomic commit per task.
- **FastMCP 3.x is post-cutoff** — the integration test is the contract; verify symbols against installed 3.4.2.
- **Commit discipline (D1):** work on branch `fix/mcp-contract-hardening-126`; stage **only** the files each task lists. **Never `git add -A`.** Never stage the contract-hardening WIP: `pubtator_link/mcp/**` (incl. `facade.py`), `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `docs/mcp-tool-catalog.md`, `.loc-allowlist`, and WIP test files under `tests/unit/mcp/**` / `tests/conformance/**`.
- **Release deferred (D3):** no version bump, CHANGELOG, or tag in this plan.
- **AUTH_MODE default `none`** — every change must keep a `none`-mode deploy byte-for-byte behaviorally identical to today (safe release before Keycloak exists).

---

### Task 1: Auth config fields + oauth-mode validation

**Files:**
- Modify: `pubtator_link/config.py` (add fields + a validator; NOT a WIP file)
- Test: `tests/unit/test_auth_config.py` (new)

**Interfaces:**
- Produces: `Settings.auth_mode: Literal["none","oauth"]`, `Settings.oauth_authorize_url/oauth_token_url/oauth_client_id/oauth_client_secret: str|None`, `Settings.jwt_issuer/jwt_jwks_url/jwt_audience: str|None`, `Settings.public_base_url: str|None`, `Settings.oauth_jwt_signing_key: str|None`, `Settings.require_write_scope: bool`, and `Settings.validate_oauth_config() -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth_config.py
import pytest
from pubtator_link.config import Settings

def _oauth_env() -> dict[str, str]:
    return {
        "PUBTATOR_LINK_AUTH_MODE": "oauth",
        "PUBTATOR_LINK_OAUTH_AUTHORIZE_URL": "https://kc.example.org/realms/gf/protocol/openid-connect/auth",
        "PUBTATOR_LINK_OAUTH_TOKEN_URL": "https://kc.example.org/realms/gf/protocol/openid-connect/token",
        "PUBTATOR_LINK_OAUTH_CLIENT_ID": "pubtator-link",
        "PUBTATOR_LINK_OAUTH_CLIENT_SECRET": "secret",
        "PUBTATOR_LINK_JWT_ISSUER": "https://kc.example.org/realms/gf",
        "PUBTATOR_LINK_JWT_JWKS_URL": "https://kc.example.org/realms/gf/protocol/openid-connect/certs",
        "PUBTATOR_LINK_JWT_AUDIENCE": "https://pubtator-link.genefoundry.org/mcp",
        "PUBTATOR_LINK_PUBLIC_BASE_URL": "https://pubtator-link.genefoundry.org",
    }

def test_auth_mode_defaults_to_none_and_ignores_missing_oauth():
    s = Settings(_env_file=None)
    assert s.auth_mode == "none"
    assert s.require_write_scope is False
    s.validate_oauth_config()  # no-op in none mode

def test_oauth_mode_requires_all_fields():
    s = Settings(_env_file=None, auth_mode="oauth")
    with pytest.raises(ValueError, match="oauth mode requires"):
        s.validate_oauth_config()

def test_oauth_mode_valid_when_all_present(monkeypatch):
    for k, v in _oauth_env().items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    s.validate_oauth_config()  # must not raise
    assert s.jwt_audience.endswith("/mcp")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_config.py -v`
Expected: FAIL — `auth_mode`/`validate_oauth_config` do not exist.

- [ ] **Step 3: Write minimal implementation**

Add to the `Settings` class in `pubtator_link/config.py` (near the existing `mcp_profile`/`mcp_service_token` fields), reusing the existing `Literal`/`Field` imports:

```python
    # --- Edge auth (AUTH_MODE=none keeps today's behavior) ---
    auth_mode: Literal["none", "oauth"] = Field(
        default="none", description="Edge auth for /mcp: none (open/token) or oauth (Keycloak + service token)"
    )
    oauth_authorize_url: str | None = Field(default=None)
    oauth_token_url: str | None = Field(default=None)
    oauth_client_id: str | None = Field(default=None)
    oauth_client_secret: str | None = Field(default=None)
    oauth_jwt_signing_key: str | None = Field(
        default=None, description="Fixed key so OAuthProxy tokens/client store survive restarts + KC secret rotation"
    )
    jwt_issuer: str | None = Field(default=None)
    jwt_jwks_url: str | None = Field(default=None)
    jwt_audience: str | None = Field(
        default=None, description="Token audience == PubTator resource URI (MUST for a protected resource)"
    )
    public_base_url: str | None = Field(
        default=None, description="Public ROOT origin (PRM/resource base); NOT the audience — avoids /mcp/mcp"
    )
    require_write_scope: bool = Field(
        default=False, description="When true, write tools require the pubtator:write scope"
    )

    def validate_oauth_config(self) -> None:
        """Fail fast if oauth mode is missing required inputs. No-op in none mode."""
        if self.auth_mode != "oauth":
            return
        required = {
            "PUBTATOR_LINK_OAUTH_AUTHORIZE_URL": self.oauth_authorize_url,
            "PUBTATOR_LINK_OAUTH_TOKEN_URL": self.oauth_token_url,
            "PUBTATOR_LINK_OAUTH_CLIENT_ID": self.oauth_client_id,
            "PUBTATOR_LINK_OAUTH_CLIENT_SECRET": self.oauth_client_secret,
            "PUBTATOR_LINK_JWT_ISSUER": self.jwt_issuer,
            "PUBTATOR_LINK_JWT_JWKS_URL": self.jwt_jwks_url,
            "PUBTATOR_LINK_JWT_AUDIENCE": self.jwt_audience,
            "PUBTATOR_LINK_PUBLIC_BASE_URL": self.public_base_url,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"oauth mode requires: {', '.join(missing)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auth_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/config.py tests/unit/test_auth_config.py
git commit -m "feat(auth): add AUTH_MODE + oauth config fields with fail-fast validation"
```

---

### Task 2: `ServiceTokenVerifier` + `build_auth` (none mode)

**Files:**
- Create: `pubtator_link/auth.py`
- Test: `tests/unit/test_auth_build.py` (new)

**Interfaces:**
- Produces: `ServiceTokenVerifier(TokenVerifier)` with `__init__(self, token: str, *, client_id: str = "genefoundry-router", scopes: list[str])`; `build_auth(settings) -> AuthProvider | None` (returns `None` in none mode).
- Consumes: `Settings` from Task 1.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth_build.py
import pytest
from pubtator_link.auth import ServiceTokenVerifier, build_auth
from pubtator_link.config import Settings

@pytest.mark.asyncio
async def test_service_token_verifier_constant_time_accept_reject():
    v = ServiceTokenVerifier("s3cret", scopes=["pubtator:read", "pubtator:write"])
    ok = await v.verify_token("s3cret")
    assert ok is not None and "pubtator:write" in ok.scopes and ok.client_id == "genefoundry-router"
    assert await v.verify_token("wrong") is None
    assert await v.verify_token("") is None

def test_build_auth_none_mode_returns_none():
    assert build_auth(Settings(_env_file=None, auth_mode="none")) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_build.py -v`
Expected: FAIL — module `pubtator_link.auth` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# pubtator_link/auth.py
"""Edge auth assembly for PubTator-Link (AUTH_MODE = none | oauth).

No-token-passthrough: the router authenticates the *caller* at its own edge and
reaches this backend with its OWN static service credential — never the caller's
OAuth token. That credential is the ServiceTokenVerifier principal here.
"""
from __future__ import annotations

import secrets
from typing import Any

from fastmcp.server.auth import AccessToken, TokenVerifier

from pubtator_link.config import Settings


class ServiceTokenVerifier(TokenVerifier):
    """Constant-time verifier for the single router-owned service token."""

    def __init__(
        self,
        token: str,
        *,
        client_id: str = "genefoundry-router",
        scopes: list[str],
    ) -> None:
        super().__init__()
        self._token = token
        self._client_id = client_id
        self._scopes = scopes

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token or not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id=self._client_id,
            scopes=list(self._scopes),
            expires_at=None,
        )


def build_auth(settings: Settings) -> Any | None:
    """Return a FastMCP auth provider for the configured mode, or None for none."""
    if settings.auth_mode == "none":
        return None
    return _build_oauth(settings)  # implemented in Task 3
```

Add a temporary stub so the module imports (Task 3 replaces it):

```python
def _build_oauth(settings: Settings) -> Any:
    raise NotImplementedError("oauth mode implemented in Task 3")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auth_build.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/auth.py tests/unit/test_auth_build.py
git commit -m "feat(auth): ServiceTokenVerifier + build_auth none-mode passthrough"
```

---

### Task 3: `build_auth` oauth mode — MultiAuth assembly

**Files:**
- Modify: `pubtator_link/auth.py` (replace `_build_oauth` stub)
- Test: `tests/unit/test_auth_build.py` (extend)

**Interfaces:**
- Consumes: `Settings` (Task 1), `ServiceTokenVerifier` (Task 2).
- Produces: `_build_oauth(settings) -> MultiAuth`. When a service token is set it is added as a verifier; the JWT verifier binds `audience=settings.jwt_audience`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auth_build.py (append)
import pytest
from fastmcp.server.auth import MultiAuth
from fastmcp.server.auth.providers.jwt import JWTVerifier

from pubtator_link.auth import ServiceTokenVerifier, build_auth
from pubtator_link.config import Settings

def _oauth_settings(**over) -> Settings:
    base = dict(
        auth_mode="oauth",
        oauth_authorize_url="https://kc.example.org/realms/gf/protocol/openid-connect/auth",
        oauth_token_url="https://kc.example.org/realms/gf/protocol/openid-connect/token",
        oauth_client_id="pubtator-link",
        oauth_client_secret="secret",
        jwt_issuer="https://kc.example.org/realms/gf",
        jwt_jwks_url="https://kc.example.org/realms/gf/protocol/openid-connect/certs",
        jwt_audience="https://pubtator-link.genefoundry.org/mcp",
        public_base_url="https://pubtator-link.genefoundry.org",
        mcp_service_token="router-secret",
        mcp_profile="full",
    )
    base.update(over)
    return Settings(_env_file=None, **base)

def test_oauth_build_returns_multiauth_with_service_verifier():
    auth = build_auth(_oauth_settings())
    assert isinstance(auth, MultiAuth)
    # JWT verifier is audience-bound to the resource URI
    jwt_v = next(v for v in auth.verifiers if isinstance(v, JWTVerifier))
    assert jwt_v.audience == "https://pubtator-link.genefoundry.org/mcp"
    # the router's static token is one of the verifiers
    assert any(isinstance(v, ServiceTokenVerifier) for v in auth.verifiers)

@pytest.mark.asyncio
async def test_oauth_multiauth_accepts_service_token_rejects_garbage():
    auth = build_auth(_oauth_settings())
    ok = await auth.verify_token("router-secret")
    assert ok is not None and "pubtator:write" in ok.scopes
    assert await auth.verify_token("not-a-token") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auth_build.py -v`
Expected: FAIL — `_build_oauth` raises `NotImplementedError`.

- [ ] **Step 3: Write minimal implementation**

Replace the `_build_oauth` stub in `pubtator_link/auth.py`. Mirrors the router's proven `_build_oauth`, including the `resource_base_url = root origin` fix (NOT the audience) to avoid the `/mcp/mcp` doubled-resource bug:

```python
def _build_oauth(settings: Settings) -> Any:
    settings.validate_oauth_config()
    from fastmcp.server.auth import MultiAuth, OAuthProxy
    from fastmcp.server.auth.providers.jwt import JWTVerifier

    verifier = JWTVerifier(
        jwks_uri=settings.jwt_jwks_url,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,   # reject tokens not minted for this resource
        base_url=settings.public_base_url,
    )
    oauth = OAuthProxy(
        upstream_authorization_endpoint=settings.oauth_authorize_url,
        upstream_token_endpoint=settings.oauth_token_url,
        upstream_client_id=settings.oauth_client_id,
        upstream_client_secret=settings.oauth_client_secret,
        token_verifier=verifier,
        base_url=settings.public_base_url,          # ROOT origin (/authorize, /token live here)
        resource_base_url=settings.public_base_url, # ROOT origin — NOT the audience (avoids /mcp/mcp)
        jwt_signing_key=settings.oauth_jwt_signing_key,
        require_authorization_consent="external",   # Keycloak owns login+consent
    )
    verifiers: list[Any] = [verifier]
    if settings.mcp_service_token:
        verifiers.append(
            ServiceTokenVerifier(
                settings.mcp_service_token,
                scopes=["pubtator:read", "pubtator:write"],
            )
        )
    return MultiAuth(server=oauth, verifiers=verifiers)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auth_build.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/auth.py tests/unit/test_auth_build.py
git commit -m "feat(auth): oauth-mode MultiAuth (OAuthProxy + JWT + service token)"
```

---

### Task 4: Wire auth into `server_manager` + gate legacy middleware

**Files:**
- Modify: `pubtator_link/server_manager.py` (attach `mcp.auth`; gate `MCPServiceAuthMiddleware` to none mode; call `validate_oauth_config`)
- Test: `tests/unit/test_server_auth_wiring.py` (new)

**Interfaces:**
- Consumes: `build_auth` (Task 2/3).
- Produces: in `create_app`, `mcp.auth = build_auth(settings)` set before `mcp.http_app(...)`; legacy `MCPServiceAuthMiddleware` installed **only** when `settings.auth_mode == "none"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_server_auth_wiring.py
from fastapi.testclient import TestClient
from pubtator_link.server_manager import UnifiedServerManager
from pubtator_link import server_manager as sm

def _app(monkeypatch, **settings_over):
    for k, v in settings_over.items():
        monkeypatch.setattr(sm.settings, k, v, raising=False)
    return UnifiedServerManager().create_app(include_mcp=True)

def test_none_mode_no_oauth_provider_but_legacy_token_gate(monkeypatch):
    app = _app(monkeypatch, auth_mode="none", mcp_service_token="tok", mcp_profile="readonly")
    client = TestClient(app)
    # legacy middleware still gates /mcp when a token is set in none mode
    assert client.post("/mcp").status_code == 401
    assert client.get("/health").status_code == 200

def test_oauth_mode_sets_provider_and_skips_legacy_gate(monkeypatch):
    monkeypatch.setattr(sm.settings, "auth_mode", "oauth", raising=False)
    for k, v in {
        "oauth_authorize_url": "https://kc.example.org/a",
        "oauth_token_url": "https://kc.example.org/t",
        "oauth_client_id": "pubtator-link",
        "oauth_client_secret": "secret",
        "jwt_issuer": "https://kc.example.org/realms/gf",
        "jwt_jwks_url": "https://kc.example.org/certs",
        "jwt_audience": "https://pubtator-link.genefoundry.org/mcp",
        "public_base_url": "https://pubtator-link.genefoundry.org",
        "mcp_service_token": "router-secret",
    }.items():
        monkeypatch.setattr(sm.settings, k, v, raising=False)
    mgr = UnifiedServerManager()
    app = mgr.create_app(include_mcp=True)
    assert mgr.mcp.auth is not None  # MultiAuth attached
    client = TestClient(app)
    # /health stays public even with auth enabled
    assert client.get("/health").status_code == 200
    # the router's service token is accepted by the MCP transport (no legacy double-gate)
    r = client.post(
        "/mcp",
        headers={"Authorization": "Bearer router-secret", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "t", "version": "0"}}},
    )
    assert r.status_code != 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_server_auth_wiring.py -v`
Expected: FAIL — `mgr.mcp.auth` is None (auth not wired); oauth request 401s from the legacy gate.

- [ ] **Step 3: Write minimal implementation**

In `pubtator_link/server_manager.py`, import `build_auth` at top:

```python
from pubtator_link.auth import build_auth
```

In `create_app`, after `mcp = create_pubtator_mcp()` and before `mcp.http_app(...)`:

```python
        if include_mcp:
            settings.validate_oauth_config()
            mcp = create_pubtator_mcp()
            mcp.auth = build_auth(settings)
            mcp_http_app = mcp.http_app(
                path=settings.mcp_path,
                json_response=True,
                stateless_http=True,
                host_origin_protection=True,
                allowed_hosts=settings.allowed_hosts,
                allowed_origins=settings.allowed_origins,
            )
            self.mcp = mcp
```

Gate the legacy middleware to none mode (replace the existing `if settings.mcp_service_token:` block):

```python
        if settings.auth_mode == "none" and settings.mcp_service_token:
            app.add_middleware(
                MCPServiceAuthMiddleware,
                token=settings.mcp_service_token,
                path=settings.mcp_path,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_server_auth_wiring.py -v`
Expected: PASS (2 tests). If the oauth `/mcp` probe returns 401, confirm the token reached `MultiAuth.verify_token` (RequireAuthMiddleware path), not the legacy gate.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/server_manager.py tests/unit/test_server_auth_wiring.py
git commit -m "feat(auth): attach MultiAuth in server_manager; legacy gate only in none mode"
```

---

### Task 5: Write authorization middleware (`require_write_scope`)

**Files:**
- Create: `pubtator_link/authorization.py`
- Modify: `pubtator_link/server_manager.py` (register middleware in oauth mode when `require_write_scope`)
- Test: `tests/unit/test_write_authorization.py` (new)

**Interfaces:**
- Produces: `WriteAuthorizationMiddleware(Middleware)` gating a frozenset of `full`-only write tools on the `pubtator:write` scope; `PUBTATOR_WRITE_TOOLS: frozenset[str]`.
- Consumes: `settings.require_write_scope`.

Write-tool names — confirm against `pubtator_link/mcp/catalog.py` `profiles=("full",)` entries before coding: `submit_text_annotation`, `add_evidence_certainty`, `stage_research_session`, `review_quickstart`, `export_review_audit_bundle` (plus any additional `("full",)`-only write tool present at implementation time).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_write_authorization.py
import pytest
from types import SimpleNamespace
from fastmcp.exceptions import ToolError
from pubtator_link.authorization import WriteAuthorizationMiddleware, PUBTATOR_WRITE_TOOLS

class _Ctx:
    def __init__(self, name): self.message = SimpleNamespace(name=name)

async def _call_next(ctx): return "ok"

@pytest.mark.asyncio
async def test_write_denied_without_scope(monkeypatch):
    import pubtator_link.authorization as az
    monkeypatch.setattr(az, "get_access_token", lambda: SimpleNamespace(scopes=["pubtator:read"]))
    mw = WriteAuthorizationMiddleware()
    tool = next(iter(PUBTATOR_WRITE_TOOLS))
    with pytest.raises(ToolError, match="pubtator:write"):
        await mw.on_call_tool(_Ctx(tool), _call_next)

@pytest.mark.asyncio
async def test_write_allowed_with_scope(monkeypatch):
    import pubtator_link.authorization as az
    monkeypatch.setattr(az, "get_access_token", lambda: SimpleNamespace(scopes=["pubtator:write"]))
    mw = WriteAuthorizationMiddleware()
    assert await mw.on_call_tool(_Ctx(next(iter(PUBTATOR_WRITE_TOOLS))), _call_next) == "ok"

@pytest.mark.asyncio
async def test_read_tool_never_gated(monkeypatch):
    import pubtator_link.authorization as az
    monkeypatch.setattr(az, "get_access_token", lambda: None)
    mw = WriteAuthorizationMiddleware()
    assert await mw.on_call_tool(_Ctx("search_literature"), _call_next) == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_write_authorization.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# pubtator_link/authorization.py
"""Caller authorization for PubTator write tools (opt-in via require_write_scope)."""
from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

PUBTATOR_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "submit_text_annotation",
        "add_evidence_certainty",
        "stage_research_session",
        "review_quickstart",
        "export_review_audit_bundle",
    }
)


class WriteAuthorizationMiddleware(Middleware):
    """Require the pubtator:write scope before a write tool runs."""

    async def on_call_tool(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        name = getattr(context.message, "name", "")
        if name in PUBTATOR_WRITE_TOOLS:
            token = get_access_token()
            scopes = set(token.scopes) if token is not None else set()
            if "pubtator:write" not in scopes:
                raise ToolError("This tool requires the pubtator:write scope")
        return await call_next(context)
```

Register in `server_manager.py` (FastMCP middleware, added to the `mcp` server, only when gating is on) right after `mcp.auth = build_auth(settings)`:

```python
            if settings.auth_mode == "oauth" and settings.require_write_scope:
                from pubtator_link.authorization import WriteAuthorizationMiddleware
                mcp.add_middleware(WriteAuthorizationMiddleware())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_write_authorization.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/authorization.py pubtator_link/server_manager.py tests/unit/test_write_authorization.py
git commit -m "feat(auth): opt-in write-scope authorization (default off = write-for-all-authenticated)"
```

---

### Task 6: Deployment config — ready-to-enable oauth+full block

**Files:**
- Modify: `docker/docker-compose.prod.yml` (commented oauth+full block + `FASTMCP_HOME` volume; keep default safe)
- Modify: `.env.example`, `.env.docker.example` (document the new vars, all commented)
- Test: manual `docker compose config` resolution (no unit test — compose YAML)

**Interfaces:** none (config only). Default deploy stays `AUTH_MODE` unset → `none`.

- [ ] **Step 1: Add the commented go-live block to `docker/docker-compose.prod.yml`**

Under the app service `environment:` (near `PUBTATOR_LINK_MCP_PROFILE`), add — commented so a deploy without Keycloak cannot crash:

```yaml
      # --- OAuth go-live (enable AFTER Keycloak is configured; see docs/SECURITY.md) ---
      # PUBTATOR_LINK_AUTH_MODE: oauth
      # PUBTATOR_LINK_MCP_PROFILE: full
      # PUBTATOR_LINK_OAUTH_AUTHORIZE_URL: "${PUBTATOR_LINK_OAUTH_AUTHORIZE_URL:?}"
      # PUBTATOR_LINK_OAUTH_TOKEN_URL: "${PUBTATOR_LINK_OAUTH_TOKEN_URL:?}"
      # PUBTATOR_LINK_OAUTH_CLIENT_ID: "${PUBTATOR_LINK_OAUTH_CLIENT_ID:?}"
      # PUBTATOR_LINK_OAUTH_CLIENT_SECRET: "${PUBTATOR_LINK_OAUTH_CLIENT_SECRET:?}"
      # PUBTATOR_LINK_OAUTH_JWT_SIGNING_KEY: "${PUBTATOR_LINK_OAUTH_JWT_SIGNING_KEY:?}"
      # PUBTATOR_LINK_JWT_ISSUER: "${PUBTATOR_LINK_JWT_ISSUER:?}"
      # PUBTATOR_LINK_JWT_JWKS_URL: "${PUBTATOR_LINK_JWT_JWKS_URL:?}"
      # PUBTATOR_LINK_JWT_AUDIENCE: "${PUBTATOR_LINK_JWT_AUDIENCE:?}"
      # PUBTATOR_LINK_PUBLIC_BASE_URL: "${PUBTATOR_LINK_PUBLIC_BASE_URL:?}"
      # PUBTATOR_LINK_REQUIRE_WRITE_SCOPE: "false"
```

Add a persistent FastMCP home volume (OAuthProxy client store) to the app service and the `volumes:` block:

```yaml
    volumes:
      - fastmcp_home:/home/appuser/.fastmcp
    environment:
      FASTMCP_HOME: /home/appuser/.fastmcp
```
```yaml
volumes:
  fastmcp_home:
    name: pubtator-link_fastmcp_home
```
(Merge these into the existing service/volumes stanzas rather than duplicating keys; confirm the container user's home path against the Dockerfile.)

- [ ] **Step 2: Document vars in `.env.example` and `.env.docker.example`** (all commented, mirroring §5 of the spec).

- [ ] **Step 3: Verify compose resolves with the safe default (no oauth vars set)**

Run:
```bash
PUBTATOR_LINK_POSTGRES_PASSWORD=dummy \
PUBTATOR_LINK_IMAGE='ghcr.io/berntpopp/pubtator-link@sha256:0000000000000000000000000000000000000000000000000000000000000000' \
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config >/dev/null && echo OK
```
Expected: `OK` (no auth vars required by default).

- [ ] **Step 4: Commit**

```bash
git add docker/docker-compose.prod.yml .env.example .env.docker.example
git commit -m "chore(deploy): ready-to-enable oauth+full block + FASTMCP_HOME volume (default stays none)"
```

---

### Task 7: Docs — SECURITY.md + configuration/deployment

**Files:**
- Modify: `docs/SECURITY.md` (replace the "must never be published directly" stance with the OAuth+service-token model and the go-live runbook)
- Modify: `docs/configuration.md`, `docs/deployment.md` (new env vars + go-live steps)

(None of these are WIP files. `docs/mcp-tool-catalog.md` IS WIP — do not touch it.)

- [ ] **Step 1: Rewrite the `docs/SECURITY.md` auth section** to describe: AUTH_MODE none/oauth; MultiAuth (Keycloak JWT or router service token); write-for-all-authenticated default with `require_write_scope` to tighten; per-resource audience binding; the Keycloak operator runbook (spec §9). State plainly that the public `/mcp` in oauth mode is directly usable by standalone OAuth clients AND the router.

- [ ] **Step 2: Add the env-var table and go-live flip to `docs/configuration.md` / `docs/deployment.md`.**

- [ ] **Step 3: Commit**

```bash
git add docs/SECURITY.md docs/configuration.md docs/deployment.md
git commit -m "docs(security): document MultiAuth model + Keycloak go-live runbook"
```

---

### Task 8: Full-suite gate

**Files:** none (verification only).

- [ ] **Step 1: Run the repo gate**

Run: `make ci-local`
Expected: PASS — format-check, lint, **lint-loc** (auth.py/authorization.py under 600 LOC), mypy, unit + integration tests. Fix any failure at its root cause; re-run until green. Do **not** stage any WIP file to make CI pass.

- [ ] **Step 2: Manual none-mode back-compat smoke** (open readonly still works)

```bash
uv run pytest tests/unit/test_auth_config.py tests/unit/test_auth_build.py \
  tests/unit/test_server_auth_wiring.py tests/unit/test_write_authorization.py -v
```
Expected: all PASS.

- [ ] **Step 3: Confirm no WIP files were staged across the whole feature**

```bash
git log --oneline origin/main..HEAD  # or ccf4b29..HEAD — feature + spec commits only
git show --stat HEAD~6..HEAD | grep -E "facade.py|pyproject.toml|uv.lock|CHANGELOG.md|mcp-tool-catalog" && echo "WIP LEAK — FIX" || echo "clean: no WIP files in feature commits"
```
Expected: `clean: no WIP files in feature commits`.

---

## Self-Review

**Spec coverage:** §4.1 auth.py → Tasks 2–3; §4.2 wiring → Task 4; §4.3 write authz → Task 5; §4.4 profile → env only (Task 6); §5 config → Task 1; §6 flows → Tasks 3–5 tests; §7 invariants → constant-time service verifier (T2), audience binding (T3), `/mcp/mcp` avoidance (T3), legacy-gate skip (T4); §8 safe release → default none (T1) + compose default (T6); §9 runbook → Task 7; §10 commit discipline → Global Constraints + Task 8 step 3; §11 tests → Tasks 1–5, 8; §12 release → deferred (out of plan).

**Placeholder scan:** No TBD/TODO; every code step has real code. Write-tool names flagged for confirmation against `catalog.py` at implementation time (Task 5).

**Type consistency:** `build_auth(settings) -> AuthProvider|None` (T2) reused in T4; `ServiceTokenVerifier(token, *, client_id, scopes)` (T2) reused in T3; `PUBTATOR_WRITE_TOOLS` / `WriteAuthorizationMiddleware` (T5) used in T5 server wiring. `settings.auth_mode`/`require_write_scope`/oauth fields (T1) used in T3/T4/T5.

**Open verification points (call out during execution, not assumptions):**
- PRM well-known path served by `http_app()` at the expected URL when `mcp_http_app` is mounted at `/` — assert in an oauth-mode test or manual curl.
- `mcp.add_middleware` is the correct FastMCP 3.4.2 API for server middleware (vs `add_middleware` on the ASGI app) — verify against installed package in Task 5.
- `AccessToken` constructor kwargs (`token`, `client_id`, `scopes`, `expires_at`) match fastmcp 3.4.2 — verify in Task 2.

---

## Revision 2 — corrected task deltas (post-Codex, verified against fastmcp 3.4.4)

See spec Revision 2 for rationale. Apply these over the tasks above:

- **All tasks:** `from pubtator_link.config import Settings` → `ServerSettings`; config tests
  construct `ServerSettings(...)`, wiring tests monkeypatch the global `settings`.
- **Task 1 (`validate_oauth_config`):** also require `oauth_jwt_signing_key` and
  `mcp_service_token`; assert `public_base_url` is an HTTPS origin with **no path/query**
  and `jwt_audience == public_base_url.rstrip('/') + mcp_path` (kills `/mcp/mcp`).
- **Task 3 (`_build_oauth`):** add `allowed_client_redirect_uris=<claude.ai + loopback
  patterns from settings>`, `valid_scopes=["pubtator:read","pubtator:write"]`,
  `redirect_path="/auth/callback"` (default). `http_app` kwargs
  (`host_origin_protection`/`allowed_hosts`/`allowed_origins`) are valid in 3.4.4 — keep.
- **Task 5 (authz):** `from pubtator_link.mcp.profiles import WRITE_TOOLS` — the
  authoritative **8-tool** set; do NOT hand-list. Test **every** tool in `WRITE_TOOLS`,
  not `next(iter(...))`.
- **NEW Task 5b (REST surface):** in `server_manager.create_app`, when
  `settings.auth_mode == "oauth"`, do **not** register the mutating REST review routes
  (`reviews_router` write/DELETE). Test: anonymous `POST`/`DELETE` to those paths returns
  404/401 in oauth mode (route absent), still present in none mode.
- **Task 6 (compose/Docker):** `FASTMCP_HOME=/home/app/.fastmcp`; add
  `RUN mkdir -p /home/app/.fastmcp && chown app:app /home/app/.fastmcp` to the Dockerfile;
  make `PUBTATOR_LINK_ALLOWED_HOSTS` configurable and include the public host in the
  go-live block.
- **Tasks 3/4/11 tests:** use a real `FastMCP` app inside `with TestClient(app)`; assert
  HTTP 200 + a valid `initialize` JSON-RPC result, anonymous → 401, GET
  `/.well-known/oauth-protected-resource/mcp` returns PRM whose resource == audience, and
  crypto JWT valid / bad-signature / wrong-audience cases (sign test JWTs with a local
  key + a matching JWKS via `JWTVerifier(public_key=...)` or a stub jwks).
- **Task 8 WIP-leak check:** diff **all** changed paths since the feature base against an
  exact allowlist of this feature's files; fail on any unmatched path (not a 6-commit grep).
- **Docs (Task 7):** Keycloak runbook registers `PUBLIC_BASE_URL/auth/callback` (not the
  claude.ai redirect) and documents a Keycloak mapper emitting `pubtator:read`/`write` into
  the `scope`/`scp` claim (JWTVerifier does not read `realm_access.roles`). Add the
  accepted cross-user-write risk + per-subject-ownership follow-up.
