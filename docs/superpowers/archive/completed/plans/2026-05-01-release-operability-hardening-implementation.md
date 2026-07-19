# Release And Operability Hardening Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add incremental release and operability hardening: scan/SBOM workflow, release workflow, readiness endpoint, request IDs, and an operations runbook.

**Architecture:** Keep `/health` as process health and add `/ready` for dependency readiness. Add workflow artifacts without registry publishing. Add request ID middleware in `UnifiedServerManager.create_app()` and document operations in `docs/development/operations-runbook.md`.

**Tech Stack:** Python 3.11, FastAPI, GitHub Actions, Docker, pytest, Make.

---

## File Structure

- Create `.github/workflows/release.yml`: tag-triggered release validation.
- Modify `.github/workflows/docker.yml` or create `.github/workflows/container-security.yml`: image scan and SBOM artifacts.
- Modify `pubtator_link/server_manager.py`: `/ready` endpoint and request ID middleware.
- Modify `tests/test_routes/test_health.py`: readiness and request ID tests.
- Modify `tests/unit/test_development_tooling.py`: workflow/runbook guardrails.
- Create `docs/development/operations-runbook.md`: deploy, health, readiness, logs, rollback.

## Task 1: Add Container Scan And SBOM Workflow

**Files:**
- Create: `.github/workflows/container-security.yml`
- Modify: `tests/unit/test_development_tooling.py`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write failing workflow guardrail test**

Add this test to `tests/unit/test_development_tooling.py`:

```python
def test_container_security_workflow_generates_scan_and_sbom_artifacts() -> None:
    workflow = _workflow(".github/workflows/container-security.yml")
    job = workflow["jobs"]["container-security"]
    uses_steps = {step.get("uses") for step in job["steps"]}
    run_steps = "\n".join(str(step.get("run", "")) for step in job["steps"])

    assert workflow["permissions"] == {"contents": "read"}
    assert job["name"] == "Container scan and SBOM"
    assert "aquasecurity/trivy-action" in "\n".join(str(step) for step in job["steps"])
    assert "docker build -f docker/Dockerfile -t pubtator-link:scan ." in run_steps
    assert "actions/upload-artifact@v4" in uses_steps
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_container_security_workflow_generates_scan_and_sbom_artifacts -q
```

Expected: fail because `.github/workflows/container-security.yml` does not exist.

- [ ] **Step 3: Add workflow**

Create `.github/workflows/container-security.yml`:

```yaml
name: Container Security

on:
  pull_request:
  push:
    branches:
      - main
  schedule:
    - cron: "43 4 * * 1"

permissions:
  contents: read

jobs:
  container-security:
    name: Container scan and SBOM
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Build Docker image
        run: docker build -f docker/Dockerfile -t pubtator-link:scan .

      - name: Run Trivy vulnerability scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: pubtator-link:scan
          format: table
          output: trivy-report.txt
          exit-code: "0"

      - name: Generate SBOM
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: pubtator-link:scan
          format: cyclonedx
          output: pubtator-link-sbom.cdx.json
          exit-code: "0"

      - name: Upload scan artifacts
        uses: actions/upload-artifact@v4
        with:
          name: container-security-artifacts
          path: |
            trivy-report.txt
            pubtator-link-sbom.cdx.json
```

- [ ] **Step 4: Run focused test**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_container_security_workflow_generates_scan_and_sbom_artifacts -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/container-security.yml tests/unit/test_development_tooling.py
git commit -m "ci: add container scan and sbom workflow"
```

## Task 2: Add Tagged Release Validation Workflow

**Files:**
- Create: `.github/workflows/release.yml`
- Modify: `tests/unit/test_development_tooling.py`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write failing release workflow test**

Add:

```python
def test_release_workflow_validates_tagged_builds_without_publishing() -> None:
    workflow = _workflow(".github/workflows/release.yml")
    release_job = workflow["jobs"]["release-validation"]
    commands = {step.get("run") for step in release_job["steps"]}

    assert workflow["permissions"] == {"contents": "read"}
    assert release_job["name"] == "Release validation"
    assert "make ci-local" in commands
    assert "make docker-prod-config" in commands
    assert "make docker-npm-config" in commands
    assert "docker build -f docker/Dockerfile -t pubtator-link:release ." in commands
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_release_workflow_validates_tagged_builds_without_publishing -q
```

Expected: fail because `.github/workflows/release.yml` does not exist.

- [ ] **Step 3: Add release workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - "v*"

permissions:
  contents: read

jobs:
  release-validation:
    name: Release validation
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Set up uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Install dependencies
        run: uv sync --group dev --frozen

      - name: Run local CI checks
        run: make ci-local

      - name: Validate production Compose config
        run: make docker-prod-config

      - name: Validate NPM Compose config
        run: make docker-npm-config

      - name: Build release Docker image
        run: docker build -f docker/Dockerfile -t pubtator-link:release .
```

