# MCP LLM Consumer Over 9 Remediation Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

## Goal

Raise PubTator-Link MCP from the current 7.7-8.5 LLM-consumer rating band to
9+ by fixing live regressions in advertised workflows and applying consistent
LLM-native payload discipline to raw upstream tools.

## Evidence

Live local MCP checks on `http://127.0.0.1:8011/mcp` reproduced the critical
report findings:

- `convert_article_ids` fails with `internal_error` when a batch mixes
  PMID, PMCID, and DOI. Logs show the NCBI ID Converter returning HTTP 400 for
  the mixed `ids=` request.
- `preflight_review_sources` fails when a PMCID exists but PubTator PMC
  BioC export returns HTTP 400. The tool now has a useful publication-passages
  fallback, but the canonical preflight path still aborts instead of falling
  back to abstract coverage.
- `submit_text_annotation` fails because the upstream text annotation
  endpoint returns JSON like `{"id":"..."}` while the client only reads a
  `content` field.
- `find_entity_relations` succeeds for `@GENE_MEFV` but returns about
  128 KB with no `limit`, `response_mode`, or summary controls.
- `export_review_audit_bundle` fails when an audit event has a
  non-mapping `payload`; `dict(event.get("payload") or {})` raises `ValueError`.
- `review_quickstart` accepts `wait_until_ready=true` and
  `timeout_ms=30000`, but still returns
  `quickstart does not block on indexing`.

Recent official guidance aligns with the report:

- MCP tools should use output schemas and structured content consistently, and
  can return resource links for large context instead of inlining everything.
- Anthropic guidance emphasizes detailed, behavior-specific tool descriptions,
  including caveats and limitations.
- Google guidance calls out that function descriptions and parameters consume
  input tokens, so large tool sets should be shortened or split into focused
  sets.
- OpenAI Agents guidance recommends short explicit descriptions, validated
  inputs, side-effect-free error handlers, and one responsibility per tool.

## Product Direction

PubTator-Link should keep the LLM-native review/RAG path as the front door and
bring raw upstream proxy tools up to the same standard. The target shape is:

- No advertised canonical workflow tool hard-fails on ordinary biomedical
  inputs.
- Every failure envelope gives a specific next action and does not suggest stale
  schema unless diagnostics actually indicate stale schema.
- Every potentially large tool has caller-controlled budget arguments and a
  compact default.
- Search-like tools omit empty/null fields in compact mode and avoid PubTator
  annotation markup unless explicitly requested.
- One-call tools handle natural-language questions by deriving a short search
  query or returning a preflight warning with a next command.
- State read tools derive status from the persisted review index when possible
  so session manifests and review indexes do not disagree.

## Architecture

The remediation splits into three layers.

1. Transport and adapter correctness:
   Fix client parsing and upstream error interpretation closest to the failing
   APIs. Mixed-ID conversion should isolate IDs by kind or fall back per ID.
   Preflight should treat "PMC full text not retrievable" as a negative probe,
   not as a tool failure. Text annotation should parse both JSON and legacy text
   session IDs.

2. MCP envelope and payload discipline:
   Add a small, shared MCP response-budget contract for raw upstream tools:
   `limit`, `response_mode`, `max_response_chars`, `omitted_count`,
   `response_size_class`, and resource links when available. Do not invent a
   second response vocabulary; mirror the existing review context batch fields.

3. Workflow truthfulness and ranking quality:
   Align schemas with runtime behavior. If `wait_until_ready` is exposed,
   quickstart must block and poll up to `timeout_ms`. Discovery tools should use
   existing entity and metadata signals before exposing candidates, especially
   for `suggest_corpus`, guideline search, citation lookup, and related
   articles.

## Non-Goals

- Do not rename the public MCP tools in this sprint.
- Do not remove full/raw BioC access; make it explicit and budgeted.
- Do not change clinical disclaimers or convert research-use tools into
  clinical decision support.
- Do not modify `.planning/` or the existing Phase 1 plan.

## Success Criteria

- The five reported broken or unsafe tools have regression tests and pass live
  MCP smoke checks:
  `convert_article_ids`, `preflight_review_sources`,
  `submit_text_annotation`, `find_entity_relations`,
  `export_review_audit_bundle`.
- `review_quickstart(wait_until_ready=true)` no longer returns a warning saying
  the flag is ignored.
- `make ci-local` passes.
- A local 43-tool smoke script produces no hard failures for the canonical
  workflow and no unbounded output above the configured cap.
- Compact search and relation payloads omit `None`/empty optional fields where
  the output schema permits it, while standard/full modes preserve compatibility.
- Diagnostics and error recovery agree: stale-schema recovery appears only when
  diagnostics or typed exceptions support that diagnosis.

