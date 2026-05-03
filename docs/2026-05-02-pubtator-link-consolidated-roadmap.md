# PubTator-Link Consolidated Roadmap

Date: 2026-05-02

This document consolidates the prior maintainability, competitor, MCP
engineering, LLM-consumer, concurrency, and observability reviews. The source
reviews are archived under `docs/archive/reviews/`.

## Executive Summary

PubTator-Link has completed the original reliability and evidence-grounding
roadmap, plus the 2026-05-02 MCP best-practices cleanup. The current system
already has the hard pieces that differentiate it from raw PubMed/PubTator
wrappers: review-scoped indexing, coverage preflight, resolver attempt
auditing, retry/backoff, bounded concurrency, typed MCP output schemas, stable
citation keys, passage addressability, research-session staging, review-feeding
discovery tools, GRADE-style certainty storage, review audit bundles,
Prometheus metrics, readiness checks, MCP lifecycle logs, compact capability
discovery, tolerant MCP input normalization, and quote-mode review retrieval.

The remaining work is no longer a broad feature rescue. It is a focused
hardening phase:

1. Enforce repository and release controls that are documented but not provably
   active.
2. Close the highest-risk hosted/security gaps: inbound rate limits, request
   size limits, tighter CORS, content-type checks, blocking container scans, and
   action pinning policy.
3. Modernize the remaining MCP protocol surface with resource templates,
   parameterized prompts, cursor pagination, and selected elicitation flows.
4. Finish production observability with traces, alerts, error tracking, and the
   promoted concurrency stress tests.
5. Reduce maintenance risk in the remaining complex internals and generate
   public MCP docs from runtime truth.

The strategic lane remains unchanged: PubTator-Link should be the open,
institution-controllable, PubTator-aware biomedical evidence MCP for research
and review workflows. It should not become a clinical decision-support product,
a broad biomedical command workbench, or a generic reference manager.

## What Is Already Done

These items appeared as gaps in older reviews but are implemented in current
source or documentation:

| Area | Current status | Evidence checked |
| --- | --- | --- |
| CI and local gates | Shipped | `make ci-local`, CI workflow, coverage gate, Docker and security workflows |
| Branch-protection policy docs | Shipped as docs, not externally enforced | `docs/development/branch-protection.md` and JSON policy |
| CLI smoke coverage | Shipped | `tests/unit/test_cli.py` |
| Review batch-budgeting tests | Shipped | source-fair, scarcity-first, response-budget, and diagnostics tests |
| MCP facade/domain split | Shipped | `pubtator_link/mcp/tools/*`, `metadata.py`, `resources.py` |
| Review re-RAG modularization | Shipped | mapper, ranking, packing, diagnostics, batch-budgeting modules |
| Coverage preflight and resolver audit | Shipped | `source_preflight`, source attempts, coverage reasons |
| Retry/backoff and `Retry-After` | Shipped | `pubtator_link/api/retry.py` and client retry path |
| Bounded concurrency and shared client | Shipped | shared `get_api_client()`, fixed token bucket, bounded batch chunks |
| Typed MCP output schemas | Shipped | tool `output_schema=...model_json_schema()` coverage |
| Passage lookup and neighboring passages | Shipped | review MCP tools and tests |
| Review index lifecycle | Shipped | list, summary, TTL cleanup surfaces |
| Scientific auditability | Shipped foundation | audit bundle, audit trail helper, GRADE-style certainty storage |
| Discovery parity | Shipped core | MeSH lookup, citation lookup, article ID conversion, related/cited/reference expansion |
| Research-session staging | Shipped | staged session models, REST/MCP routes, quickstart handoff |
| Search ergonomics | Shipped materially | `entity_ids`, coverage hints, metadata modes, corpus suggestion |
| Observability foundation | Shipped | correlation IDs, `/ready`, `/metrics`, MCP lifecycle logs/metrics |
| Concurrency critical fixes | Shipped | rate limiter, shared client, DB acquire timeout, ASGI middleware, httpx limits |
| Container scan and SBOM | Shipped but non-blocking | Trivy workflow creates artifacts with `exit-code: "0"` |
| Release validation workflow | Shipped validation only | tag workflow builds and validates, but does not publish/sign |
| MCP capability discovery cleanup | Shipped | slim default `get_server_capabilities`, opt-in details, preferred tool-name policy |
| Lean/read-only MCP profiles | Shipped | default lean profile, full compatibility profile, and readonly hosted profile |
| MCP resource templates | Shipped | review, session, passage, audit, LLM-context, and tool-detail resources |
| Runtime MCP tool catalog | Shipped | generated `docs/mcp-tool-catalog.md` from registered tool metadata |
| Durable LLM review context | Shipped foundation | `record_review_context` and `pubtator://reviews/{review_id}/llm-context/latest` |
| Read-only literature discovery | Shipped | `search_literature` defaults to `coverage="none"` with review-index handoff guidance |
| Recent MCP failure diagnostics | Shipped | bounded recent-error recorder and degraded diagnostics for review-tool failures |
| LLM input normalization | Shipped at adapter boundary | query/limit aliases, singleton lists, enum casing, and structured field errors |
| GeneReviews/NBK recovery | Shipped | NBK extraction, lookup recovery hints, and Bookshelf URL rejection before indexing |
| Early review source coverage summary | Shipped as optional repository hook | `index_review_evidence` response summary/message/warnings |
| Batch retrieval compaction | Shipped | passage dedupe with `matched_queries`, collapsed diagnostics, `include_diagnostics=False` default |
| Quote-mode review retrieval | Shipped | `response_mode="quotes"` with bounded citable snippets and no long merged passages |
| Audit export ergonomics | Shipped | field errors, bounded inline JSON fallback, safer exclusive file export |
| Guideline-search clarification | Shipped | `search_guidelines` documented as filtered/boosted `search_literature` wrapper |

