# MCP Modernization Foundation Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-03

## Purpose

Modernize PubTator-Link's MCP surface so LLM clients spend fewer tokens choosing
tools, preserve review state across sessions, and use parallel retrieval paths
without losing citation-grade auditability.

The target is the first stable foundation slice from the MCP LLM speed,
discoverability, and accuracy report:

- Workstream 1: lean MCP profile and generated catalog.
- Workstream 2: parameterized review-state resource templates.
- Workstream 3: durable LLM review context.

This design intentionally includes cleanup as a deliverable. The implementation
must not introduce `v2` tool names, duplicate workflow APIs, hidden dead
branches, or a central god object that owns all MCP behavior.

## Goals

- Default MCP initialization exposes a lean tool surface suited to normal LLM
  review work.
- Full and readonly profiles remain available for advanced clients and hosted
  deployments.
- Tool descriptions are short, non-overlapping, and generated into a catalog
  that cannot drift from runtime registration.
- Review/session/passage/audit state can be loaded as resources instead of
  action-shaped tool calls.
- LLM working state is durable, structured, append-only, and review-scoped.
- Batch retrieval becomes easier to drive efficiently by returning resource links
  and context options instead of forcing manual follow-up discovery.
- Parallel implementation is possible through independent catalog/profile,
  resource, context persistence, and retrieval-efficiency tasks.

## Non-Goals

- No hosted OAuth implementation in this slice.
- No semantic vector database or embedding pipeline in this slice.
- No local-file ingest or roots support.
- No broad one-call workflow orchestrator.
- No destructive review cleanup tools in the lean or readonly profiles.
- No generic transcript memory. The LLM context is structured review state, not
  chat history.

## Architecture

Keep domain ownership in the existing MCP modules while adding small support
modules with clear boundaries:

- `pubtator_link/mcp/catalog.py`: lightweight metadata and runtime catalog
  extraction for each MCP tool and resource, including category, profile
  membership, stability, example, output schema presence, and next-action hints.
  This module does not register tools.
- `pubtator_link/mcp/profiles.py`: profile enum and small helpers for deciding
  whether a tool should be registered for `lean`, `full`, or `readonly`.
- `pubtator_link/mcp/review_resources.py`: parameterized review resources and
  resource-template helpers.
- `pubtator_link/services/llm_review_context.py`: service for append-only context
  events and current-context projection.
- Existing `pubtator_link/mcp/tools/*.py`: continue to own domain tool
  registration. Each registration is guarded by profile metadata instead of
  moving every tool into one central registry.

The facade becomes profile-aware:

- `lean`: default. Exposes the small LLM-facing workflow surface.
- `full`: exposes all non-hidden compatibility and advanced tools.
- `readonly`: exposes only read-only research tools and resources.

The default profile should come from `PUBTATOR_LINK_MCP_PROFILE`, defaulting to
`lean`.

## Lean Tool Surface

Lean should include only tools that materially advance common biomedical search,
grounding, and review workflows:

- `pubtator.workflow_help`
- `pubtator.diagnostics`
- `pubtator.search_literature`
- `pubtator.search_guidelines`
- `pubtator.search_biomedical_entities`
- `pubtator.lookup_variant_evidence`
- `pubtator.get_publication_metadata`
- `pubtator.get_publication_passages`
- `pubtator.preflight_review_sources`
- `pubtator.index_review_evidence`
- `pubtator.inspect_review_index`
- `pubtator.retrieve_review_context_batch`
- `pubtator.get_review_audit_trail`
- `pubtator.get_server_capabilities`
- `pubtator.record_review_context`

`pubtator.record_review_context` is included because durable LLM state is part of
the default workflow. It is write-like but append-only, non-destructive, and
review-scoped. It must be excluded from `readonly`.

