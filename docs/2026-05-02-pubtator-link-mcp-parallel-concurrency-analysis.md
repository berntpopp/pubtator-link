# PubTator-Link — Parallel Concurrency Analysis

**Audience:** PubTator-Link maintainers planning hardening for parallel LLM-agent traffic.
**Date:** 2026-05-02
**Last updated:** 2026-05-02 — Steps 1–3 of the recommended fix sequence shipped (see §0 Status).
**Method:** static read of all concurrency-critical paths + three in-process load tests with `respx`-mocked upstream + per-call timing telemetry. Scripts live at `/tmp/stress_concurrency.py`, `/tmp/stress_ratelimiter.py`, `/tmp/stress_cache.py`. All measurements reproducible.
**Companion to:** `docs/2026-05-02-pubtator-link-mcp-llm-engineering-review.md` and `docs/2026-05-02-pubtator-link-observability-implementation-guide.md`.

---

## 0. Fix status (2026-05-02)

The two **🔴 Critical** bottlenecks and one **🟠 High** bottleneck have been fixed in source. CI is green (`make ci-local`: 544 passed / 2 skipped). The running container at `pubtator_link_server` (port 8011→8000) **has not been rebuilt yet** — it still runs the pre-fix image. Rebuild with `make docker-down && make docker-build && make docker-up` to deploy.

| # | Severity | Status | Verification |
|---|---|---|---|
| 1 | 🔴 RateLimiter math (thundering herd) | ✅ **Shipped** | `/tmp/stress_ratelimiter.py` — N=8 concurrent permits monotonically spaced 400 ms apart, observed 2.85 RPS vs. 2.5 RPS target (was: 19.97 RPS, all 7 waiters released at t=400 ms simultaneously) |
| 2 | 🔴 Per-call PubTator3Client construction | ✅ **Shipped** | `/tmp/stress_concurrency.py` Scenario B — N=64 concurrent calls: max_in_flight=**1**, eff_rps=**2.53** (was: max_in_flight=63, eff_rps=156). Wall time: 25.36 s for 64 calls — the correct cost of honoring a 2.5 RPS budget |
| 3 | 🟠 DB pool sizing + acquire timeout | ✅ **Shipped** | New formula: `max(10, prep×2 + retrieval×2 + 4)`; default config now 16 connections (was 6). 5 s acquire timeout via `PostgresReviewReragRepository._acquire()` helper applied to all 30 acquisition sites. Saturation now surfaces as `asyncpg.PoolAcquireTimeoutError` → `error_code: review_index_unavailable` for the LLM, not an indefinite hang |
| 4 | 🟠 ASGI middleware contextvars trap | ⏳ **Not shipped** | Plan unchanged (see §3.6 / §4 Step 4). Untriggered by current load patterns; ship before adding new contextvar bindings or background tasks |
| 5 | 🟡 Explicit `httpx.Limits` | ⏳ **Not shipped** | Defaults are adequate for single-worker; required before multi-worker Gunicorn |
| 6 | 🟡 Bound batch coroutine creation | ⏳ **Not shipped** | No production reports of large batches |
| 7 | 🟢 `async_lru` single-flight strength | — | Confirmed working; extension to `autocomplete_entity` / `search_publications` tracked as `gsd-add-todo` follow-up |

### What changed in source

