# Changelog

## [Unreleased]

## [7.1.1] - 2026-07-15

### Fixed

- **Safe evidence contracts.** Variant evidence now keeps exact/equivalent source
  classifications separate from broad candidate variants; relation endpoints select the
  opposite endpoint; PMC annotations consistently classify missing IDs; and persisted
  research-session lists are compact, cursor-paginated summaries with deterministic
  scope-aware cursors.
- **Profile-reachable workflows.** `readonly` only advertises its direct retrieval chain
  ending in `get_publication_passages`; `lean` and `full` expose only tools available in
  their authenticated profiles. Capability payloads, prompts, persisted review context,
  and diagnostics no longer leak unreachable tool guidance.

### Changed

- Re-vendored the behaviour conformance gate from genefoundry-router `56db958`
  (`docs/conformance/behaviour.py` blob `c69801687`) so live MCP contract checks
  treat not-found example probes as inconclusive and keep empty auxiliary objects
  from hiding counted rows.

## [7.1.0] - 2026-07-15

Edge authentication. Adds an optional Keycloak-OAuth mode so a single `/mcp` can serve both
standalone OAuth users (claude.ai connectors, Claude Code, scripts) and the router — the latter
with its own static service token, never the caller's — both reaching the full writeable tool
surface. The default (`AUTH_MODE=none`) is unchanged and backwards-compatible, so the released
image is safe to publish before Keycloak exists.

### Added

- **`PUBTATOR_LINK_AUTH_MODE=oauth`** — one `/mcp` accepts a Keycloak JWT **or** the router's
  static service token via FastMCP `MultiAuth`. The JWT verifier is audience-bound to the
  resource URI, and Protected-Resource-Metadata is served so the claude.ai OAuth flow completes.
- **Write-scope authorization** — `PUBTATOR_LINK_REQUIRE_WRITE_SCOPE` (default `false` =
  write-for-all-authenticated) gates the authoritative `WRITE_TOOLS` on the `pubtator:write` scope.
- **Deployment** — a commented oauth+full go-live block and a `FASTMCP_HOME` client-store volume
  in the production overlay; `docs/SECURITY.md` documents the model and a Keycloak operator runbook.

### Security

- In `oauth` mode the mutating REST review routes (`/api/reviews/*`) are **not registered**,
  closing an unauthenticated write path to the review database that lives outside the MCP mount.
- Audience binding rejects tokens minted for other backends; `PUBLIC_BASE_URL` is validated as a
  bare origin and `JWT_AUDIENCE` must equal `PUBLIC_BASE_URL + /mcp`, preventing a doubled
  `/mcp/mcp` protected-resource advertisement.

### Changed

- **Conformance gate re-vendored** (`tests/conformance/behaviour.py`, byte-identical to
  genefoundry-router). A `not_found` on a tool's own documented example is now treated as
  inconclusive rather than a failure: `get_research_session_status` is keyed on a runtime-issued
  session handle whose example can never resolve against a fresh deployment, so its honest
  `not_found` (correct, and made cleaner by the 7.0.0 error-egress fix) no longer red-flags the
  server. A malformed example (`invalid_input`) still fails the gate. Test-only; the released image
  is unaffected.
- **The public `/mcp` endpoint is now open for read-only access.** The production
  overlay no longer sets `PUBTATOR_LINK_MCP_SERVICE_TOKEN`, so
  `MCPServiceAuthMiddleware` is not installed and a direct unauthenticated `/mcp`
  request returns `200` instead of `401 {"error":"unauthorized"}`. The endpoint
  serves only read-only public PubTator3 literature data
  (`PUBTATOR_LINK_MCP_PROFILE=readonly`, unauthenticated writes disabled), so a
  service-token gate on the public transport is not warranted. To re-enable bearer
  auth, restore the (now commented) `PUBTATOR_LINK_MCP_SERVICE_TOKEN` line in
  `docker-compose.prod.yml` and supply the token from the secret store. Compose-only
  change; the released image is unaffected.

## [7.0.0] - 2026-07-15