Tools kept out of lean are not bad tools. They are advanced, compatibility, raw
export, or resource-first operations. Examples include
`retrieve_review_context`, `get_review_passages_by_id`,
`get_neighboring_review_passages`, `list_review_indexes`,
`get_research_session_status`, text annotation tools, relation lookup, audit
bundle export, and evidence certainty management.

`retrieve_review_context` remains in `full` as a compatibility wrapper around
`retrieve_review_context_batch` with one query. Documentation and workflow
guidance should point to batch retrieval only.

## Tool Catalog And Token Efficiency

The catalog should be generated from runtime registration plus small supplemental
metadata. Decorators remain the source of truth for tool parameters, title,
description, annotations, and output schema. Supplemental catalog metadata adds
profile/category/example fields that decorators do not carry cleanly.

Each generated tool entry must include:

- `name`
- `title`
- `category`
- `profiles`
- `stability`: `lean`, `advanced`, `compat`, or `admin`
- `annotations`: read/write/export/destructive summary
- `description`
- `do_not_use_for`
- `example`
- `next_tools`
- `resource_links`
- `output_schema_name`
- `has_output_schema`

Description rubric:

- Start with "Use this when..."
- Include "Do not use this for..." when another tool/resource is preferred.
- State required predecessor when one exists.
- State expected next tool or resource.
- Keep examples to one or two lines.

`docs/mcp-tool-catalog.md` is generated from runtime registration. CI fails when
the generated catalog is stale. `get_capabilities_resource()` should consume the
same catalog data instead of maintaining a parallel hand-written tool list.

Token efficiency comes from three constraints:

- Lean profile reduces `tools/list` size.
- Capabilities resource returns compact catalog summaries by default and only
  includes schemas when explicitly requested.
- Resource links replace status/passage/audit follow-up tool descriptions in
  the common path.

## Resource Templates

Add parameterized resources:

- `pubtator://reviews/{review_id}`
- `pubtator://reviews/{review_id}/sessions`
- `pubtator://reviews/{review_id}/sessions/{session_id}`
- `pubtator://reviews/{review_id}/passages/{passage_id}`
- `pubtator://reviews/{review_id}/audit`
- `pubtator://reviews/{review_id}/audit/{passage_id}`
- `pubtator://reviews/{review_id}/llm-context`
- `pubtator://reviews/{review_id}/llm-context/latest`
- `pubtator://capabilities/tools/{tool_name}`

Resource reads must be compact, typed, and bounded. They should not call
upstream PubTator APIs. They read local review state, prepared passages, audit
events, and catalog metadata.

The review and session resources should include:

- `review_id`
- `session_id` when scoped
- preparation status
- source counts
- coverage summary
- indexed PMID counts
- failed source counts
- links to sessions, context, and capabilities resources

The passage resource should include one stable passage by ID, citation key,
PMID/source ID, section, coverage tier, quote offsets when available, and nearby
context links.

The audit resource without a passage ID should return a compact audit summary,
not the full export bundle. The passage-specific audit resource should include
compact audit data for one passage ID. Bulk audit export remains a full-profile
tool.

FastMCP's installed resource template support should be used directly with
parameterized `@mcp.resource(".../{param}")` registration. Resource subscriptions
are deferred in this slice because the installed MCP SDK advertises
`subscribe=False`; do not patch the low-level SDK unless a later implementation
plan explicitly accepts that maintenance cost. `resources/list_changed` can be
used where FastMCP exposes a clean send path.

## Durable LLM Review Context

Add durable, review-scoped LLM context using compact snapshots plus append-only
events. Existing `review_audit_events` remains the scientific audit log; LLM
context is separate because it has replay/resume semantics and token-budget
metadata.

Tables:

- `review_llm_context`
- `review_llm_context_events`

Context fields:

- `context_id`
- `review_id`
- `session_id`
- `kind`
- `topic`
- `research_question`
- `question_hash`
- `request`
- `response_summary`
- `selected_pmids`
- `rejected_pmids`
- `preferred_entity_ids`
- `active_queries`
- `successful_queries`
- `failed_queries`
- `selected_passage_ids`
- `audit_passage_ids`
- `open_questions`
- `user_decisions`
- `last_next_commands`
- `stable_citation_keys`
- `cache_key`
- `token_estimate`
- `created_by`
- `created_at`
- `updated_at`