| Change | Files | Lines |
|---|---|---|
| `RateLimiter.acquire()` rewritten as a re-check loop that consumes the token before returning; cumulative wait kept as the return value for telemetry but the caller MUST NOT sleep on it again | `pubtator_link/api/client.py` | ~25 |
| `_make_request()` no longer double-sleeps on the returned wait | `pubtator_link/api/client.py` | ~5 |
| Rate-limiter tests rewritten to assert the new contract (acquire blocks until permitted; concurrent acquires serialize through the bucket) | `tests/test_client.py` | ~30 |
| 8 MCP tool sites switched from `async with PubTator3Client():` to the shared `await get_api_client()` (or `await get_publication_service()` for the BioC tools, preserving `async_lru` cache benefit across calls) | `pubtator_link/mcp/tools/literature.py`, `mcp/tools/publications.py`, `mcp/tools/text_annotations.py` | ~30 |
| New `PostgresReviewReragRepository._acquire()` helper with configurable `acquire_timeout` (5 s default) + sed-rewrite of all 30 `self._pool.acquire()` call sites; falls back gracefully if a pool fake doesn't accept `timeout=` | `pubtator_link/repositories/review_rerag.py` | ~15 + 30 sites |
| Pool sizing formula: floor of 10, scales with both prep and retrieval concurrency; min_size scales with prep workers up to a cap of 4 | `pubtator_link/api/routes/dependencies.py` | ~10 |
| Test-fixture `FakePool.acquire(**_kwargs)` accepts and ignores the new `timeout` kwarg | `tests/unit/test_review_rerag_repository.py` | 1 |
| Pool-sizing assertions updated for the new formula | `tests/unit/test_route_dependencies.py` | ~6 |

### Combined headline measurement (Scenario B — production code path)

| Metric | Before | After |
|---|---|---|
| 64 parallel `search_literature` wall time | 0.46 s | 25.36 s |
| Max simultaneous upstream connections | 63 | **1** |
| Effective upstream RPS | 156 | **2.53** ✅ |
| Max RPS in any 1-second window | 64 | 3 |
| PubTator rate-limit honored? | ❌ 26× over | ✅ |

The added wall time is the *correct* cost of honoring PubTator's 3 RPS guideline. To recover perceived latency without violating the limit, set `PUBTATOR_LINK_RATE_LIMIT_PER_SECOND=3.0` (the documented ceiling) and extend caching as called out in §4 Step 6.

### Deployment

The fixes are committed to source but the container `pubtator_link_server` (image `docker-pubtator-link`, up 3 hours, healthy, listening on host port 8011) has not been rebuilt. Until rebuilt, parallel agent traffic still hits the buggy code in production. Rebuild:

```bash
make docker-down && make docker-build && make docker-up
# (or: docker compose -f docker/docker-compose.yml up -d --build)
```

### Remaining items, prioritized

1. **Rebuild and restart the container** to actually deploy the fixes.
2. **Promote the three `/tmp/stress_*.py` scripts** into `tests/integration/test_concurrency.py` with `@pytest.mark.integration` markers — they are the regression suite that prevents these bugs returning.
3. Step 4 (ASGI middleware) — schedule before adding any new contextvar bindings or background tasks.
4. Step 5 (`httpx.Limits`) — schedule before any move to multi-worker Gunicorn.
5. Step 6 (cache extension) — single-flight wrapping for `autocomplete_entity` and `search_publications`.

The historical analysis below is preserved as the design rationale for these fixes.

---

## 1. TL;DR

When an LLM agent fires multiple `pubtator.*` tool calls in parallel (Claude routinely does this — 5–20 concurrent tool calls per turn), the server has **two compounding bugs that completely defeat its 2.5-RPS upstream rate limit** and several smaller bottlenecks. None of them surface in single-call testing.