## What Is Left

### P0: Controls That Protect `main` And Releases

**1. Enforce branch protection in GitHub.**

The repo has a machine-checkable branch-protection policy, but local files cannot
prove GitHub settings are enabled. GitHub branch protection is the control that
turns CI, Docker validation, CodeQL, and dependency review into merge blockers.

Exit criteria:

- `main` requires pull requests.
- Required checks match `docs/development/branch-protection.json`.
- Stale approvals are dismissed after new commits.
- Branches must be up to date before merge.
- Direct pushes and force pushes are blocked except for explicit maintainers or
  release automation.

**2. Make release security blocking.**

Current Trivy scanning and SBOM generation are useful but advisory. The next
step is to fail on HIGH/CRITICAL findings unless a reviewed exception exists.
For supply-chain hygiene, also decide whether to pin third-party GitHub Actions
to full SHAs and whether release images need signing/provenance.

Exit criteria:

- Container scan fails on configured severity.
- SBOM artifact remains generated for every tagged release.
- Release workflow publishes only after `make ci-local`, Docker config checks,
  container scan, and SBOM generation pass.
- Action pinning policy is documented and tested.
- Image signing or provenance is either implemented or explicitly deferred.

### P0: Hosted Safety And Abuse Resistance

**3. Tighten inbound HTTP controls.**

The upstream PubTator rate limiter protects PubTator, not the public HTTP server.
Hosted MCP deployments still need inbound request limits and narrower HTTP
middleware defaults.

Exit criteria:

- CORS uses explicit methods and headers instead of wildcards.
- HTTP and MCP POST routes have request-size limits.
- Per-IP or per-token rate limiting exists for hosted HTTP mode.
- Rate-limit and request-size failures return stable, documented error codes.
- Defaults remain easy for local stdio and local development.

**4. Harden curated URL and input validation.**

`SafeUrlFetcher` already blocks private addresses, redirects, and oversized
responses. The next step is MIME policy and stricter identifier validation so
hosted instances do not ingest arbitrary content types or injection-shaped IDs.

Exit criteria:

- Curated URL fetch accepts only documented content types.
- Unsupported content type is recorded as a resolver attempt with a stable
  reason.
- MCP and REST entity ID filters validate expected PubTator-style IDs.
- Tests cover PDF/XML/HTML/text accept paths, unsupported MIME, redirect loops,
  and oversize bodies.

