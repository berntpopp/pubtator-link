from __future__ import annotations

import secrets

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class MCPServiceAuthMiddleware:
    """Require the router-owned bearer credential on the MCP transport only."""

    def __init__(self, app: ASGIApp, *, token: str, path: str = "/mcp") -> None:
        self.app = app
        self.token = token
        self.path = path.rstrip("/") or "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request_path = scope.get("path", "").rstrip("/") or "/"
        if scope["type"] != "http" or request_path != self.path:
            await self.app(scope, receive, send)
            return

        authorization = Headers(scope=scope).get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        valid = (
            separator == " "
            and scheme.lower() == "bearer"
            and secrets.compare_digest(credential, self.token)
        )
        if not valid:
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