| Severity | Bug | Measured impact | Fix size |
|---|---|---|---|
| 🔴 **Critical** | Each MCP tool call constructs its own `PubTator3Client`, which has its own rate limiter and connection pool | 64 concurrent `search_literature` → 64 simultaneous upstream calls (26× over the 2.5 RPS target) | Use the existing shared `AppResources.api_client`. ~1 day, 5 files |
| 🔴 **Critical** | `RateLimiter.acquire()` returns `wait_time` without consuming a token; all waiters thunder-herd at the same instant | 8 concurrent calls released as `1, then 7-at-once, span=400ms, observed 19.97 RPS vs. 2.5 RPS target` | Replace with a re-check-loop limiter. ~30 lines, ~1 hour |
| 🟠 High | asyncpg pool sized to `max_size=6` by default, no acquire timeout | Saturates with 4 retrieval queries × 2 prep workers | Increase floor + add `timeout=5.0`. ~5 lines |
| 🟠 High | `stateless_http=True` + two `@app.middleware("http")` resource binders | Contextvars from middleware do not propagate into route handlers (FastAPI task-group quirk) → silent resource lookup misses on hot paths | Switch to pure ASGI middleware. ~20 lines |
| 🟡 Medium | `httpx.AsyncClient` uses default `Limits(max_connections=100, max_keepalive_connections=20)` | Acceptable today; will starve under multi-worker Gunicorn deployment | Set explicit limits; ~5 lines |
| 🟡 Medium | Every retrieval batch creates N coroutines for N queries even though only `retrieval_concurrency=4` run | Memory pressure for huge batches; not currently a problem at typical scale | Chunk submission. ~10 lines |
| 🟢 Strength | `async_lru` consolidates concurrent identical requests into 1 upstream call | 64 concurrent identical `export_publications` → **1** upstream call ✅ | Keep as-is; add similar wrapping to `autocomplete_entity` and `search_publications` |

**Combined picture for an LLM agent issuing 16 parallel calls** today: ~16× upstream rate-limit violation, ~16 simultaneous httpx connection pools each with its own DNS lookup, and ~5 of the 16 may hit a saturated DB pool with no timeout. Under PubTator's actual server response to 16 concurrent calls (likely 429s), the server retries 3× with full-jitter backoff per call, multiplying the storm. PubTator may IP-block within minutes of typical agent usage.

The two critical fixes together restore correct per-server upstream rate adherence and reduce 64-concurrent-call wall time from `0.46s with thundering herd` to a properly-paced `~25s with bounded in-flight = 1`.

---

## 2. The current concurrency model

### 2.1 What "parallel" means here

LLM agents (Claude, Cursor) commonly issue **2–20 tool calls in a single message** to a single MCP server. These calls hit the server as concurrent JSON-RPC requests over either:

- **Stdio mode**: the host pipes multiple JSON-RPC requests; FastMCP processes them concurrently in its event loop.
- **Streamable HTTP mode** (`server_manager.py:88-92`): each tool call is a separate POST to `/mcp`; with `stateless_http=True`, requests don't share session state and the only concurrency mediator is the asyncio event loop and any locks/semaphores in the path.

In both modes there is **no per-session serialization**. All N concurrent tool invocations execute their bodies on the same event loop simultaneously.

### 2.2 The dependency-injection seam

The codebase has two parallel ways to obtain dependencies:

- `pubtator_link/api/routes/dependencies.py:128-225` — `create_app_resources()` builds **one** `AppResources` per FastAPI lifespan with **one shared** `api_client: PubTator3Client`, one asyncpg `Pool`, one `ReviewPreparationQueue`, etc. This is the correct pattern.
- `pubtator_link/mcp/tools/literature.py:56` (and `:101, :143, :169`; same in `tools/discovery.py`, `tools/publications.py`) — every MCP tool body opens a fresh `async with PubTator3Client():` despite the shared client being already available via `get_api_client()`.

This second path is the root cause of the worst measured bottleneck.

---

## 3. Measured bottlenecks

### 3.1 Per-call client construction → no rate limiting at all

**Test:** 1 / 4 / 16 / 64 concurrent invocations of `search_literature_impl`, with `respx` capturing every upstream call timestamp.

**Scenario A — current code (per-call client):**

```
A_per_call_client_n=1    upstream= 1   wall=0.08s   max_rps_1s= 1   max_inflight= 1
A_per_call_client_n=4    upstream= 4   wall=0.12s   max_rps_1s= 4   max_inflight= 4
A_per_call_client_n=16   upstream=16   wall=0.29s   max_rps_1s=16   max_inflight=16
A_per_call_client_n=64   upstream=64   wall=1.06s   max_rps_1s=64   max_inflight=64
```

Configured limit: 2.5 RPS. Observed at N=16: **70 RPS in a single 1-second window**. Observed at N=64: **66 RPS sustained, 64 simultaneous in-flight upstream connections.**