Event types:

- `context_created`
- `session_selected`
- `pmids_selected`
- `pmids_rejected`
- `query_succeeded`
- `query_failed`
- `passage_selected`
- `audit_passage_selected`
- `question_opened`
- `decision_recorded`
- `next_commands_recorded`
- `context_summarized`

Public MCP surface:

- Resource: `pubtator://reviews/{review_id}/llm-context`
- Tool: `pubtator.record_review_context`

`record_review_context` is append-only. It does not edit or delete old events.
It validates event type, review ID, optional session ID, PMIDs, passage IDs, and
bounded summary fields. It stores passage IDs and compact summaries by default,
not large article text. Passage text is rehydrated through passage resources.

## Parallelism And Latency Efficiency

The implementation should distinguish two forms of parallelism:

- Agent/development parallelism: independent tasks can be implemented by
  separate workers when write sets do not overlap.
- Runtime parallelism: batch retrieval should keep bounded concurrent query
  searches while avoiding repeated shared reads.

Runtime retrieval cleanup:

- `retrieve_context_batch()` should read shared preparation status, prepared
  PMIDs, failed PMIDs, indexed PMIDs, and available sections once per batch.
- It should use a bounded retrieval snapshot object for session existence,
  preparation status, source summaries, failed sources, indexed PMIDs, sections,
  and coverage maps when needed.
- Single-query retrieval can still call the existing single path.
- Batch retrieval should pass shared state into per-query assembly to avoid
  duplicate repository reads.
- Retrieval responses should expose `coverage_summary` and
  `next_context_options`, including resource links for neighboring passages and
  exact passage reads.

This should not become an unbounded async fanout. Existing retrieval concurrency
limits remain in force.

## Error Handling

Tool failures should use structured error content with typed codes and MCP
`isError` behavior where FastMCP supports it.

Resource reads should distinguish:

- `invalid_uri`
- `not_found`
- `not_ready`
- `forbidden`
- `internal_error`

Readonly profile should exclude write-like tools at registration time. It should
not register tools and then reject them at call time.

## Cleanup Requirements

This slice must clean up while building:

- Close all eight known missing `output_schema` registrations.
- Add output schema coverage for `pubtator.get_server_capabilities` if it is
  still schema-less when the catalog work starts.
- Remove stale docs that mention historical `_v2` names as active guidance.
- Hide compatibility tools from lean.
- Keep compatibility tools only in `full` and mark them `compat` in the catalog.
- Do not add new duplicate tools for resource reads.
- Do not add a generic memory delete/edit API.
- Do not move all registration into one large registry.
- Do not add unrelated refactors outside the files touched by this work.

## Testing Strategy

Required tests:

- Profile tests for exact lean/full/readonly tool names.
- Tests that compatibility tools are absent from lean.
- Tests that readonly excludes write/export/destructive tools.
- Tests that every registered tool has output schema coverage unless explicitly
  documented as impossible.
- Catalog generation and drift test.
- Unit tests for resource URI parsing and resource payload shape.
- Unit tests for `record_review_context` validation and event projection.
- Migration/schema tests for `review_llm_context` and events.
- Repository tests for append-only context event behavior.
- Retrieval tests proving batch shared reads are not repeated per query.
- MCP facade tests for resource templates.

Final verification remains `make ci-local`.

## Rollout

Implementation should land in four safe increments:

1. Catalog/profile foundation and output schema cleanup.
2. Generated catalog docs and drift test.
3. Review resource templates.
4. Durable LLM context and batch retrieval shared-read cleanup.

Each increment should be independently testable and should avoid changing the
public behavior of full-profile tools except for description/schema cleanup.
