# PubTator-Link — Observability Implementation Guide

**Audience:** PubTator-Link maintainers, planning a production-grade observability rollout.
**Date:** 2026-05-02
**Companion to:** `docs/2026-05-02-pubtator-link-mcp-llm-engineering-review.md` (§4.16 scored observability at 5.5/10).
**Goal:** make the server self-explanatory in production — when a tool call is slow, fails, or misbehaves, you should be able to answer *what / when / why* in under 60 seconds without re-running the request.

---

## 0. Implementation status (2026-05-02)

The foundation pieces from PR-1 through PR-3 and the review RAG reliability/LLM ergonomics follow-up have been implemented in the current source tree:

| Area | Status | Notes |
|---|---|---|
| Correlation IDs | Shipped | `asgi-correlation-id` is installed with pure ASGI middleware through `app.add_middleware`; `X-Request-ID` is preserved/generated on HTTP responses. |
| Resource context middleware | Shipped | `PubTatorResourcesMiddleware` replaces the previous `@app.middleware("http")` resource binder to avoid the contextvars propagation trap. |
| MCP tool lifecycle logs | Shipped | The existing central `run_mcp_tool` wrapper emits `mcp_tool_started`, `mcp_tool_completed`, and `mcp_tool_failed`; no per-tool decorator is required. |
| Prometheus metrics | Shipped | `/metrics` exports `mcp_tool_calls_total` and `mcp_tool_latency_seconds`. |
| MCP error diagnostics | Shipped | MCP error envelopes can include bounded `diagnostics_snapshot`, `degraded_mode`, and `fallback_preview` fields. |
| Degraded review notices | Shipped | Review indexing/retrieval MCP tools emit `ctx.warning()` when returned results carry a degraded mode. |
| Resolver audit trace controls | Shipped | Review retrieval tools hide resolver attempts by default and expose `include_resolver_trace` for audit/debug workflows. |
| Batch response schema | Shipped | Compact/diagnostics batch retrieval can omit empty `results`, and the advertised output schema permits that lean response. |
| Prepare-mode compatibility | Shipped | `index_review_evidence` no longer advertises `prepare_mode`, but accepts cached legacy `prepare_mode="selected"` calls. |
| OpenTelemetry traces | Not shipped | Still a follow-up; this guide keeps the trace plan as future work. |
| Broader MCP-native UX notices | Partial | Degraded-mode notices are shipped; zero-result "call X first" notices and richer fallback notices remain follow-up work. |

Fresh verification after the reliability/ergonomics work:

- `make ci-local` — 664 passed, 2 skipped.
- `make docker-build`, `make docker-down`, `PUBTATOR_LINK_PORT=8011 make docker-up`.
- `curl -sS http://localhost:8011/ready` returned `schema_current: true`.
- `curl -sS http://localhost:8011/metrics | head -40` included `mcp_tool_calls_total` and `mcp_tool_latency_seconds`.

---

## 1. The three pillars (and what each one catches)

| Pillar | Catches | Cost | When you reach for it |
|---|---|---|---|
| **Structured logs** | Discrete events: tool called, retry triggered, fallback used, parse failed, schema stale | Cheap (text) | "What happened on this specific request?" |
| **Metrics** | Aggregates over time: p95 latency, error rate, cache hit ratio, queue depth | Very cheap (counters/histograms) | "Is the system healthy *right now*? Is anything trending bad?" |
| **Traces** | Request-scoped causal chain: route → service → repo → upstream API → DB query | Medium (sampled) | "Where did the 800 ms go? Which DB query is the bottleneck?" |

You need **all three**, not because of completeness theatre, but because each answers a different question. Logs alone make you grep; metrics alone tell you it's broken without telling you why; traces alone don't survive long enough for a postmortem.

A fourth, often-overlooked, item:

| | | | |
|---|---|---|---|
| **Errors / crashes** (Sentry-style) | Exceptions with stack, request context, last-known state | Cheap | "Show me unique exceptions in the last 24 h, grouped by fingerprint." |

Ship this **before** metrics or traces. It's the highest leverage thing on day one.

---

## 2. Log levels — concrete conventions for this codebase

Python's stdlib has 5 levels; MCP's protocol-level logging channel uses the 8-level RFC 5424 set. Map them like this:

| Level | RFC 5424 | When to use | Examples from PubTator-Link |
|---|---|---|---|
| `DEBUG` | debug | Loop iterations, parameter dumps. **Disabled in prod by default.** | "Considering passage P… for inclusion (rank=0.81)" |
| `INFO` | info | Successful business events worth keeping in prod | "MCP tool call completed", "Review preparation queued", "Cache hit" |
| | notice (MCP-only) | Successful but unusual or audit-relevant | "Fell back to Europe PMC for PMC10000000", "Used cached entity match for BRCA1" |
| `WARNING` | warning | Degraded-but-recovered, including all retries and fallbacks | "PubTator3 returned 429, retrying with 1.4s backoff", "review_schema_not_current — surfaced fallback to client" |
| `ERROR` | error | Request-failing condition. Always include `error_code`. | "MCP tool execution failed", "Review preparation job marked failed" |
| `CRITICAL` | critical | Server-wide degradation; oncall-pageable | "asyncpg pool exhausted, requests will time out", "MCP server failed to bind transport" |
| | alert (MCP-only) | Action required immediately | (rarely used by servers — usually for hosts) |
| | emergency (MCP-only) | System unusable | (rarely used by servers) |

**The two rules that matter most:**

1. **Every WARNING and above must include `error_code` (when applicable) and `tool_name`** so you can group and rate-alert without parsing free text. Your `mcp/errors.py` already produces stable error codes — use them.
2. **Default production threshold is INFO**, not DEBUG. Set DEBUG level only on demand via env var (`LOG_LEVEL=DEBUG`) or — for MCP — via the spec's `logging/setLevel` request from the host.