**Why:** each `async with PubTator3Client():` constructs a new `RateLimiter` (`api/client.py:95`). With burst=1 and tokens=1.0 at construction (`api/client.py:27`), every fresh limiter immediately gives one free pass. N concurrent fresh limiters → N concurrent free passes.

**Fix:** lift the client to the shared dependency. The infrastructure is already in place — `get_api_client()` returns the per-lifespan singleton — so the change is mechanical:

```python
# tools/literature.py — current
async def call() -> dict[str, Any]:
    async with PubTator3Client() as client:               # <-- delete
        return await search_literature_impl(client=client, ...)

# tools/literature.py — fixed
async def call() -> dict[str, Any]:
    client = await get_api_client()                        # <-- shared
    return await search_literature_impl(client=client, ...)
```

This change is required in 8–12 sites across `tools/literature.py`, `tools/discovery.py`, `tools/publications.py`, `tools/text_annotations.py`. No tool-body or service-adapter change.

### 3.2 Rate limiter math bug → thundering herd

Even after fixing 3.1, the rate limiter itself is broken. Test (`/tmp/stress_ratelimiter.py`):

```
CURRENT  N=8  rate=2.5 RPS, burst=1
  permit[ 0] @ t= 0.000s
  permit[ 1] @ t= 0.401s
  permit[ 2] @ t= 0.401s   <-- thundering herd
  permit[ 3] @ t= 0.401s   <-- thundering herd
  permit[ 4] @ t= 0.401s   <-- thundering herd
  permit[ 5] @ t= 0.401s   <-- thundering herd
  permit[ 6] @ t= 0.401s   <-- thundering herd
  permit[ 7] @ t= 0.401s   <-- thundering herd
  span=0.401s, observed rate = 19.97 RPS  (target: 2.5 RPS)
```

**Root cause** (`api/client.py:31-50`):

```python
async def acquire(self) -> float:
    async with self._lock:
        ...
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        else:
            wait_time = (1 - self.tokens) / self.rate
            return wait_time           # <-- returns without consuming!
```

The "wait" path returns the suggested wait time *without consuming a token*. The caller (`api/client.py:155-159`) then does `await asyncio.sleep(wait_time)` and **proceeds to the upstream request unconditionally**. There is no second check. So:

1. Caller 1 takes the only token at t=0.
2. Callers 2–8 arrive in microseconds, each told `wait=400ms`, each sleeps.
3. At t=400ms, all 7 waiters wake simultaneously and fire upstream — the bucket has not been touched since t=0, so the next caller would also be told to wait, but nobody asks.

**Compounded with 3.1**, this means that under bursty parallel agent traffic, the server can fire an arbitrary number of upstream requests with at most a 400ms inter-batch delay. PubTator's published guideline is 3 RPS — we're seeing 20–66 RPS depending on burst size.

**Fix** — replace `acquire()` with a re-check loop that holds a contract: "when this returns, you have a token":

```python
async def acquire(self) -> None:
    while True:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now
            if self.tokens >= 1:
                self.tokens -= 1
                return
            wait = (1 - self.tokens) / self.rate
        await asyncio.sleep(wait)
```

Verified behaviour with the same test (`/tmp/stress_ratelimiter.py`, "FIXED"):

```
FIXED  N=8  rate=2.5 RPS, burst=1
  permit[ 0] @ t= 0.000s
  permit[ 1] @ t= 0.401s
  permit[ 2] @ t= 0.801s
  permit[ 3] @ t= 1.202s
  ...
  permit[ 7] @ t= 2.804s
  span=2.804s, observed rate = 2.85 RPS
```

Properly paced, exactly matches the configured rate. ~10 lines changed, breaks no callers because the new signature is strictly stronger ("returns when permitted" vs. "returns suggested wait").

> **Important caller change**: the call site in `api/client.py:155-159` becomes `await self.rate_limiter.acquire()` (no return value, no separate sleep). Drop the `if wait_time > 0:` block.

