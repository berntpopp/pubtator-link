# Modern MCP Docker NPM Verification

Date: 2026-04-29

## Commands

- `uv run pytest tests/unit/mcp tests/integration/test_mcp_http_protocol.py tests/unit/docker -q`
  - Passed: 23 passed, 1 warning.
- `uv run ruff check .`
  - Passed after final lint fixes.
- `uv run mypy pubtator_link`
  - Passed after adding explicit casts for FastMCP inspection and PubTator adapter response shapes.
- `uv run pytest -q`
  - Passed: 188 passed, 3 warnings.
- `docker build -f docker/Dockerfile -t pubtator-link:modern .`
  - Passed.
- `docker compose -f docker/docker-compose.yml config`
  - Passed.
- `docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config`
  - Passed.
- `docker compose --env-file docker/.env.npm.example -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml config`
  - Passed.
- Local health and MCP initialize curl smoke.
  - `curl -fsS http://127.0.0.1:8000/health` returned healthy JSON.
  - MCP initialize at `http://127.0.0.1:8000/mcp` returned HTTP 200 and JSON-RPC capabilities.
  - `docker compose -f docker/docker-compose.yml down` completed after the smoke.

## Outcomes

- Final verification passed.
- Follow-up fixes made during verification:
  - Set `VIRTUAL_ENV=/opt/venv` in the Docker builder so `uv sync --active` installs runtime dependencies into the copied virtualenv.
  - Mounted the FastMCP app so POST `/mcp` returns HTTP 200 directly instead of redirecting to `/mcp/`.
  - Added type casts for adapter response shape handling and the FastMCP inspection shim.
  - Fixed Ruff import ordering, Docker test temp-path lint annotations, and a mutable fake class attribute in tests.