MCP contract hardening (genefoundry-router#126). Adopts the Tool-Surface Budget Standard v1 and
the Tool-Schema Documentation Standard v1, closes the `error_code` enum, and fixes the `isError`
protocol flag. Major because several tool parameters that were advertised as optional but always
required at runtime are now declared required (a call form that previously failed at runtime now
fails at schema validation instead).

### Changed

- **Tool surface cut from ~73,300 tokens to ~13,600 tokens (–81%).** `output_schema=None` on every
  tool suppresses the published response schemas (87% of the old surface; the model never reads
  them and `structuredContent` is unaffected for the dict envelopes every tool returns), and
  `FastMCP(dereference_schemas=False)` stops inlining `$defs`. A new advertised-schema compaction
  pass (`schema_compaction.py`) collapses redundant `anyOf[X, null]` nullable wrappers and strips
  auto-generated `title` noise without touching descriptions, enums, or runtime validation. No
  tool definition exceeds the 1,200-token per-tool ceiling. The whole-server surface remains above
  the 10,000-token target because a fully documented 35-tool surface cannot fit under it without
  splitting tools (out of scope here — it would force a router drift recapture); the Documentation
  Standard takes precedence over the budget in that conflict.
- **Every input property across all 35 tools now carries a `description`** (was 1%); every required
  and array-typed property carries `examples`; every closed vocabulary (search sections, BioC
  passage sections, PubMed publication types, response modes, …) is declared as a `Literal` enum so
  an out-of-vocabulary value is rejected with `invalid_input` instead of silently returning zero
  results.
- **`error_code` is closed to the six-value fleet enum** (`invalid_input`, `not_found`,
  `ambiguous_query`, `upstream_unavailable`, `rate_limited`, `internal`). Internal reasons
  (`validation_failed`, `internal_error`, `review_index_unavailable`, `review_schema_not_current`,
  `curated_url_rejected`, `output_validation_failed`) are projected onto the canon while still
  driving recovery text. A bad argument now answers `invalid_input` (never `not_found`) and names
  the accepted parameters.

### Fixed

- **Error envelopes now set the MCP `isError: true` flag.** Every `success: false` envelope is
  returned as `ToolResult(is_error=True, …)` so a client branching on `isError` sees the failure
  and surfaces it to the model, while keeping the structured envelope. A returned dict alone left
  `isError` false, so failures read as successful calls.
- **Silently-empty filters closed.** `search_literature` / `search_guidelines` `sections` and
  `publication_types`, and `get_publication_passages` / `estimate_publication_context` `sections`,
  matched nothing (with `success: true`) for a mis-cased or unknown value; the declared enums now
  reject it.

### Fixed (re-review round)

- **No advertised call form is uncallable.** The now-redundant alias parameters (`query`/`text`
  synonyms, singular `pmid`, citation-graph `doi`/`query`, topic-map `topic`/`question`/`seed_pmids`)
  are **removed** rather than left in the schema as documented-but-uncallable alternatives. Pass the
  canonical primary parameter; a single PMID goes in the `pmids` list.
- **Silently-empty filter, closed at the class level.** The advanced `filters` JSON `type` is now
  validated against the same publication-type vocabulary as the flat `publication_types` enum, so
  `{"type":["review"]}` is rejected as `invalid_input` instead of bypassing the enum and returning
  an empty success. `find_entity_relations.relation_type`/`target_entity_type` and
  `get_server_capabilities.details` are now declared enums (subset of the runtime vocabulary).
- **Error canonicalization at the egress.** A tool error raised *outside* `run_mcp_tool` (and the
  tool-storage layout a fresh server uses) previously reached the wire as `isError:true` with
  `structuredContent:null`; the handler now wraps tools from both FastMCP registries and re-shapes
  any raised error into a flat envelope with a six-value `error_code` (original under
  `error_subtype`). `text_annotation_degraded` and the audit-export path now carry a canonical
  top-level `error_code`.
- **Honest filtered pagination.** A PMID-filtered `inspect_review_index` computed remaining counts
  and the next cursor from GLOBAL totals — over-reporting remaining and repeating cursors after an
  empty filtered page (a loop). It is now bounded by page fullness under a filter, with remaining
  reported as unknown rather than a global number.
- **Honest fallback totals.** The local single-page search fallback no longer overwrites `total`
  with one page's match count and `total_pages` with 1; it reports a lower bound plus `has_more` so
  the client is never falsely told retrieval is complete.

### Migration

- `search_literature.text`, `search_guidelines.text`, `search_biomedical_entities.query`,
  `get_mesh.query`, `suggest_corpus.question`, `build_topic_literature_map.query`,
  `get_publication_passages.pmids`, `get_publication_metadata.pmids`,
  `get_publication_annotations.pmids`, `estimate_publication_context.pmids`,
  `find_related_articles.pmids`, `preflight_review_sources.pmids`,
  `get_publication_citation_graph.pmid`, `get_variant_evidence.variant`, and
  `get_review_context.question`/`get_review_context_batch.queries` are now **required** (they were
  always required at runtime), and the redundant singular/synonym alias parameters have been
  **removed**. Resolve a DOI or free-text to a PMID first (`convert_article_ids` / `search_literature`)
  for `get_publication_citation_graph`.
- Section filters on `get_publication_passages` / `estimate_publication_context` now accept the
  canonical uppercase BioC labels; publication-type and search-section filters accept the declared
  case-sensitive vocabularies.

### Conformance

- Behaviour Conformance v1 gate vendored (`tests/conformance/behaviour.py`,
  `test_behaviour_v1.py`) and wired into `conformance.yml`. Against a locally-running server:
  **CONFORMANT — 257 pass, 0 fail, 0 UNGATED** (29 inconclusive: review re-RAG tools skipped with
  no database). A regression test pins the tool surface under budget.

## [6.1.6] - 2026-07-14

### Fixed

- **The NPM deployment would have lost its public hostname on the next deploy.**
  `docker-compose.prod.yml` sets `container_name: !reset null` on both
  `pubtator-link` and `pubtator-postgres`. That is correct for the standalone
  production stack it targets, but the deployed chain is
  `docker-compose.yml -f docker-compose.prod.yml -f docker-compose.npm.yml`, and
  Nginx Proxy Manager forwards to a **container name** on the shared network — the
  live proxy host emits `proxy_pass http://pubtator_link_server:8000;`. With the name
  reset, Compose would have named the container `pubtator-link-pubtator-link-1`, NPM
  could not have resolved it, and `pubtator-link.genefoundry.org` would have started
  returning 502 the moment the server pulled this compose. The NPM overlay now
  restores `container_name` (`pubtator_link_server`, `pubtator_link_postgres`) for the
  topology that depends on it. `docker-compose.prod.yml` is untouched.

## [6.1.5] - 2026-07-13

### Fixed

- Release evidence now states the data contract this repository actually
  declares. The reusable release workflow hardcoded `--contract
  data-independent` and `data_requirements: {"mode":"none"}`, so the signed
  release manifest claimed the image binds to no data while
  `container-release.json` declares `data-bound` with a pinned
  `restored-database` corpus. Re-pinned the container CI and release callers to
  the corrected standard revision
  (`86b11f7ed062ed84dfddcbd309e34da88f3dae5b`), which reads the contract and the
  data identity from `container-release.json`.
- This also activates `_require_data_binding`, which previously returned early
  for a `data-independent` contract. The release now asserts that the captured
  data identity equals the pinned `data.release_tag` and `data.digest` instead
  of silently skipping the strongest assertion in the evidence chain.

## [6.1.4] - 2026-07-13

### Changed

- Adopt the GeneFoundry router container-release standard: SHA-pinned reusable
  container CI/release callers, digest-only production image configuration,
  code-only Docker context controls, and complete OCI image labels.
- Declare the `pubtator-postgres` pgvector sidecar as a `database`-role auxiliary
  service in `container-release.json` and harden it to the central Compose policy
  (digest-pinned untagged image, `read_only`, `cap_drop: ALL`,
  `no-new-privileges`, bounded `deploy` limits and logging, named-volume writable
  storage, no published ports).
- Production now runs the image's own Gunicorn default command instead of a
  Compose `command:` override.

## 6.1.3

### Changed

- Consolidated dependency maintenance (supersedes Dependabot #112-#118):
  - `fastapi` 0.136.1 -> 0.139.0 (floor raised to `>=0.139.0`).
  - `uvicorn[standard]` 0.48.0 -> 0.51.0 (floor raised to `>=0.51.0`).
  - `sentence-transformers` 5.5.1 -> 5.6.0 (optional `embeddings` extra).
  - `mypy` 2.1.0 -> 2.3.0 (floor raised to `>=2.2.0`; latest compatible locked).
  - `ruff` 0.15.18 -> 0.15.21.
  - `astral-sh/setup-uv` 8.3.0 -> 8.3.2 (SHA-pinned) across the CI, Docker,
    release, and conformance workflows.
  - `pgvector/pgvector` Compose image 0.8.4-pg18-trixie -> 0.8.5-pg18-trixie,
    re-pinned to the new multi-arch index digest.


## 6.1.2

### Security

- Defense in depth: guard the FastMCP-core not-found reflection surface. Core
  echoed the caller's own requested tool name / resource URI / prompt name (with
  any control/zero-width/bidi/NUL code points) back to the caller and into logs
  before backend middleware ran. A layered guard (registry preflight, resource
  boundary, protocol-handler backstop, and a validation-log scrub filter) now
  answers unknown tools/resources/prompts with fixed, input-free messages and
  neutralizes the framework log records at their source loggers and FastMCP's own
  handlers. Caller self-reflection surface; research use only.

## 6.1.1

### Security

- Defense in depth: the MCP error path no longer echoes upstream API error-body
  text or exception detail into caller-visible messages/partial-success
  rows/validation frames/resources (fixed typed classifications), caller-visible
  strings are sanitized of control/zero-width/bidi/NUL code points, hostile
  review identifiers are rejected without echo, and raw exception text is kept
  out of logs. Research use only.

## 6.1.0

### Security

- Re-enabled FastMCP 3.4.4 strict Host/Origin protection (additive;
  service-token write-boundary + public /health preserved).

## 6.0.0

### BREAKING

- Passage-bearing MCP tool fields now return structured `untrusted_text_v1`
  envelopes instead of raw strings. The envelopes preserve the original
  Unicode passage body while structurally fencing it from model instructions,
  escaping delimiter-like code points, and attaching source provenance. REST
  and service-layer passage contracts remain unchanged.

## 5.0.0

### BREAKING

- The default and hosted MCP profile is now `readonly`. The canonical eight state-changing
  review, annotation, indexing, and export tools are excluded from the public catalog.
- `export_review_audit_bundle` no longer accepts a caller-selected filesystem path. Callers use
  `save_to_file`; deployments must configure an export base directory, and the server creates a
  private generated JSON file beneath it.

### Security

- Require a router-owned Bearer credential on the effective MCP path while leaving `/health`
  available to infrastructure probes. Non-loopback write-profile binds fail startup without a
  service token; CLI and Gunicorn use the same validated bind settings.
- Create audit exports with exclusive no-follow semantics and mode `0600`, preventing symlink,
  overwrite, and caller-path races.
- Production and NPM Compose require the service token, explicitly select the read-only profile,
  and expose the application only behind the proxy.
- Upgrade Soup Sieve from 2.8.3 to 2.8.4, fixing HIGH-severity denial-of-service vulnerabilities
  CVE-2026-49476 and CVE-2026-49477.

## 4.0.4

### Changed

- **Release reconciliation.** Merges the consolidated Dependabot dependency
  sweep (previously tagged `4.0.2` on `origin/main`) into the security
  log-hardening release line (`4.0.2`–`4.0.3`). Both lineages had independently
  published a `4.0.2`; the version is bumped to `4.0.4` to strictly supersede
  both. The Dependabot dependency bumps (`structlog`, `numpy`, `fastmcp`,
  `orjson`, `typer`) and the `errors.py` fastmcp-3.4.3 `ValidationError` handling
  they carried are retained alongside all `4.0.2`/`4.0.3` security fixes. No new
  functional source changes beyond the merge.

## 4.0.3

### Security

- **No free-text query or raw exceptions in REST/service logs.** Several
  REST-route and service log sites rendered the free-text search query (GDPR
  Art. 9 — it can carry variant coordinates, phenotype text, or patient
  identifiers) and raw exception strings (which can carry a Postgres DSN,
  host/IP, or the query echoed back by an upstream error) into logs, despite
  the sanitized response returned to the caller. This completes the 4.0.2
  `mcp_tool_error` fix, which had scoped these pre-existing sites out.
  - `publication_service.search_publications` no longer logs `query=text` or
    `error=str(e)` (it logs `query_length` + `error_type` instead) and no longer
    embeds the raw query in the cache-miss log `cache_key`.
  - The PMC-export failure log now emits `error_type` rather than `error=str(e)`.
  - `handle_api_errors` (`dependencies/validation.py`), `annotations.py`,
    `cache.py`, and `dependencies/review.py` now log `error_type=type(e).__name__`
    instead of interpolating the raw exception string.
  - A sentinel regression guard asserts the query term and its echoed exception
    string are absent from all emitted log values.

## 4.0.2

### Security

- **No raw exceptions in MCP failure logs.** `mcp_tool_error`
  (`pubtator_link/mcp/errors.py`) no longer passes `exc_info` when logging a
  tool failure. The exception message and traceback could carry a Postgres
  DSN, credentials, host/IP, or free-text PII into logs despite the sanitized
  in-band envelope. The failure log now emits only the sanitized `error_code`
  and `exception_type` fields, matching `run_mcp_tool`.
- **CORS credentials disabled on the unauthenticated edge.** The CORS
  middleware now sets `allow_credentials=False` (this backend uses application
  session IDs, not CORS browser credentials) with a fail-closed startup guard
  rejecting the `allow_credentials=True` + wildcard-origin pair.

### Changed

- **Consolidated Dependabot dependency sweep.** Bumped `structlog`
  (`>=24.4.0,<26.0.0` → `>=26.1.0,<27.0.0`, major), `numpy`
  (`>=2.4.6,<3.0.0` → `>=2.5.1,<3.0.0`, major), `fastmcp` (3.4.2 → 3.4.3),
  `orjson` (3.11.8 → 3.11.9), and `typer` (0.26.7 → 0.26.8). CI `astral-sh/setup-uv`
  pinned 8.2.0 → 8.3.0 and the `pgvector/pgvector` Compose image bumped
  `0.8.3-pg18-trixie` → `0.8.4-pg18-trixie`. No source changes were required for the
  major bumps (structlog CalVer, numpy `asarray` usage unaffected).

## 4.0.1

### Fixed

- **MCP `serverInfo.version` now advertises the package version** instead of the
  FastMCP framework version. `create_pubtator_mcp()` passes `version=__version__`
  to `FastMCP(...)`, so the `initialize` handshake reports `pubtator-link`'s own
  version (matching `/health`) rather than the bundled `fastmcp` release.

### Changed

- **Single-source versioning.** `pubtator_link.__version__` now derives from the
  installed package metadata (`importlib.metadata.version("pubtator-link")`)
  rather than a hardcoded literal. `pyproject.toml [project].version` is the sole
  source of truth.

## 4.0.0

### BREAKING: GeneFoundry Response-Envelope Standard v1 (flat banner)

`run_mcp_tool` (`pubtator_link/mcp/errors.py`) no longer raises
`fastmcp.exceptions.ToolError` on execution or argument-validation failure.
Every MCP tool now returns a flat `success: false` envelope **in-band**
instead — `{success, error_code, message, retryable, fallback_tool,
fallback_args, recovery_action, _meta{tool, next_commands,
unsafe_for_clinical_use}}` — and the wire-level MCP `isError` flag is still
set to `true` (via `ToolResult(is_error=True, structured_content=...)`,
verified against the installed `fastmcp==3.4.2`), so clients keep seeing a
protocol-level error while also getting a structured, parseable payload
instead of a JSON string buried in the error text.

- **`recovery` renamed to `recovery_action`** on every error envelope.
- **`_meta.tool` added** to both success and error envelopes (previously
  error envelopes only carried `_meta.next_commands` /
  `_meta.unsafe_for_clinical_use`; success envelopes carried no `_meta` at
  all unless the tool body set its own).
- **Success envelopes now always carry `_meta.unsafe_for_clinical_use` and
  `_meta.tool`**, backfilled by `run_mcp_tool` if the tool body did not
  already set them; existing payload keys (e.g. `results`/`result`,
  `next_commands`) are preserved, never dropped or replaced.
- Any tool caller that used `pytest.raises(ToolError)` /
  `json.loads(str(exc))` against this server's tools must instead inspect
  the returned `ToolResult.is_error` / `structured_content`, or (over MCP)
  the response's `isError` flag and `structuredContent` body.

No deprecation shims — pre-alpha, MAJOR bump.

## 3.0.1

- **Container & Deployment Hardening Standard v1**: pin the base image by digest
  (`python:3.14-slim@sha256:b877e50…`) for byte-reproducible builds (closes #86).

## 3.0.0

### BREAKING: GeneFoundry Logging & CLI Standard v1 (closes #58)

The command-line interface migrated from `argparse` to a single **typer** app
with **rich** output, and the server is now **Streamable HTTP only**.

- **CLI is now `typer`.** `pubtator_link/cli.py` exposes one
  `Typer(name="pubtator-link", no_args_is_help=True)` app with the standard
  commands: `serve`, `config [--validate]`, `health [--url]`, and `version`.
  `serve` accepts `--transport {unified,http}` (default `unified`),
  `--host`, `--port`, `--mcp-path`, `--log-level`, `--disable-docs`, and
  `--dev`. There is no bare-serve.
- **Single console script.** `[project.scripts]` is now
  `pubtator-link = "pubtator_link.cli:app"`. The `pubtator-link-mcp` console
  script and the root `server.py` / `mcp_server.py` entrypoints have been
  **removed**.
- **stdio removed.** The `stdio` transport, the `pubtator-link-mcp` entrypoint,
  `UnifiedServerManager.start_stdio_server`, and the stdio branches in
  `logging_config.py` / `config.py` are gone. The server speaks Streamable HTTP
  only — MCP at `/mcp`, health at `/health` (both unchanged). The removed CLI
  subcommands `test` / `entities` / `search` / `export` are not part of the
  standard surface; the `python -m pubtator_link.benchmarks` path is unaffected.
- **structlog logging confirmed on the canon.** `logging_config.py` now uses the
  canonical processor chain
  (`merge_contextvars → add_log_level → TimeStamper(iso) → StackInfoRenderer →
  set_exc_info → static fields`) with JSON (prod) / Console (dev) renderers and
  static `service`/`version` fields; the `asgi-correlation-id` request id is
  surfaced via `merge_contextvars`.
- **Docker / compose / Makefile / README** boot via `pubtator-link serve …`. The
  default image command and the base Compose stack use the typer CLI; the
  hardened production / NPM overlays keep their multi-worker Gunicorn entrypoint
  (`pubtator_link.server_manager:create_app()`), which is unaffected.

The MCP tool surface, services, and the `/health` / `/mcp` endpoints are
unchanged, so the `genefoundry-router` gateway is unaffected. No deprecation
shims — pre-alpha, MAJOR bump.

## 2.0.0

### BREAKING: GeneFoundry Tool-Naming Standard v1 (closes #57)

Every MCP tool name has dropped its redundant `pubtator_` self-prefix. Namespacing
is the gateway's job: the `genefoundry-router` mounts this server with
`mount(namespace="pubtator")`, so tools surface at the gateway as `pubtator_<tool>`,
and standalone MCP clients already namespace them as `mcp__pubtator-link__<tool>`.
The leaf-level prefix was redundant and caused double-prefixing
(`pubtator_pubtator_search_literature`) at the gateway.

There are **no deprecation aliases** — the old prefixed names are removed
immediately. Update every call site, allowlist, and prompt to the new names. The
canonical gateway **namespace token** for this server is `pubtator`.

In addition to the prefix drop, the direct verb synonyms `lookup`/`fetch`/`retrieve`
were normalized to the canonical verb `get`. Genuinely non-CRUD action /
orchestration / meta tools (`build`/`convert`/`estimate`/`export`/`index`/`inspect`/
`submit`/`add`/`record`/`preflight`/`stage`/`suggest`/`ground` plus
`review_quickstart`/`workflow_help`/`diagnostics`) keep their verbs; harmonizing
those is deferred to a fleet-level decision.

#### Tool rename map (old → new)

| Old name | New name |
| --- | --- |
| `pubtator_search_literature` | `search_literature` |
| `pubtator_search_guidelines` | `search_guidelines` |
| `pubtator_search_biomedical_entities` | `search_biomedical_entities` |
| `pubtator_find_entity_relations` | `find_entity_relations` |
| `pubtator_find_related_articles` | `find_related_articles` |
| `pubtator_find_related_evidence_candidates` | `find_related_evidence_candidates` |
| `pubtator_lookup_variant_evidence` | `get_variant_evidence` |
| `pubtator_lookup_citation` | `get_citation` |
| `pubtator_lookup_mesh` | `get_mesh` |
| `pubtator_fetch_publication_annotations` | `get_publication_annotations` |
| `pubtator_fetch_pmc_annotations` | `get_pmc_annotations` |
| `pubtator_get_publication_passages` | `get_publication_passages` |
| `pubtator_get_publication_metadata` | `get_publication_metadata` |
| `pubtator_get_publication_citation_graph` | `get_publication_citation_graph` |
| `pubtator_get_text_annotation_results` | `get_text_annotation_results` |
| `pubtator_get_server_capabilities` | `get_server_capabilities` |
| `pubtator_get_review_passages_by_id` | `get_review_passages_by_id` |
| `pubtator_get_review_audit_trail` | `get_review_audit_trail` |
| `pubtator_get_review_index_summary` | `get_review_index_summary` |
| `pubtator_get_neighboring_review_passages` | `get_neighboring_review_passages` |
| `pubtator_get_evidence_certainty` | `get_evidence_certainty` |
| `pubtator_get_research_session_status` | `get_research_session_status` |
| `pubtator_list_review_indexes` | `list_review_indexes` |
| `pubtator_list_evidence_certainty` | `list_evidence_certainty` |
| `pubtator_list_research_sessions` | `list_research_sessions` |
| `pubtator_build_topic_literature_map` | `build_topic_literature_map` |
| `pubtator_convert_article_ids` | `convert_article_ids` |
| `pubtator_estimate_publication_context` | `estimate_publication_context` |
| `pubtator_export_review_audit_bundle` | `export_review_audit_bundle` |
| `pubtator_index_review_evidence` | `index_review_evidence` |
| `pubtator_inspect_review_index` | `inspect_review_index` |
| `pubtator_submit_text_annotation` | `submit_text_annotation` |
| `pubtator_add_evidence_certainty` | `add_evidence_certainty` |
| `pubtator_record_review_context` | `record_review_context` |
| `pubtator_retrieve_review_context` | `get_review_context` |
| `pubtator_retrieve_review_context_batch` | `get_review_context_batch` |
| `pubtator_preflight_review_sources` | `preflight_review_sources` |
| `pubtator_stage_research_session` | `stage_research_session` |
| `pubtator_suggest_corpus` | `suggest_corpus` |
| `pubtator_ground_question` | `ground_question` |
| `pubtator_review_quickstart` | `review_quickstart` |
| `pubtator_workflow_help` | `workflow_help` |
| `pubtator_diagnostics` | `diagnostics` |

### Other changes

- Documented the canonical gateway namespace token (`pubtator`) and the Tool-Naming
  Standard v1 in the README.
- Added a CI guard (`tests/unit/test_tool_names.py`) asserting every registered tool
  name matches `^[a-z0-9_]{1,50}$`, never self-prefixes the `pubtator` namespace, and
  (outside the documented action/meta exemptions) starts with a canonical verb.
- Fixed profile-scoped capability filtering to recognize unprefixed tool names so
  full-only tools are no longer advertised under the `lean`/`readonly` profiles.

## Unreleased

- Disabled cache management endpoints by default and made cache clear semantics
  honest: full clears report actual entries cleared, while scoped pattern clears
  now return HTTP 400.
- Removed the unused broken `PublicationService.batch_export_publications()`
  helper.
- Added PubTator export retry metadata sidecars for review preparation audit
  rows without shared mutable client state.
- Corrected MCP review write annotations so append/create tools are marked
  non-idempotent and deduplicated indexing tools remain idempotent.
- Changed review preparation workers to atomically claim queued jobs in a short
  database transaction before running upstream fetch, parser, and embedding work.
- Documented MCP search metadata mapping for flat `publication_types`, `year_min`, and
  `year_max` arguments.
- Clarified that `source_fair` and `scarcity_first` are opt-in review retrieval budget
  strategies while `query_fair` remains the default.
- Documented stable citation keys and maps for durable downstream references.
- Added lifecycle guidance for repeated `index_review_evidence` calls and prompt-injection
  handling for retrieved article text.
