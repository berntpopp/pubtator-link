# Changelog

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