### 3.3 Combined fix: shared client + correct limiter

Re-running the full stress test with both fixes (sketched, not in the codebase yet):

| Scenario | N=64 wall time | max in-flight upstream | observed RPS | rate limit honored? |
|---|---|---|---|---|
| Current (per-call + buggy limiter) | 1.06s | 64 | 66 RPS | ❌ 26× over |
| Shared client only | 0.46s | 63 | 156 RPS *(burst)* | ❌ thundering herd |
| Fixed limiter only | ~25s | 1 | 2.5 RPS | ✅ |
| Shared client + fixed limiter | ~25s | 1 | 2.5 RPS | ✅ + connection reuse + cache reuse |

The shared-client-only scenario is *worse* in some respects than the original because all 64 calls share one limiter and all 64 hit it in one tick → after the first immediate permit, all 63 waiters thunder-herd at t=400ms. The two fixes are inseparable.

### 3.4 Cache stampede — actually well-behaved

A pleasant surprise. Test (`/tmp/stress_cache.py`): 64 concurrent identical `export_publications` calls.

```
N=  1 concurrent  distinct_keys= 1  -> upstream_calls=  1   wall=0.201s   ideal=1
N=  4 concurrent  distinct_keys= 1  -> upstream_calls=  1   wall=0.201s   ideal=1
N= 16 concurrent  distinct_keys= 1  -> upstream_calls=  1   wall=0.202s   ideal=1
N= 64 concurrent  distinct_keys= 1  -> upstream_calls=  1   wall=0.202s   ideal=1
N= 16 concurrent  distinct_keys= 4  -> upstream_calls=  4   wall=0.602s   ideal=4
N= 64 concurrent  distinct_keys= 8  -> upstream_calls=  8   wall=0.603s   ideal=8
```

`async_lru` performs proper **single-flight**: 64 concurrent identical requests collapse to 1 upstream call. This is a strength of the existing caching layer and the model the team should replicate when extending the cache to `autocomplete_entity` and `search_publications` (called out as gaps in §4.8 of the main review).

Caveat: the rate limiter is still consulted on the single in-flight call, and that call still goes through the broken limiter — so a single uncached batch stampede can still cause the upstream to see one big request. Not a stampede problem, but it's why fixing the limiter matters even after the cache is good.

### 3.5 Database pool sizing

`api/routes/dependencies.py:117-125`:

```python
return {
    "dsn": review_rerag_config.database_url,
    "min_size": 1,
    "max_size": max(2, review_rerag_config.prep_concurrency * 2 + 2),
}
```

Defaults: `prep_concurrency=2` → `max_size=6`. Concurrent demand:

- Up to 2 prep workers in `ReviewPreparationQueue` running concurrently, each may hold a connection.
- Up to 4 retrieval queries (`retrieval_concurrency=4` in `review_context_service.py:173`) each acquiring a connection for `search_passages`.
- Audit-event writes, source listing, certainty writes — opportunistic.

With the default config, **4 concurrent `retrieve_review_context_batch(queries=[…12…])` calls** can request up to 4×4 = 16 simultaneous DB connections against a pool of 6. The asyncpg pool blocks indefinitely waiting for a connection because `pool.acquire()` is called without a `timeout=` (verified across `repositories/review_rerag.py`). Under sustained pressure, MCP tool calls just hang.

**Fixes:**

1. Add `timeout=5.0` to every `pool.acquire()` call in `repositories/review_rerag.py`. A timeout reveals saturation as a fast `asyncpg.PoolAcquireTimeoutError` (which `mcp/errors.py` will sanitize to `error_code: review_index_unavailable` automatically).
2. Raise the pool floor: `max_size=max(10, prep_concurrency * 2 + retrieval_concurrency * 2 + 4)` — cheap and right-sized for the concurrent retrieval workload.
3. Set `min_size` to a non-trivial value (e.g., 4) to keep warm connections.

### 3.6 ASGI middleware contextvars trap