References: [MCP logging spec](https://modelcontextprotocol.info/specification/draft/server/utilities/logging/), [Apitally FastAPI logging guide](https://apitally.io/blog/fastapi-logging-guide).

### A small style guide that pays off later

- **Use snake_case event keys** (`tool_name`, not `Tool Name`). They become Loki/Datadog field names.
- **One event = one line.** Don't multi-line stack traces in INFO logs.
- **Static event name, dynamic context.** `log.info("mcp_tool_completed", tool_name=..., latency_ms=..., outcome="ok")` — easy to filter on `event = "mcp_tool_completed"`.
- **Don't log secrets, raw user content, or PII.** For PubTator-Link specifically: log PMIDs (public), log query *length* not query *text* by default, **never log `submit_text_annotation` request body** (may contain patient-derived text).

---

## 3. The MCP-native logging channel — partially implemented

The MCP spec defines two relevant primitives:

- **`notifications/message`** — server pushes a structured log to the host: `{ level, logger, data }` where `data` is arbitrary JSON.
- **`logging/setLevel`** — host can request a minimum severity at runtime (default is `warning`).

**Why this matters:** when a Claude/Cursor user runs `pubtator.retrieve_review_context_batch` against degraded evidence, the host can surface a server-emitted notice in the same chat thread. This is now implemented for review evidence degraded modes.

In FastMCP this is exposed via the `Context` object passed to a tool:

```python
from fastmcp import Context

@mcp.tool(name="pubtator.retrieve_review_context_batch", ...)
async def retrieve_review_context_batch(review_id: str, queries: list[str], ..., ctx: Context | None = None):
    if not await service.review_index_has_passages(review_id):
        await ctx.warning(
            "Review index has no prepared passages - run pubtator.index_review_evidence first.",
        )
    ...
```

`ctx.debug() / ctx.info() / ctx.notice() / ctx.warning() / ctx.error() / ctx.critical()` all map to `notifications/message`. The host respects the level set by the user's `logging/setLevel`, so you can emit liberally without being noisy.

**Shipped:** `pubtator.index_review_evidence`, `pubtator.retrieve_review_context`, and `pubtator.retrieve_review_context_batch` now accept FastMCP-injected `ctx` without exposing it in public JSON schema, and emit warnings for degraded review evidence.

**Still left:** wrap zero-result "call X first" branches and non-error fallback decisions in `ctx.warning()` or `ctx.notice()`.

---

## 4. Implementation plan — four small PRs

Each PR is independently deployable. In this repository the lifecycle instrumentation is implemented in the central `run_mcp_tool` wrapper rather than a separate decorator, because all public MCP tools already route through that wrapper.

### PR-1: structured logging + correlation IDs (foundation)

**What:** wire structlog with JSON output, contextvars for request scoping, and `asgi-correlation-id` for X-Request-ID propagation.

**Why first:** every later improvement (metrics, traces, error tracking) reads structured fields. Get the field names right once.

**Add deps** (`pyproject.toml`):

```toml
dependencies = [
    ...
    "asgi-correlation-id>=4.3.0,<5.0.0",
]
```

**Update `pubtator_link/logging_config.py`** — replace the current shared formatter with this skeleton:

```python
import logging
import structlog
from structlog.contextvars import merge_contextvars

def configure_logging(*, transport: str, level: str = "INFO") -> None:
    is_stdio = transport == "stdio"
    is_dev = level.upper() == "DEBUG"

    processors = [
        merge_contextvars,                        # pulls correlation_id, tool_name, etc.
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,                        # custom; see §6
    ]
    if is_dev and not is_stdio:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())  # orjson via patch if needed

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        cache_logger_on_first_use=True,
        # IMPORTANT: stdio mode → stderr-only to keep stdout clean for MCP JSON
        logger_factory=structlog.WriteLoggerFactory(file=sys.stderr if is_stdio else sys.stdout),
    )
```

**Wire correlation IDs in `server_manager.py`** — use the *pure ASGI* middleware form (the `@app.middleware("http")` decorator does **not** propagate contextvars correctly to handlers because of FastAPI's task-group copying — this is a real, documented foot-gun):

```python
from asgi_correlation_id import CorrelationIdMiddleware

app.add_middleware(
    CorrelationIdMiddleware,
    header_name="X-Request-ID",
    update_request_header=True,
    generator=lambda: str(uuid.uuid4()),
)
```

That middleware also binds `correlation_id` into structlog's contextvars, so every log line in that request automatically carries it.

**Wire it into stdio MCP mode too** — generate one ID per tool call (see PR-2 decorator).

### PR-2: MCP tool instrumentation (the missing piece)

**What:** one decorator that wraps every `@mcp.tool` registration and emits exactly the events you'll want to query later.

**Why second:** with PR-1's contextvars, this gives you the answer to "what happened on request X?" in one log query.

**Add `pubtator_link/mcp/instrumentation.py`:**

```python
from __future__ import annotations
import time
import uuid
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any
import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

log = structlog.get_logger("mcp.tool")

def instrument_tool(name: str) -> Callable:
    """Wrap an MCP tool body. Emits start/complete/error events with stable fields."""
    def decorator(func: Callable[..., Awaitable[dict[str, Any]]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request_id = str(uuid.uuid4())
            started = time.perf_counter()
            bind_contextvars(tool_name=name, request_id=request_id)
            log.info("mcp_tool_started", arg_keys=sorted(kwargs.keys()))
            try:
                result = await func(*args, **kwargs)
                latency_ms = (time.perf_counter() - started) * 1000
                log.info(
                    "mcp_tool_completed",
                    latency_ms=round(latency_ms, 2),
                    response_size_chars=_safe_size(result),
                    outcome="ok",
                )
                return result
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                # error_code resolved by mcp/errors.py — re-extract here for log field parity
                from pubtator_link.mcp.errors import error_code_for_exception
                log.warning(
                    "mcp_tool_failed",
                    latency_ms=round(latency_ms, 2),
                    error_code=error_code_for_exception(exc),
                    error_class=type(exc).__name__,
                    outcome="error",
                    exc_info=True,
                )
                raise
            finally:
                clear_contextvars()
        return wrapper
    return decorator
```

**Apply at registration** in `mcp/tools/literature.py` (and the other five tool files):

```python
@mcp.tool(name="pubtator.search_literature", ...)
@instrument_tool("pubtator.search_literature")
async def search_literature(...): ...
```

**What you can now answer:**
- "What's the p95 latency of `retrieve_review_context_batch`?" → grep `mcp_tool_completed` + `tool_name=...`
- "Which tool fails most often?" → group `mcp_tool_failed` by `error_code` + `tool_name`
- "Why did this specific call fail?" → search `request_id=<uuid>` across all logs

### PR-3: Prometheus metrics + a `/metrics` endpoint

**What:** export the same events as time-series counters/histograms.

**Why third:** logs answer per-request questions; metrics answer "how is the fleet doing right now?" and drive alerts.

**Add deps:**

```toml
"prometheus-client>=0.21.0,<1.0.0",
```

**Add `pubtator_link/observability/metrics.py`:**

```python
from prometheus_client import Counter, Histogram, Gauge, CONTENT_TYPE_LATEST, generate_latest

mcp_tool_calls_total = Counter(
    "mcp_tool_calls_total",
    "MCP tool invocations.",
    labelnames=("tool", "outcome", "error_code"),
)
mcp_tool_latency_seconds = Histogram(
    "mcp_tool_latency_seconds",
    "MCP tool latency.",
    labelnames=("tool",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60),
)
upstream_calls_total = Counter(
    "upstream_calls_total",
    "Upstream HTTP calls (PubTator, NCBI, EuropePMC).",
    labelnames=("upstream", "status_class"),
)
upstream_retries_total = Counter(
    "upstream_retries_total",
    "Number of retry attempts performed.",
    labelnames=("upstream", "reason"),  # reason in {429, 5xx, timeout}
)
cache_events_total = Counter(
    "cache_events_total",
    "LRU cache events.",
    labelnames=("cache", "event"),  # event in {hit, miss, set, evict}
)
review_queue_depth = Gauge(
    "review_queue_depth",
    "Pending review preparation jobs.",
)
db_pool_in_use = Gauge(
    "db_pool_in_use",
    "asyncpg connections currently in use.",
)
```

Update `instrument_tool` to also emit `mcp_tool_calls_total.labels(...)` and observe `mcp_tool_latency_seconds`. Add a route:

```python
@router.get("/metrics", include_in_schema=False)
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

**Alerts to set up first** (PromQL examples):

- Tool error rate > 5% over 5 min: `sum(rate(mcp_tool_calls_total{outcome="error"}[5m])) / sum(rate(mcp_tool_calls_total[5m])) > 0.05`
- Tool p95 latency > 10s: `histogram_quantile(0.95, sum by (le, tool) (rate(mcp_tool_latency_seconds_bucket[5m]))) > 10`
- Review queue depth > 100 for 10 min (sustained backlog).
- DB pool saturation > 90%: `db_pool_in_use / db_pool_size > 0.9`
- Upstream 429 storm: `rate(upstream_retries_total{reason="429"}[5m]) > 1`

These five alerts cover ~90% of "the server is misbehaving" cases.

### PR-4: OpenTelemetry traces

**What:** distributed tracing across `route → service → repository → upstream HTTP → DB`.

**Why last:** traces are the heaviest pillar (operationally and cost-wise), but they're what you actually open when "the p95 went up by 400 ms last Tuesday at 14:32" and you don't know which span ate the budget.

**Add deps:**

```toml
"opentelemetry-api>=1.30.0",
"opentelemetry-sdk>=1.30.0",
"opentelemetry-exporter-otlp>=1.30.0",
"opentelemetry-instrumentation-fastapi>=0.51b0",
"opentelemetry-instrumentation-httpx>=0.51b0",
"opentelemetry-instrumentation-asyncpg>=0.51b0",
```

**Add `pubtator_link/observability/tracing.py`:**

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

def configure_tracing(app, *, service_name: str, otlp_endpoint: str | None) -> None:
    if not otlp_endpoint:                          # tracing optional / no-op when unset
        return
    resource = Resource.create({"service.name": service_name, "service.version": "1.0.0"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
    HTTPXClientInstrumentor().instrument()
    AsyncPGInstrumentor().instrument()
```

**Custom spans** for non-HTTP boundaries (review preparation queue, FTS query, ranker):

```python
tracer = trace.get_tracer("pubtator_link.review_context")

async def retrieve(...):
    with tracer.start_as_current_span("retrieve_context") as span:
        span.set_attribute("review.id", review_id)
        span.set_attribute("query.count", len(queries))
        ...
        span.set_attribute("result.passages", len(passages))
        span.set_attribute("result.budget_used_chars", chars_used)
```

**Background task gotcha:** OpenTelemetry context does *not* automatically propagate into `BackgroundTasks` or asyncio tasks. For your `ReviewPreparationQueue` workers, capture and re-attach context explicitly:

```python
from opentelemetry import context as otel_context

# Capture at enqueue time:
ctx = otel_context.get_current()

# Re-attach at worker dequeue:
token = otel_context.attach(ctx)
try:
    with tracer.start_as_current_span("review_prepare_pmid") as span:
        ...
finally:
    otel_context.detach(token)
```

Without this, your queue work shows up as orphan traces — a real and documented FastAPI background-task pitfall.

**Sampling:** in production set `OTEL_TRACES_SAMPLER=parentbased_traceidratio` and `OTEL_TRACES_SAMPLER_ARG=0.1` (10% of root traces sampled). Always-sample errors via a custom processor.

---

## 5. Where the four PRs land in your code

| File | PR-1 | PR-2 | PR-3 | PR-4 |
|---|---|---|---|---|
| `pubtator_link/logging_config.py` | rewrite | — | — | — |
| `pubtator_link/server_manager.py` | add CorrelationIdMiddleware | — | mount `/metrics` route | call `configure_tracing(app, ...)` |
| `pubtator_link/mcp/instrumentation.py` (new) | — | create | extend with metrics | add custom spans |
| `pubtator_link/mcp/tools/*.py` | — | apply `@instrument_tool` decorator | — | — |
| `pubtator_link/observability/metrics.py` (new) | — | — | create | — |
| `pubtator_link/observability/tracing.py` (new) | — | — | — | create |
| `pubtator_link/api/client.py` | log retries with structlog | — | bump `upstream_calls_total` / `upstream_retries_total` | (httpx instrumented automatically) |
| `pubtator_link/services/review_preparation_queue.py` | — | — | update `review_queue_depth` gauge | propagate OTel context across workers |
| `mcp_server.py` | call `configure_logging(transport="stdio", ...)` | — | — | — |

---

## 6. Production gotchas (worth pinning to your runbook)

1. **stdio MCP mode pollutes stdout if any handler writes there.** You already guard this in `mcp_server.py`. Re-verify whenever you add logging — the `structlog.WriteLoggerFactory(file=sys.stderr)` choice in PR-1 is load-bearing.
2. **`@app.middleware("http")` does not propagate contextvars.** Use `app.add_middleware(CorrelationIdMiddleware, ...)` or pure ASGI middleware. This bites every team once.
3. **Background tasks and asyncio.create_task lose OTel context.** Capture/attach explicitly (shown above).
4. **Don't log raw user input from `submit_text_annotation`.** It can contain patient-derived text. Log only `text_length`, `bioconcepts_count`, `submitter_session_id`. Add a redaction processor:

   ```python
   _SENSITIVE_KEYS = frozenset({"text", "raw_text", "annotation_payload", "patient_text"})
   def _redact_sensitive(_logger, _name, event_dict):
       for k in list(event_dict):
           if k in _SENSITIVE_KEYS:
               event_dict[k] = "[REDACTED:%d_chars]" % len(str(event_dict[k]))
       return event_dict
   ```
5. **Cardinality explosions in metrics.** Never use `review_id`, `pmid`, `passage_id`, or query text as a Prometheus label. They're unbounded — your TSDB will OOM. Keep labels to `tool`, `outcome`, `error_code`, `upstream`, `cache`, `status_class`.
6. **Sampling is not optional in production.** 100% trace sampling will dwarf your tool latency and your ops budget. 10% root-span sampling + always-sample-on-error is the default.
7. **MCP `notifications/message` only flows to clients that opted in via `logging/setLevel`.** Default threshold is `warning`. Don't be surprised when DEBUG-level `ctx.debug()` calls don't appear in the host until the user lowers the level.
8. **Sentry/Errortracking before metrics.** If your budget is one tool, integrate Sentry first — it gives you exception fingerprints, stack traces, and request context for free, and it works even if you never set up Prometheus.

---

## 7. Recommended log/event vocabulary (use these names everywhere)

Standardize early; renaming events later breaks dashboards and alerts.

| Event name | Where emitted | Required fields |
|---|---|---|
| `mcp_tool_started` | `run_mcp_tool` wrapper | `tool_name`, `pmid_count` |
| `mcp_tool_completed` | `run_mcp_tool` wrapper | `tool_name`, `pmid_count`, `latency_ms` |
| `mcp_tool_failed` | `run_mcp_tool` wrapper | `tool_name`, `pmid_count`, `latency_ms`, `error_code` |
| `upstream_request` | `api/client.py` | `upstream`, `method`, `endpoint`, `status_code`, `latency_ms`, `attempt` |
| `upstream_retry` | `api/retry.py` | `upstream`, `attempt`, `reason`, `delay_ms` |
| `cache_event` | every `@alru_cache` boundary | `cache`, `event` (`hit/miss/set/evict`), `key_hash` |
| `review_preparation_started` | `review_preparation_queue.py` | `review_id`, `pmids_count`, `prepare_mode` |
| `review_preparation_completed` | `review_preparation_queue.py` | `review_id`, `prepared`, `failed`, `duration_ms` |
| `review_context_retrieved` | `review_context_service.py` | `review_id`, `query_count`, `passages_returned`, `chars_returned`, `budget_strategy` |
| `db_query` | repository layer (sample only when slow) | `repo`, `op`, `latency_ms`, `rows`, `slow=true` if > 200 ms |

These are the events you'll actually search and alert on. Add fields freely; never rename a published one.

---

## 8. Cost / ops sizing

For a single-tenant POC at this scale (single instance, low QPS):

- **Logs:** ship to Loki / Datadog / a single ClickHouse instance via Vector or Promtail. Expect ~100 MB/day at INFO level under modest load. With 30-day retention: free tier of any vendor.
- **Metrics:** Prometheus scrape every 15 s. Storage = ~1–5 GB/month. Free.
- **Traces:** with 10% sampling and ~1k traces/day: a single Tempo or Jaeger instance is fine. Free tier on Grafana Cloud / SigNoz / Honeycomb.
- **Errors:** Sentry free tier (5k events/month) is enough for a POC.

If you're on a single VM and want zero-vendor: a [Grafana + Prometheus + Loki + Tempo](https://github.com/blueswen/fastapi-observability) stack runs comfortably in ~1.5 GB RAM.

---

## 9. Acceptance checklist

When all four PRs are merged, you should be able to perform the following exercises in production within 60 seconds each:

- Status: reliability/ergonomics follow-up is tracked by `docs/superpowers/plans/2026-05-02-review-rag-reliability-and-llm-ergonomics-implementation.md`.
- [x] Find lifecycle log lines for MCP calls by event name and `tool_name`.
- [x] Expose MCP tool latency histograms for p95 dashboards.
- [x] Expose MCP tool error counters by `error_code`.
- [x] Return bounded MCP diagnostics, degraded mode, and fallback preview in tool error envelopes.
- [x] Surface review degraded-mode warnings through MCP context notifications.
- [ ] Identify which DB query took > 1 s in a slow request (trace).
- [ ] Page oncall when upstream 429s spike or DB pool saturates.
- [ ] Reproduce: download the trace+logs for one failing request and replay locally.
- [ ] (LLM-side) Have Claude/Cursor surface server-emitted `ctx.warning` notices for zero-result retrieval and fallback branches.

The last item is the one no other server in this domain currently does. It's where the LLM-consumer experience leaps from "fine" to "feels alive."

---

## 10. References

- [MCP Logging spec — `notifications/message`, `logging/setLevel`, RFC 5424 levels](https://modelcontextprotocol.info/specification/draft/server/utilities/logging/)
- [MCP Logging Tutorial — mcpevals.io](https://www.mcpevals.io/blog/mcp-logging-tutorial)
- [MCP Server Logs guide — Merge.dev](https://www.merge.dev/blog/mcp-server-logs)
- [structlog production patterns — Dash0](https://www.dash0.com/guides/python-logging-with-structlog)
- [Logging setup for FastAPI + Uvicorn + structlog (with Datadog) — nymous gist](https://gist.github.com/nymous/f138c7f06062b7c43c060bf03759c29e)
- [asgi-correlation-id middleware](https://github.com/snok/asgi-correlation-id)
- [OpenTelemetry FastAPI Instrumentation — Python Contrib](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
- [Tracing FastAPI background tasks with OTel spans — OneUptime](https://oneuptime.com/blog/post/2026-02-06-trace-fastapi-background-tasks-opentelemetry/view)
- [End-to-end LLM observability in FastAPI with OpenTelemetry — freeCodeCamp](https://www.freecodecamp.org/news/build-end-to-end-llm-observability-in-fastapi-with-opentelemetry/)
- [Production-grade FastAPI logging guide — Apitally](https://apitally.io/blog/fastapi-logging-guide)
- [FastAPI observability stack reference (Tempo + Loki + Prometheus + Grafana)](https://github.com/blueswen/fastapi-observability)