**5. Replace string-inferred MCP errors with typed service exceptions.**

`mcp/errors.py` still maps some failures by looking for raw text such as
`updated_at` and imports transport/storage libraries directly. Typed exceptions
would make error codes stable and keep the MCP layer independent from asyncpg or
httpx internals.

Exit criteria:

- Repository/service layers raise typed errors such as
  `ReviewSchemaStaleError`, `ReviewIndexUnavailableError`, and
  `UpstreamUnavailableError`.
- MCP error mapping uses `isinstance`, not raw message substrings.
- Existing error payload shape remains backward compatible.

### P1: MCP Protocol Modernity And Agent UX

**6. Add MCP resource templates.** Shipped foundation; remaining work is richer
not-found/error shaping and any client-specific UX polish.

Parameterized resources now let clients render review summaries, passage
previews, audit blocks, LLM context, and tool docs without rerunning tools.

Recommended templates:

- `pubtator://reviews/{review_id}`
- `pubtator://reviews/{review_id}/passages/{passage_id}`
- `pubtator://capabilities/tools/{tool_name}`

Exit criteria:

- Templates are discoverable from MCP resource listing.
- Parameter validation returns stable not-found and validation errors.
- Resource bodies are compact and research-use scoped.

**7. Add parameterized prompts and success `_meta`.**

Prompts are currently fixed strings. Make them accept arguments such as `topic`,
`year_min`, `entity_ids`, or `review_id`. On successful retrieval and write-like
operations, echo compact `_meta` with budget, snapshot, and idempotency hints.

Exit criteria:

- Prompt templates are argument-aware and tested.
- Retrieval success includes budget/snapshot metadata already present in models
  in an MCP-friendly location.
- Write-like review operations accept or return an idempotency key when useful.

**8. Introduce cursor pagination where result sets can drift.**

Page/offset remains acceptable for stable search pages, but review inventories
and session lists are better served by opaque cursors.

Exit criteria:

- Cursor APIs document the cursor as opaque.
- Existing page/offset callers keep working during migration.
- Cursor tests cover concurrent insert/delete tolerance where practical.

**9. Add narrow elicitation only for ambiguous review mutations.**

MCP elicitation should not be used for secrets. It is useful for a small number
of human-confirmed workflow decisions, such as collision handling when a
`review_id` already has staged sessions.

Exit criteria:

- Elicitation is optional and only used when the client advertises support.
- Non-supporting clients get deterministic fallback behavior.
- Form elicitation never requests credentials or sensitive data.

### P1: Observability That Answers Production Questions

**10. Add OpenTelemetry traces and alerts.**

Logs and Prometheus metrics are present; traces are not. Tracing should cover
route -> MCP tool -> service -> repository -> upstream/DB paths, with low-cardinality
attributes and sampling.

Exit criteria:

- Tracing is opt-in by env var.
- FastAPI, httpx, asyncpg, and key review-service spans are instrumented.
- Background review-preparation jobs preserve trace context when available.
- `/health`, `/ready`, and `/metrics` are excluded from request traces.
- Alert recommendations cover upstream 429 spikes, MCP error rate, p95 latency,
  DB pool saturation, and review queue backlog.

**11. Add error tracking and operational runbook checks.**

Metrics show rates; error tracking groups unique exceptions and stack traces.
This is high leverage for hosted deployments.

Exit criteria:

- Sentry or equivalent error tracking is optional and disabled by default.
- Error events include request ID, tool name, error code, and sanitized context.
- Runbook documents how to diagnose: slow request, schema drift, upstream 429,
  DB pool saturation, and empty review retrieval.

**12. Promote concurrency stress scripts into integration tests.**

The concurrency analysis relied on `/tmp/stress_*.py`. Those contracts should
live in the repo so rate-limit and single-flight behavior do not regress.

Exit criteria:

- Integration tests cover concurrent rate-limit pacing, shared-client behavior,
  and `async_lru` single-flight behavior.
- Slow tests are marked and excluded from the default fast unit suite.
- Expected timing thresholds are tolerant enough for CI variance.