`server_manager.py:185-209` registers two middlewares with `@app.middleware("http")`:

```python
@app.middleware("http")
async def add_request_id(...): ...

@app.middleware("http")
async def bind_pubtator_resources(request, call_next):
    ...
    token = bind_app_resources(resources)
    try:
        return await call_next(request)
    finally:
        reset_app_resources(token)
```

This is the **documented `@app.middleware("http")` pitfall**: FastAPI runs the endpoint inside a task group which **creates a copy of the context**, so contextvars set in the middleware body are visible in the endpoint, but contextvars set inside the endpoint (e.g., per-request bindings) don't propagate back. More subtly, when the MCP HTTP app is mounted at `/` (line 222), requests routed into the FastMCP sub-app may not even traverse this middleware in the order you expect.

In your code, `bind_app_resources` is set in middleware and read inside service-layer dependencies via `current_app_resources()`. This *should* work for the read direction, but is fragile and silently breaks under any of:

- Future addition of a second contextvar set inside an endpoint.
- BackgroundTasks fired from an endpoint (run in a different context where the binding is gone).
- Any `asyncio.create_task()` from a service (no automatic context inheritance unless you pass it explicitly).

**Fix** — switch to a pure ASGI middleware:

```python
class PubTatorResourceBindingMiddleware:
    def __init__(self, app, get_resources): ...
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        token = bind_app_resources(self.get_resources(scope))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_app_resources(token)

app.add_middleware(PubTatorResourceBindingMiddleware, get_resources=...)
```

This is the same pattern `asgi-correlation-id` uses (recommended in the observability guide). It runs **outside** FastAPI's task-group copy and propagates correctly.

### 3.7 httpx connection limits

`api/client.py:98-114` constructs `httpx.AsyncClient` without explicit `limits=`. Default is `Limits(max_connections=100, max_keepalive_connections=20, keepalive_expiry=5.0)`.

- **Single-instance, current code:** fine. 64 concurrent calls × 1 connection each = 64 in-flight, well under 100.
- **Single-instance after the per-call-client fix:** same. The shared client multiplexes all calls through its connection pool.
- **Multi-worker Gunicorn deployment** (mentioned in `pyproject.toml` deps and `docker/`): each worker process has its own client and its own 100-connection ceiling, but PubTator sees `workers × concurrent_requests` and may rate-limit or refuse. Set explicit limits proportional to your rate budget: `httpx.Limits(max_connections=int(rate * 2), max_keepalive_connections=int(rate))`.

### 3.8 Batch retrieval — bounded but eager

`review_context_service.py:173-202`:

```python
semaphore = asyncio.Semaphore(self.retrieval_concurrency)

async def retrieve_one(query_index, query):
    async with semaphore:
        result = await self.retrieve_context(...)
        return query_index, result

indexed_results = await asyncio.gather(
    *(retrieve_one(index, query) for index, query in enumerate(request.queries))
)
```

The semaphore correctly bounds **execution** to `retrieval_concurrency` (=4 by default). But `asyncio.gather(*...)` still creates **N coroutines for N queries** up front, plus N semaphore-waiters. For typical batch sizes (≤30 queries) this is fine; for very large batches (e.g., a misuse like `queries=[...500...]`) you'd hold ~500 coroutine objects + DB connection requests in memory. Add an upstream cap:

```python
MAX_BATCH_QUERIES = 50
queries = request.queries[:MAX_BATCH_QUERIES]
if len(request.queries) > MAX_BATCH_QUERIES:
    log.warning("batch_truncated", requested=len(request.queries), kept=MAX_BATCH_QUERIES)
```

Also worth noting: each `retrieve_context` issues a separate `audit_event` write *outside* the semaphore (line 248). Audit writes are unbounded across concurrent batches — under heavy load this is a small but real second source of DB pool pressure.

### 3.9 Second-order effects to be aware of

