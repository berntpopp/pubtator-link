# MCP Canonical Tool Surface Cleanup Design

## Goal

Reduce PubTator-Link MCP context overhead and caller confusion by exposing one canonical tool per user-facing operation. The canonical tools should keep the LLM-friendly flat argument schemas from the current `_v2` tools, while removing duplicate `_v2` public registrations, capability entries, documentation examples, and adapter dead code.

## Background

The current MCP facade exposes both wrapper-style tools and flat `_v2` tools for several operations:

- `pubtator.search_literature` and `pubtator.search_literature_v2`
- `pubtator.search_biomedical_entities` and `pubtator.search_biomedical_entities_v2`
- `pubtator.get_publication_passages` and `pubtator.get_publication_passages_v2`
- `pubtator.inspect_review_index` and `pubtator.inspect_review_index_v2`
- `pubtator.retrieve_review_context` and `pubtator.retrieve_review_context_v2`
- `pubtator.retrieve_review_context_batch` and `pubtator.retrieve_review_context_batch_v2`

This helped introduce flat schemas without immediately breaking the prior wrapper-style tools, but it now doubles the visible tool surface for common workflows. For deferred tool search and context-sensitive tool selection, duplicate tools make discovery noisier and force descriptions to explain version choice rather than the task.

Current MCP guidance supports reducing tool context and using progressive discovery when tool definitions grow large. It also recommends model-friendly tool descriptions with clear "Use this when..." guidance, compact schemas, structured outputs, and read-only annotations where applicable. PubTator-Link already follows much of this; the largest remaining local issue is duplicate public tool exposure.

## Scope

In scope:

- Make these canonical MCP tools use flat argument signatures directly:
  - `pubtator.search_literature`
  - `pubtator.search_biomedical_entities`
  - `pubtator.get_publication_passages`
  - `pubtator.inspect_review_index`
  - `pubtator.retrieve_review_context`
  - `pubtator.retrieve_review_context_batch`
- Remove these public tool registrations:
  - `pubtator.search_literature_v2`
  - `pubtator.search_biomedical_entities_v2`
  - `pubtator.get_publication_passages_v2`
  - `pubtator.inspect_review_index_v2`
  - `pubtator.retrieve_review_context_v2`
  - `pubtator.retrieve_review_context_batch_v2`
- Remove `_v2` adapter helper functions when they become unused.
- Keep request model classes only where they are still used by internal adapters or non-duplicated tools.
- Update MCP capabilities, resources, prompts, connection docs, and tests so no `_v2` names are advertised.
- Keep existing REST endpoints unchanged.
- Keep research-use limitations visible, but avoid adding repeated versioning boilerplate.

Out of scope:

- Adding new retrieval algorithms, ranking formulas, or metadata enrichment.
- Adding `list_review_indexes`.
- Adding citation style formatting.
- Changing REST route paths or request bodies.
- Preserving `_v2` aliases for backward compatibility.

## Public Contract

After this cleanup, clients should call canonical names only. The common tools should have flat MCP schemas:

```json
{
  "name": "pubtator.retrieve_review_context_batch",
  "input": {
    "review_id": "fmf-colchicine-guidelines",
    "queries": ["MEFV colchicine", "FMF guideline"],
    "response_mode": "compact",
    "max_chars": 12000,
    "max_response_chars": 24000
  }
}
```

The old wrapper shape for these canonical MCP tools is intentionally removed:

```json
{
  "request": {
    "review_id": "fmf-colchicine-guidelines",
    "queries": ["MEFV colchicine"]
  }
}
```

This is a breaking MCP surface cleanup. The REST API continues to accept its existing JSON bodies.

## Design

### MCP Facade

`pubtator_link/mcp/facade.py` should register only one public MCP tool per operation. For the six duplicated operations, the canonical registration should move the current `_v2` function signature and description onto the non-versioned name.

Example target pattern:

