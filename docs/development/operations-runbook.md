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

## Review Auditability And Upstream Resilience

PubTator-Link retries idempotent upstream GET calls on transient statuses
`408`, `429`, `500`, `502`, `503`, and `504`. The retry helper respects
`Retry-After` when present and otherwise uses capped full-jitter backoff. Text
annotation POST submission remains single-attempt by default because the upstream
service may already have accepted the job.

Review batch retrieval and source preflight use conservative bounded concurrency
defaults: `PUBTATOR_LINK_REVIEW_RETRIEVAL_CONCURRENCY=4` and
`PUBTATOR_LINK_REVIEW_PREFLIGHT_CONCURRENCY=3`. Raise these only after checking
upstream behavior and local database capacity.

For source coverage failures, inspect `coverage_reason` and
`resolver_attempts` on `inspect_review_index` or
`export_review_audit_bundle`. Common reasons include `no_pmcid`,
`abstract_fallback_used`, `upstream_timeout`, `upstream_404`, and
`retry_exhausted`. Treat abstract-only and title-only coverage as scientific
limitations in downstream review notes.

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