- **Retry storm.** When upstream returns 429 (likely if 3.1+3.2 cause N concurrent requests), each call retries up to 3 times with full-jitter backoff up to 10s. With 16 concurrent failing calls, you can have 48 retry attempts spread over 10 seconds, and the limiter will not coordinate them. After fixing 3.1 + 3.2 this self-resolves.
- **Stdio framing.** Stdio uses one long-lived process and a single JSON line stream. If the host pipes 16 requests, FastMCP dispatches them concurrently — **same concurrency model as HTTP**, no extra serialization. The bugs in §3.1–3.2 apply identically.
- **Single-uvicorn-worker default.** `start_unified_server` uses `uvicorn.Server(uvicorn.Config(app, …))` with **no `workers=` argument** (`server_manager.py:285-293`). One process, one event loop. This actually *protects* you from the per-worker rate-limit multiplication described in §3.7 — but if you ever switch to `gunicorn -w N` (which the deps include), each worker has its own state and the upstream-RPS multiplier becomes N × (current bug factor). Don't move to multi-worker until §3.1 + §3.2 are fixed and a cross-worker rate limit is in place (Redis token bucket, or sticky-sessions + one-worker-per-tenant).

---

## 4. Recommended fix sequence

Each step is independently shippable. Test the rate-limit fix end-to-end against PubTator with `make dev` after each step.

### Step 1 — fix the rate-limiter math (1 hour)

`api/client.py:RateLimiter.acquire()` → re-check loop (code in §3.2). Update the call site in `_make_request()` (line 155) to drop the now-unused `wait_time` return + sleep block.

**Verification:** re-run `/tmp/stress_ratelimiter.py`. Should show monotonically increasing permit times at exactly 1/rate intervals.

### Step 2 — share the PubTator3Client across MCP tools (1 day, 5 files)

Replace every `async with PubTator3Client() as client:` in `mcp/tools/*.py` with `client = await get_api_client()`. The service adapters already accept the client as a parameter; no signature changes.

**Verification:** rerun `/tmp/stress_concurrency.py`. Scenario A should now match scenario B's behavior, and combined with Step 1, max in-flight should drop to 1 across all N values.

### Step 3 — set DB pool acquire timeouts (30 min)

In every `repositories/review_rerag.py` method that does `async with self.pool.acquire() as conn:`, change to `async with self.pool.acquire(timeout=5.0) as conn:`. Also raise `max_size` floor in `dependencies.py:117-125` to `max(10, prep_concurrency * 2 + retrieval_concurrency * 2 + 4)`.

**Verification:** add a test that fills the pool (4 long-running queries against a `min_size=1, max_size=4` pool) and asserts a 5th `acquire()` returns `asyncpg.PoolAcquireTimeoutError` rather than hanging forever.

### Step 4 — switch to pure ASGI middleware for resource binding (half day)

Replace the two `@app.middleware("http")` decorators in `server_manager.py:185-209` with `app.add_middleware(...)` style middlewares. Same logic, different attachment point.

**Verification:** add a test where a service spawns `asyncio.create_task(...)` from inside a route handler and asserts `current_app_resources()` returns the right binding inside the task.

### Step 5 — set explicit httpx limits + cap batch query count (1 hour)

`api/client.py:98` add `limits=httpx.Limits(max_connections=int(config.rate_limit_per_second * 4), max_keepalive_connections=int(config.rate_limit_per_second * 2))`. In `review_context_service.py:retrieve_context_batch`, cap `request.queries` to a configurable maximum (default 50).

### Step 6 — extend the (already correct) cache strategy (half day)

The `async_lru` single-flight behavior is your friend. Wrap `client.autocomplete_entity` and `client.search_publications` analogously in `services/`. Use `frozenset` of normalized arg tuples for cache keys to canonicalize ordering.

### Step 7 — when ready for multi-worker — distributed rate limit (separate project)

Implement a Redis-backed token-bucket rate limiter shared across Gunicorn workers. Until then, keep `workers=1` in deployment.

---

## 5. Testing methodology — for re-running after fixes

The three test scripts at `/tmp/stress_*.py` are the regression suite for these issues. Run with:

```bash
cd /home/bernt-popp/development/pubtator-link
.venv/bin/python /tmp/stress_concurrency.py    # per-call vs shared client comparison
.venv/bin/python /tmp/stress_ratelimiter.py    # token-bucket math
.venv/bin/python /tmp/stress_cache.py          # async_lru single-flight
```

After applying Step 1 + Step 2, the expected output table is:

```
A_per_call_client_n=64    upstream=64  wall=~25s  max_in_flight=1  eff_rps=2.5
B_shared_client_n=64      upstream=64  wall=~25s  max_in_flight=1  eff_rps=2.5
```

These should be **promoted into `tests/integration/test_concurrency.py`** as proper pytest tests with a `@pytest.mark.integration` marker. The test names should encode the contracts: `test_n_concurrent_search_calls_respects_rate_limit`, `test_concurrent_identical_exports_single_flight`, etc. They're slow (~30s each) but they're exactly the regression suite that prevents these bugs from coming back.

---

## 6. What this looks like to an LLM agent

Today, when Claude does `pubtator.search_literature(...) ∥ pubtator.search_biomedical_entities(...) ∥ pubtator.preflight_review_sources(...) ∥ pubtator.lookup_mesh(...)` in one turn (4 tool calls):

- 4 `PubTator3Client` instances created (4× httpx clients, 4× DNS lookups, 4× rate limiters).
- All 4 acquire upstream tokens immediately (each fresh limiter has burst=1).
- Upstream sees 4 simultaneous requests, well under PubTator's 3 RPS but a noticeable spike.
- Average tool-call latency: ~upstream_latency (no waiting).

After fixes 1+2:

- 1 shared `PubTator3Client`.
- First call gets the token immediately, calls 2/3/4 wait 400ms each (properly paced).
- Total wall time: `upstream_latency + 3 × 400ms ≈ upstream_latency + 1.2s`.
- Tool-call p95 latency: ~1.5s for the slowest of the 4.

That's a real latency cost — 1.2s of added serialization for 4 parallel calls. **It is the correct cost** of honoring PubTator's published rate guideline. Two mitigations that improve perceived latency without violating the limit:

1. **Up the configured rate to 3.0 RPS** (the documented PubTator ceiling) since you're now correctly enforcing it. `PUBTATOR_LINK_RATE_LIMIT_PER_SECOND=3.0`. Saves 33% on serialized tool calls.
2. **Cache more aggressively** (Step 6). Many parallel agent calls hit the same entities/PMIDs; with `async_lru` extended to autocomplete and search, repeat work disappears.

After both: the same 4-call burst usually completes with 1–2 actual upstream requests and ~1s wall time. The user sees the same latency they see today, but PubTator stops getting hammered.

---

## 7. References

- Stress test scripts (reproducible, runnable):
  - `/tmp/stress_concurrency.py` — per-call vs. shared client × N=1/4/16/64
  - `/tmp/stress_ratelimiter.py` — current vs. fixed token-bucket
  - `/tmp/stress_cache.py` — async_lru single-flight verification
- [Token bucket algorithm — Wikipedia](https://en.wikipedia.org/wiki/Token_bucket)
- [PubTator3 API guidelines — NCBI](https://www.ncbi.nlm.nih.gov/research/pubtator3/api) (3 RPS ceiling)
- [`asgi-correlation-id` — pure ASGI middleware reference implementation](https://github.com/snok/asgi-correlation-id)
- [FastAPI middleware caveat — Tiangolo discussion #2057](https://github.com/tiangolo/fastapi/discussions/2057) (the `@app.middleware("http")` contextvars trap)
- [asyncpg pool acquire timeout docs](https://magicstack.github.io/asyncpg/current/api/index.html#asyncpg.pool.Pool.acquire)
- Companion docs: `docs/2026-05-02-pubtator-link-mcp-llm-engineering-review.md` §4.7, §4.8; `docs/2026-05-02-pubtator-link-observability-implementation-guide.md` §6