- [ ] **Step 4: Run focused test**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_release_workflow_validates_tagged_builds_without_publishing -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/release.yml tests/unit/test_development_tooling.py
git commit -m "ci: add tagged release validation workflow"
```

## Task 3: Add Readiness Endpoint

**Files:**
- Modify: `pubtator_link/server_manager.py`
- Modify: `tests/test_routes/test_health.py`
- Test: `tests/test_routes/test_health.py`

- [ ] **Step 1: Write readiness tests**

Add to `tests/test_routes/test_health.py`:

```python
    def test_readiness_endpoint_without_database_config(self, test_client):
        response = test_client.get("/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["version"] == "1.0.0"
        assert data["dependencies"]["database"]["status"] == "not_configured"

    def test_readiness_endpoint_content_type(self, test_client):
        response = test_client.get("/ready")

        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/test_routes/test_health.py::TestHealthAndRoot::test_readiness_endpoint_without_database_config -q
```

Expected: fail with 404.

- [ ] **Step 3: Add `/ready` endpoint**

In `pubtator_link/server_manager.py`, import:

```python
from .config import review_rerag_config, settings
```

Replace the existing settings import line. Add this route after `/health`:

```python
        @app.get("/ready")
        async def ready(request: Request) -> dict[str, object]:
            """Readiness check endpoint."""
            resources = getattr(request.app.state, "pubtator_resources", None)
            database_status = "not_configured"
            if review_rerag_config.database_url is not None:
                database_status = "ready"
                if resources is None or resources.review_pool is None:
                    database_status = "unavailable"

            status = "ready" if database_status != "unavailable" else "not_ready"
            return {
                "status": status,
                "version": "1.0.0",
                "transport": settings.transport,
                "dependencies": {
                    "database": {
                        "status": database_status,
                    }
                },
            }
```

If a non-2xx response is required for unavailable configured database, implement with `JSONResponse(status_code=503, content=...)` and add a focused test using monkeypatching.

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/test_routes/test_health.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/server_manager.py tests/test_routes/test_health.py
git commit -m "feat: add readiness endpoint"
```

## Task 4: Add Request ID Middleware

**Files:**
- Modify: `pubtator_link/server_manager.py`
- Modify: `tests/test_routes/test_health.py`
- Test: `tests/test_routes/test_health.py`

- [ ] **Step 1: Write request ID tests**

Add:

```python
    def test_request_id_header_is_preserved(self, test_client):
        response = test_client.get("/health", headers={"X-Request-ID": "req-123"})

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "req-123"

    def test_request_id_header_is_generated_when_missing(self, test_client):
        response = test_client.get("/health")

        assert response.status_code == 200
        assert response.headers["X-Request-ID"]
```

- [ ] **Step 2: Run tests to verify failure**

```bash
uv run pytest tests/test_routes/test_health.py::TestHealthAndRoot::test_request_id_header_is_preserved -q
```

Expected: fail because response lacks `X-Request-ID`.

- [ ] **Step 3: Add middleware**

In `pubtator_link/server_manager.py`, import:

```python
from uuid import uuid4
```

Add this middleware before `bind_pubtator_resources`:

```python
        @app.middleware("http")
        async def add_request_id(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            request_id = request.headers.get("X-Request-ID") or str(uuid4())
            request.state.request_id = request_id
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
```

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/test_routes/test_health.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/server_manager.py tests/test_routes/test_health.py
git commit -m "feat: add request id middleware"
```

## Task 5: Add Operations Runbook

**Files:**
- Create: `docs/development/operations-runbook.md`
- Modify: `tests/unit/test_development_tooling.py`
- Test: `tests/unit/test_development_tooling.py`

- [ ] **Step 1: Write failing runbook guardrail test**

Add:

```python
def test_operations_runbook_documents_deploy_health_and_rollback() -> None:
    runbook = Path("docs/development/operations-runbook.md").read_text()

    assert "make docker-up" in runbook
    assert "/health" in runbook
    assert "/ready" in runbook
    assert "docker compose" in runbook
    assert "rollback" in runbook.lower()
    assert "X-Request-ID" in runbook
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_operations_runbook_documents_deploy_health_and_rollback -q
```

Expected: fail because runbook does not exist.

- [ ] **Step 3: Add runbook**

Create `docs/development/operations-runbook.md`:

````markdown
# Operations Runbook

## Local Docker Restart

Use the Makefile targets from the repository root:

```bash
make docker-down
make docker-build
make docker-up
docker compose -f docker/docker-compose.yml ps
```

The default development app listens on `${PUBTATOR_LINK_PORT:-8000}` and the
PostgreSQL container listens on `${PUBTATOR_LINK_POSTGRES_PORT:-5434}` unless
overridden by `.env`.

## Health And Readiness

Process health:

```bash
curl -f http://localhost:${PUBTATOR_LINK_PORT:-8000}/health
```

Dependency readiness:

```bash
curl -f http://localhost:${PUBTATOR_LINK_PORT:-8000}/ready
```

`/health` checks that the process is serving HTTP. `/ready` reports dependency
readiness, including database state when review re-RAG database configuration is
enabled.

## Request IDs

Clients may send `X-Request-ID`. The server returns `X-Request-ID` on responses.
Use this value when correlating logs and user reports.

## Logs

```bash
docker compose -f docker/docker-compose.yml logs -f pubtator-link
docker compose -f docker/docker-compose.yml logs -f pubtator-postgres
```

## Rollback

For Docker Compose deployments, roll back by checking out the previous known
good commit or image tag, then rebuild and restart:

```bash
git checkout HEAD~1
make docker-down
make docker-build
make docker-up
```

Inspect `/health`, `/ready`, and container logs before returning traffic.
````

- [ ] **Step 4: Run focused tests**

```bash
uv run pytest tests/unit/test_development_tooling.py::test_operations_runbook_documents_deploy_health_and_rollback -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add docs/development/operations-runbook.md tests/unit/test_development_tooling.py
git commit -m "docs: add operations runbook"
```

## Task 6: Final Verification

**Files:**
- Check: `.github/workflows/container-security.yml`
- Check: `.github/workflows/release.yml`
- Check: `pubtator_link/server_manager.py`
- Check: `tests/test_routes/test_health.py`
- Check: `tests/unit/test_development_tooling.py`
- Check: `docs/development/operations-runbook.md`

- [ ] **Step 1: Run focused tests**

```bash
uv run pytest tests/unit/test_development_tooling.py tests/test_routes/test_health.py tests/unit/test_server_manager.py tests/unit/docker -q
```

Expected: pass.

- [ ] **Step 2: Run full gates**

```bash
make ci-local
make test-cov
```

Expected: both exit 0 and coverage remains at or above 80%.

- [ ] **Step 3: Check for final cleanup changes**

```bash
git add .github/workflows pubtator_link/server_manager.py tests docs/development
git commit -m "feat: finalize release and operability hardening"
```

Run:

```bash
git status --short
```

If any listed release/operability files changed during final verification, commit them. If `git status --short` is empty, do not create an empty commit for this task.

## Plan Self-Review Checklist

- Spec coverage: scan/SBOM, release validation, readiness, request IDs, and runbook are covered.
- Placeholder scan: no placeholders.
- Type consistency: endpoints use existing `UnifiedServerManager.create_app()` and tests use existing `TestClient` fixture.
