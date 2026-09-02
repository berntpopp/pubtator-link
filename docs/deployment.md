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

## Fleet deploy contract (strato_v6_docker_npm)

`docker/docker-compose.npm.yml` is the overlay the fleet controller repo
(`strato_v6_docker_npm`) actually deploys and validates, as the third file of
the `docker-compose.yml` + `docker-compose.prod.yml` + `docker-compose.npm.yml`
stack it renders for this repo — it pulls the released, attested
`ghcr.io/berntpopp/pubtator-link` image at a pinned digest and never builds
from source. Every service in that overlay declares a numeric
`user: "<uid>:<gid>"`: `999:999` for `pubtator-link` (this image's own
uid:gid from `docker/Dockerfile`) and `999:999` for `pubtator-postgres` (the
`pgvector/pgvector` image's own uid:gid), because the controller's runtime
observer proves the effective uid from `/proc`. Unlike most sibling repos,
the release Compose files named in `container-release.json`
(`docker/docker-compose.yml`, `docker/docker-compose.prod.yml`) are allowed to
declare `user` — the contract already pins `pubtator-postgres` to
`user: "999:999"` there (see `service.auxiliary`) — so the shared release
gate only requires any declared `user` to stay numeric non-root and match the
rendered service exactly, not that it's absent. `tests/unit/test_deploy_overlay_user.py`
guards both rules.

`container-release.json` also declares `service.deployed_compose_files` (the same
three-file set above, in order) and `service.deployed_sidecars` (`pubtator-postgres`'s
exact pinned `pgvector/pgvector` image; there is no read-only seed bind, so
`deployed_seed_binds` stays unset). The shared `_container-release.yml` release
workflow's `validate-deployed-overlay` step, pinned in both
`.github/workflows/container-release.yml` and `.github/workflows/container-ci.yml`,
reads that declaration to check the stack actually deployed rather than the npm
overlay alone. Guarded by
`test_container_release_manifest_declares_the_deployed_overlay` in
`tests/unit/test_container_release_contract.py`.

Release checklist enforced by this repo: bump `pyproject.toml`, run `uv lock`,
add a `CHANGELOG.md` heading `## [x.y.z] - YYYY-MM-DD`, bump `CITATION.cff`
`version:` (generated file; `date-released` is regenerated externally by
`genefoundry-router`'s `make citation-write`, not by this repo's release),
tag `vx.y.z`, then approve the `release` GitHub Environment gate (it can
require approval twice).

Self-check that the overlay still projects cleanly for the fleet controller:

```bash
export PUBTATOR_LINK_IMAGE="ghcr.io/berntpopp/pubtator-link@sha256:<64 hex>"
export PUBTATOR_LINK_POSTGRES_PASSWORD="<any value>"
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml \
  -f docker/docker-compose.npm.yml config --format json > /tmp/r.json
# from strato_v6_docker_npm:
uv run python -c "import sys,json; sys.path.insert(0,'scripts'); from utils.deployment_preflight import canonical_projection; canonical_projection(json.load(open('/tmp/r.json')), project='pubtator-link'); print('PROJECTION OK')"
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
