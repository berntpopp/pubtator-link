# Deployment

The operator's entry point. Detailed Compose material lives in
[`docker/README.md`](../docker/README.md); the trust boundary and token handling live in
[Security](SECURITY.md); the on-call procedures live in the
[operations runbook](development/operations-runbook.md).

## Docker

```bash
make docker-build          # build the image
make docker-up             # start the development stack (app + Postgres)
make docker-logs           # follow logs
make docker-down           # stop
```

Production and reverse-proxy overlays are rendered — and structurally validated — with:

```bash
make docker-prod-config    # docker-compose.yml + docker-compose.prod.yml
make docker-npm-config     # + docker-compose.npm.yml (Nginx Proxy Manager)
```

Production requires `PUBTATOR_LINK_IMAGE` pinned to a `ghcr.io/berntpopp/pubtator-link@sha256:<digest>`
and supplies `PUBTATOR_LINK_POSTGRES_PASSWORD` and `PUBTATOR_LINK_MCP_SERVICE_TOKEN` from a
secret store — the prod overlay fails closed rather than falling back to a default.

## The pgvector sidecar

The review re-RAG subsystem **requires PostgreSQL with pgvector**. The production overlay
runs a digest-pinned `pgvector/pgvector` service (`pubtator-postgres`) as the image's own
non-root `postgres` uid:gid, with the data volume persisted across releases.

Postgres consumes `POSTGRES_PASSWORD` only at initdb on an **empty** data volume: rotating
the password later does not change the role's password, so rotation means either an `ALTER
ROLE` against the running database or a restore of the volume from backup, followed by
recreating the app service. The base Compose stack initializes the schema from
`pubtator_link/db/review_schema.sql` the first time the volume is created; apply migrations
to an existing database with:

```bash
make db-migrate            # idempotent; PUBTATOR_LINK_DATABASE_URL must be set
```

## Exposure

The backend must be reachable **only** through the router or reverse proxy — never
published directly to a LAN or the internet. Production requires a router-owned service
bearer token on `/mcp`; a direct unauthenticated `/mcp` request must return `401`, while
`/health` stays open for container probes.

## Health monitoring

```bash
curl http://localhost:8000/health

# Cache statistics, only when the opt-in endpoints are enabled
PUBTATOR_LINK_ENABLE_CACHE_ENDPOINTS=true make dev
curl http://localhost:8000/api/cache/stats
```

## Observability

- **Structured logging** — JSON in production (`LOG_FORMAT=json`), console in development.
- **Request correlation** — responses carry `X-Request-ID`; see the operations runbook.
- **Performance metrics** — request timing and cache statistics.
- **Error tracking** — errors are logged with context, with upstream detail masked at the
  MCP boundary.
- **Rate limiting** — outbound politeness toward PubTator3, plus an optional inbound
  limiter (`PUBTATOR_LINK_ENABLE_INBOUND_RATE_LIMIT`).
