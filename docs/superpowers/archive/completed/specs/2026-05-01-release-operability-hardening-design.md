# Release And Operability Hardening Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-01

## Goal

Add incremental release and operability hardening so Docker artifacts can be
validated more consistently and runtime health is easier to diagnose.

## Problem

The project has CI, Docker validation, CodeQL, dependency review, structured
logging, and `/health`. It does not yet have:

- Docker image vulnerability scanning.
- SBOM generation.
- a tagged release workflow.
- readiness semantics that distinguish process health from dependency
  readiness.
- request/correlation IDs.
- minimal runbook documentation for deploy, rollback, and incident checks.

This workstream is broader than the others and should be implemented in
separable tasks.

## Non-Goals

- Do not publish images to a registry unless credentials and target registry
  are explicitly provided during execution.
- Do not require paid external services.
- Do not introduce a full tracing stack.
- Do not change public REST or MCP response schemas except adding a new
  readiness endpoint.
- Do not make local development require Docker scanning tools outside CI unless
  the tool is available.

## Proposed Design

Split hardening into four independent pieces.

### 1. Image Scan And SBOM Workflow

Add or extend a GitHub Actions workflow that:

- builds the Docker image.
- runs vulnerability scanning with a common action such as Trivy.
- generates an SBOM artifact.
- uploads scan/SBOM outputs as workflow artifacts.

Keep workflow permissions least-privilege. Use pull request and `main` push
events. Do not fail on vulnerability severity policy until the team chooses a
policy; start by producing artifacts and failing only on scanner execution
errors.

### 2. Tagged Release Workflow

Add a release workflow triggered by version tags such as `v*`.

Initial release workflow should:

- run `make ci-local`.
- run Docker build.
- render Compose configs.
- produce a Docker image artifact or documented build output.

Publishing to GHCR or another registry should be a later optional task unless
credentials and naming are confirmed.

### 3. Readiness Endpoint

Add a readiness endpoint that checks dependency readiness separately from
process health:

- `/health` remains lightweight process health.
- `/ready` checks app-scoped resources and database connectivity when the review
  database URL is configured.

The response should be simple JSON with status and dependency fields. It should
return a non-2xx status when a configured dependency is unavailable.

### 4. Request IDs And Runbook

Add request ID middleware:

- read incoming `X-Request-ID` if present.
- generate a UUID when missing.
- attach the ID to response headers.
- make it available to structured logs where practical.

Add `docs/development/operations-runbook.md` covering:

- local Docker restart and health checks.
- readiness checks.
- log inspection.
- rollback guidance for Docker Compose deployments.
- what CI/release artifacts to inspect.

## Testing

Workflow/documentation tests:

```bash
uv run pytest tests/unit/test_development_tooling.py tests/unit/docker -q
```

Runtime tests:

```bash
uv run pytest tests/test_routes/test_health.py tests/unit/test_server_manager.py -q
```

Completion gate:

```bash
make ci-local
make test-cov
```

## Rollout

1. Add workflow hardening for scan/SBOM artifact generation.
2. Add tagged release workflow without registry publishing.
3. Add `/ready` endpoint and tests.
4. Add request ID middleware and tests.
5. Add operations runbook.

Each step should be independently committable.

## Risks And Mitigations

Risk: scanner actions introduce flaky CI or unexpected policy failures.

Mitigation: start with artifact generation and scanner execution success, not a
strict vulnerability severity gate.

Risk: readiness checks break local development when PostgreSQL is intentionally
unset.

Mitigation: only check database connectivity when the review database URL is
configured; otherwise report that database readiness is not configured.

Risk: request IDs complicate logging configuration.

Mitigation: first guarantee response headers and request state; structured log
enrichment can remain minimal.
