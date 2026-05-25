# 2026-05-26 - pubtator_link.server_manager:app removed

**Impact:** Operators running PubTator-Link via Gunicorn or Uvicorn must
update their entrypoint.

## Why

Importing `pubtator_link.server_manager` previously built the full FastAPI
app at module load time, including conditionally registering FastMCP. This
could open upstream connections during any import (tests, reloaders, MCP STDIO
bootstrap) and was flagged as a hosted-MCP ship blocker in the 2026-05-25
senior engineer audit (item 1.1). The module-level
`pubtator_link.server_manager:app` entrypoint is gone.

## Migration

Replace `pubtator_link.server_manager:app` with the factory entrypoint in your
process manager command.

Gunicorn requires `gunicorn >= 22`:

```bash
gunicorn -c gunicorn_conf.py --factory pubtator_link.server_manager:create_app
```

Uvicorn:

```bash
uvicorn pubtator_link.server_manager:create_app --factory --host 0.0.0.0 --port 8000
```

## Verification

```bash
python -c "import pubtator_link.server_manager"
```

The command must complete without opening network or database connections.

## Environment Ordering Caveat

`create_app()` reads `settings.transport` at call time to decide whether to
mount the FastMCP routes. Set `PUBTATOR_LINK_TRANSPORT` and any other worker
environment before the worker forks.

With `gunicorn --preload`, the factory is invoked in the master process, so
post-fork environment changes will not be observed. Without `--preload`, each
worker calls the factory independently and observes environment set in the
worker entrypoint script.