### P1: Runtime Docs And Contract Drift

**13. Generate an MCP tool catalog from runtime registration.** Shipped
foundation; remaining work is adding a CI freshness gate if desired.

The tool surface is large enough that static docs will drift. Generate a compact
catalog from the actual registered MCP tools, schemas, annotations, and resource
groups.

Exit criteria:

- Generated catalog includes name, purpose, core/advanced group, args, output
  schema name, and research-use scope.
- CI fails if generated docs are stale.
- README and MCP connection guide link to the generated catalog.

**14. Add an error-code reference.**

LLM agents branch on `error_code`; humans need the same map.

Exit criteria:

- Every emitted MCP error code has cause, retryability, fallback, and recommended
  next command.
- Tests ensure documented codes match code.

**15. Add lightweight architecture and workflow diagrams.**

The project has many well-separated modules now. A short architecture guide will
lower agent error rates and reduce onboarding cost.

Exit criteria:

- One route -> service -> repository -> external API diagram.
- One review workflow sequence: search -> stage -> index -> inspect -> retrieve
  -> passage lookup -> audit export.
- One hosted deployment diagram showing reverse proxy, app, DB, and metrics.

### P2: Performance And Internal Maintainability

**16. Extend caching to entity autocomplete and expose cache stats.**

Search is cached at the publication-service layer and exports use `async_lru`.
Entity autocomplete remains a likely hot path. Cache stats should be visible in
metrics or diagnostics.

Exit criteria:

- Autocomplete cache has bounded TTL and size.
- Cache key normalization avoids order-sensitive misses.
- Cache hit/miss metrics are low-cardinality.
- Write paths invalidate only relevant review-context caches.

**17. Split full-text preparation when the next functional change lands there.**

`FullTextPreparationService` remains the main large service. Do not split it for
its own sake, but the next resolver change should separate fetching, extraction,
and orchestration.

Exit criteria:

- Fetchers own upstream/source-specific access.
- Extractors own BioC/JATS/PDF/HTML parsing.
- Orchestrator owns source priority and terminal coverage state.
- Existing source-attempt audit behavior stays compatible.

**18. Add more advanced test strategies where they fit.**

Use property-based tests for search-filter merging and snapshot/golden tests for
nested review-context responses. Keep default tests fast.

Exit criteria:

- Property tests cover filter normalization and conflict handling.
- Snapshot tests cover representative compact/diagnostics/full review outputs.
- New tests are stable and deterministic.

### P2: Institutional Packaging And Governance

**19. Package institutional deployment guidance.**

PubTator-Link's best strategic position is an inspectable evidence MCP that an
institution can run inside its own boundary. That needs explicit deployment and
governance docs.

Exit criteria:

- Hosted HTTP deployment guide covers reverse proxy auth, TLS, CORS, rate limits,
  data retention, logs, and backups.
- Clinical-use boundary is explicit: research-use literature infrastructure, not
  diagnosis, treatment, triage, patient management, or patient-specific decision
  support.
- A compliance mapping explains which controls support auditability, privacy,
  and governance without claiming medical-device compliance.

**20. Add registry/install polish only after controls are ready.**

Registry metadata improves discoverability, but publishing a hosted MCP surface
before auth and rate-limit defaults are clear would be premature.

Exit criteria:

- Stdio, HTTP, Docker, and hosted examples are tested.
- Registry description matches actual transports and tool inventory.
- Public descriptions include research-use scope and deployment boundary.

## Prioritized Execution Order

