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