```python
@mcp.tool(
    name="pubtator.retrieve_review_context_batch",
    title="Retrieve Review Context Batch",
    annotations=READ_ONLY_OPEN_WORLD,
)
async def retrieve_review_context_batch(
    review_id: str,
    queries: list[str],
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    response_mode: ReviewBatchResponseMode = "compact",
    max_passages_per_query: int = 8,
    max_total_passages: int = 20,
    max_chars: int = 12000,
    max_response_chars: int = 24000,
    deduplicate_passages: bool = True,
    include_diagnostics: bool = True,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    """Use this when a user wants multiple short review retrieval query variants in one call. Default compact mode returns merged passages plus per-query summaries; use diagnostics for query refinement and full only when per-query passage text is needed. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_review_context_service()
    return await retrieve_review_context_batch_impl(
        review_id=review_id,
        queries=queries,
        pmids=pmids,
        entity_ids=entity_ids,
        sections=sections,
        response_mode=response_mode,
        max_passages_per_query=max_passages_per_query,
        max_total_passages=max_total_passages,
        max_chars=max_chars,
        max_response_chars=max_response_chars,
        deduplicate_passages=deduplicate_passages,
        include_diagnostics=include_diagnostics,
        include_tables=include_tables,
        include_references=include_references,
        table_mode=table_mode,
        allow_truncated_passages=allow_truncated_passages,
        max_chars_per_passage=max_chars_per_passage,
    )
```

### Service Adapters

The adapter module should expose canonical flat adapter functions for the six operations:

- `search_literature_impl(..., text, page, sort, sections, filters)`
- `search_biomedical_entities_impl(..., query, concept, limit)`
- `get_publication_passages_impl(..., pmids, sections, mode, full, max_passages_per_pmid, max_chars, include_tables, include_references)`
- `inspect_review_index_impl(..., review_id, pmids, include_passage_samples, sample_per_pmid)`
- `retrieve_review_context_impl(..., review_id, question, pmids, entity_ids, sections, max_passages, max_chars, include_diagnostics, include_tables, include_references, table_mode, allow_truncated_passages, max_chars_per_passage)`
- `retrieve_review_context_batch_impl(..., review_id, queries, pmids, entity_ids, sections, response_mode, max_passages_per_query, max_total_passages, max_chars, max_response_chars, deduplicate_passages, include_diagnostics, include_tables, include_references, table_mode, allow_truncated_passages, max_chars_per_passage)`

The implementation may construct existing internal request models such as `RetrieveReviewContextBatchRequest`; those models remain useful for REST and service boundaries. The MCP-only wrapper request classes should be deleted when no longer referenced.

### Capabilities And Prompts

`pubtator://capabilities` should list only canonical tool names. Sample calls should use canonical names and flat JSON. Tool groups should avoid duplicates.

Prompts should refer only to canonical tool names. They should not mention `_v2`, compatibility wrappers, or version selection.

### Documentation

`docs/MCP_CONNECTION_GUIDE.md` should be updated to show canonical names and flat arguments. The tool table should not contain `_v2` entries.

Existing historical specs and plans may retain `_v2` references because they describe prior implementation history, but active user-facing docs and tests must not advertise them.

## Error Handling

This cleanup should not change service error behavior. Validation errors should continue to come from the generated MCP schema and underlying Pydantic/service models. Removing wrapper request models means validation should now identify the missing top-level parameter directly, such as `review_id`, rather than `request.review_id`.

## Testing

Tests must be written before production changes:

- MCP facade tests assert no tool name ends with `_v2`.
- MCP facade tests assert canonical tools have flat schemas and no top-level `request` property for the six cleaned-up operations.
- Capabilities tests assert no `_v2` names appear in `tools`, `tool_groups`, `sample_calls`, or `review_rerag.tools`.
- Adapter tests cover canonical flat adapter behavior for representative operations.
- Existing route and service tests continue to pass unchanged.

Focused checks:

```bash
uv run pytest tests/unit/mcp -q
uv run pytest tests/test_routes/test_reviews.py tests/test_routes/test_search.py tests/unit/test_review_context_service.py -q
```

Completion gate:

```bash
make ci-local
```

## Migration Notes

Callers must replace `_v2` names with canonical names:

- `pubtator.search_literature_v2` -> `pubtator.search_literature`
- `pubtator.search_biomedical_entities_v2` -> `pubtator.search_biomedical_entities`
- `pubtator.get_publication_passages_v2` -> `pubtator.get_publication_passages`
- `pubtator.inspect_review_index_v2` -> `pubtator.inspect_review_index`
- `pubtator.retrieve_review_context_v2` -> `pubtator.retrieve_review_context`
- `pubtator.retrieve_review_context_batch_v2` -> `pubtator.retrieve_review_context_batch`

Callers must pass arguments at the top level rather than under `request`.

## Acceptance Criteria

- `create_pubtator_mcp()._tool_manager._tools` contains no names ending in `_v2`.
- The six canonical tools expose flat parameters and no `request` wrapper.
- `pubtator://capabilities` contains no `_v2` names anywhere in active fields.
- Active docs and prompts use only canonical names.
- Unused `_v2` adapter functions and MCP-only wrapper request models are deleted.
- `make ci-local` passes.