| Order | Work | Priority | Why now |
| ---: | --- | --- | --- |
| 1 | Enforce GitHub branch protection | P0 | Converts existing CI into an actual merge control |
| 2 | Make Trivy blocking and define action pinning/signing policy | P0 | Turns advisory release security into a gate |
| 3 | Tighten CORS, request size, inbound rate limits | P0 | Required before serious hosted HTTP exposure |
| 4 | Add MIME policy and entity-ID validation | P0 | Reduces hosted input risk |
| 5 | Replace string-inferred errors with typed exceptions | P0 | Stabilizes LLM recovery contracts |
| 6 | Add OpenTelemetry traces, alerts, and error tracking | P1 | Completes production diagnosis loop |
| 7 | Promote concurrency stress tests | P1 | Locks in the recently fixed concurrency contracts |
| 8 | Add MCP resource templates and parameterized prompts | P1 | Modernizes the MCP surface with small UX wins |
| 9 | Generate MCP catalog and error-code reference | P1 | Prevents docs/runtime drift |
| 10 | Extend autocomplete cache and cache metrics | P2 | Improves perceived latency without raising upstream load |
| 11 | Split full-text preparation during next resolver change | P2 | Reduces future edit risk without churn |
| 12 | Publish institutional deployment/registry package | P2 | Useful after hosted controls are in place |

## Defer Explicitly

- **Sampling for query rewriting:** useful only if the server begins adaptive
  LLM-assisted reranking. The deterministic backend principle is more important
  right now.
- **Broad OpenAlex/Semantic Scholar/Crossref graph expansion:** valuable later,
  but not until core hosted safety, tracing, and docs drift are handled.
- **Default publisher scraping or PDF crawling:** keep disabled for public hosted
  deployments. Curated user-provided URLs should remain explicit and
  provenance-labeled.
- **Clinical decision-support positioning:** avoid diagnosis/treatment/triage
  claims. Keep the backend deterministic and research-use scoped.
- **A full systematic-review SaaS workflow:** PubTator-Link should export and
  support review workflows, not become Covidence or RevMan.

## Best-Practice References Used

- GitHub branch protection rules define merge requirements such as pull-request
  review, passing status checks, and up-to-date branches:
  <https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches>
- MCP latest stable 2025-11-25 includes newer features such as URL-mode
  elicitation, sampling tool calling, icons metadata, and experimental tasks:
  <https://modelcontextprotocol.info/specification/>
- MCP elicitation supports server-requested user input, but form mode must not
  request secrets; URL mode is intended for sensitive external authorization:
  <https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation>
- MCP sampling can let a server request client-side model calls, but applications
  should keep a human approval path for sampling requests:
  <https://modelcontextprotocol.io/specification/2025-11-25/client/sampling>
- OpenTelemetry FastAPI instrumentation supports route exclusion and request or
  response hooks, which fits excluding `/health`, `/ready`, and `/metrics`:
  <https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html>
- Prometheus Python client docs point to metric-type and instrumentation guidance;
  keep labels low-cardinality:
  <https://prometheus.github.io/client_python/instrumenting/>
- OWASP MCP Top 10 frames MCP-specific risks such as model/context binding,
  context spoofing, prompt-state manipulation, and covert channels:
  <https://owasp.org/www-project-mcp-top-10/>
- OWASP LLM guidance keeps prompt injection, insecure output handling, supply
  chain, excessive agency, and sensitive-data disclosure in scope for LLM apps:
  <https://owasp.org/www-project-top-10-for-large-language-model-applications/>
- NIST supply-chain guidance emphasizes robust CI/CD, vetted components,
  automated scanning, and SSDF-aligned vulnerability management:
  <https://www.nist.gov/document/guidance-supply-chain-security-under-eo-14028-section-4c4d>

## Archive Index

The prior review documents remain available for rationale and historical detail:

- `docs/archive/reviews/2026-04-30-maintainability-ci-cd-llm-development-review.md`
- `docs/archive/reviews/2026-05-01-pubtator-link-competitor-landscape.md`
- `docs/archive/reviews/2026-05-01-pubtator-link-mcp-capability-speed-usability-scientific-review.md`
- `docs/archive/reviews/2026-05-01-pubtator-link-mcp-deep-competitor-analysis.md`
- `docs/archive/reviews/2026-05-02-pubtator-link-mcp-llm-consumer-evaluation.md`
- `docs/archive/reviews/2026-05-02-pubtator-link-mcp-llm-engineering-review.md`
- `docs/archive/reviews/2026-05-02-pubtator-link-mcp-parallel-concurrency-analysis.md`
- `docs/archive/reviews/2026-05-02-pubtator-link-observability-implementation-guide.md`
