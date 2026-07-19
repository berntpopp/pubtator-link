# MCP Facade Domain Split Design

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

Date: 2026-05-01

## Goal

Split `pubtator_link/mcp/facade.py` into small domain registration modules while
preserving the public MCP contract.

## Problem

`pubtator_link/mcp/facade.py` is 504 lines and centralizes unrelated
responsibilities:

- FastMCP server creation and instructions.
- public tool annotations.
- literature/entity tool registration.
- publication and passage tool registration.
- remote text annotation tool registration.
- review re-RAG tool registration.
- resources and prompts.
- private FastMCP inspection compatibility.

That shape makes small MCP changes high-context. LLM coding agents must edit a
single broad file for unrelated domains, which increases merge conflict risk and
review cost.

The repository now has characterization tests for public MCP tool names,
resource URIs, prompt names, schemas, annotations, and capability advertising.
Those tests make a behavior-preserving split practical.

## Non-Goals

- Do not change public MCP tool names.
- Do not change resource URIs.
- Do not change prompt names.
- Do not change public tool argument schemas or defaults.
- Do not change REST routes or service behavior.
- Do not add new tools.
- Do not remove research-use limitations.
- Do not require external network calls in tests.

## Proposed Architecture

Keep `create_pubtator_mcp()` as the single public factory in
`pubtator_link/mcp/facade.py`. Reduce it to orchestration:

1. create `FastMCP` with the existing instructions.
2. call domain registration functions.
3. install inspection managers.
4. return the configured server.

Create small modules:

- `pubtator_link/mcp/annotations.py`
  - owns `READ_ONLY_OPEN_WORLD`, `READ_ONLY_CLOSED_WORLD`,
    `REMOTE_JOB_ANNOTATIONS`, and `REVIEW_WRITE_ANNOTATIONS`.
- `pubtator_link/mcp/compat.py`
  - owns private FastMCP inspection-manager compatibility.
- `pubtator_link/mcp/tools/literature.py`
  - registers literature search, biomedical entity search, and entity relation
    tools.
- `pubtator_link/mcp/tools/publications.py`
  - registers publication annotation, PMC annotation, publication passage, and
    context estimate tools.
- `pubtator_link/mcp/tools/text_annotations.py`
  - registers text annotation submission and result polling tools.
- `pubtator_link/mcp/tools/review.py`
  - registers review indexing, review index inspection, single retrieval, and
    batch retrieval tools.
- `pubtator_link/mcp/metadata.py`
  - registers resources and prompts.

Each registration function accepts a `FastMCP` instance and mutates only that
instance:

```python
def register_literature_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.search_literature",
        title="Search Biomedical Literature",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_literature(
        text: str,
        page: int = 1,
        sort: str | None = None,
        filters: str | None = None,
        publication_types: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        async with PubTator3Client() as client:
            return await search_literature_impl(
                client=client,
                text=text,
                page=page,
                sort=sort,
                filters=filters,
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
                sections=sections,
            )
```

This keeps registration explicit and avoids a plugin registry abstraction that
would hide the public surface.

## Public Contract

The following public tool set must remain exact:

- `pubtator.get_server_capabilities`
- `pubtator.search_literature`
- `pubtator.fetch_publication_annotations`
- `pubtator.get_publication_passages`
- `pubtator.estimate_publication_context`
- `pubtator.fetch_pmc_annotations`
- `pubtator.search_biomedical_entities`
- `pubtator.find_entity_relations`
- `pubtator.submit_text_annotation`
- `pubtator.get_text_annotation_results`
- `pubtator.index_review_evidence`
- `pubtator.inspect_review_index`
- `pubtator.retrieve_review_context`
- `pubtator.retrieve_review_context_batch`

The following resource URI set must remain exact:

- `pubtator://capabilities`
- `pubtator://bioconcepts`
- `pubtator://relation-types`
- `pubtator://formats`
- `pubtator://text-processing`
- `pubtator://compliance/research-use`

The following prompt set must remain exact:

- `search_biomedical_literature`
- `annotate_research_text`
- `review_pubtator_annotations`
- `review_rerag_workflow`

## Data Flow

Tool data flow stays unchanged:

1. MCP client calls a public `pubtator.*` tool.
2. Tool function validates flat arguments through FastMCP/Pydantic.
3. Tool function creates or fetches the same service/client dependency as today.
4. Tool function delegates to the existing implementation in
   `pubtator_link/mcp/service_adapters.py`.
5. Adapter returns the same dictionary response shape.

Only registration location changes.

## Compatibility Handling

`_install_inspection_managers()` currently adapts FastMCP 3 internals so tests
and compatibility checks can inspect registered tools, resources, and prompts.
Move this to `pubtator_link/mcp/compat.py` as:

```python
def install_inspection_managers(mcp: FastMCP) -> None:
    provider = cast(Any, mcp.providers[0])
    components = provider._components
    tools = {
        component.name: component
        for key, component in components.items()
        if key.startswith("tool:")
    }
    inspectable_mcp = cast(Any, mcp)
    inspectable_mcp._tool_manager = SimpleNamespace(_tools=tools)
```

Keep the private access in one module. Tests may continue inspecting
`mcp._tool_manager`, `mcp._resource_manager`, and `mcp._prompt_manager`, but no
new modules should duplicate private FastMCP access.

## Error Handling

Error behavior must not change. The split should preserve:

- FastMCP validation errors for invalid tool arguments.
- PubTator client/service exceptions from existing adapters.
- dependency lookup behavior for app-scoped services.
- research-use descriptions and non-destructive annotations.

No domain registration function should catch broad exceptions during normal tool
execution.

## Testing

Use existing characterization tests as the primary safety net:

- `tests/unit/mcp/test_mcp_facade.py`
- `tests/unit/mcp/test_mcp_service_adapters.py`

Add focused tests only where they lock the new module boundaries:

- registering all domain modules produces the same public tool set.
- `install_inspection_managers()` exposes tools, resources, and prompts after
  domain registration.
- capability advertising still matches registered tools.

Required focused check:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_mcp_service_adapters.py -q
```

Completion gate:

```bash
make ci-local
make test-cov
```

## Rollout

Implement the split in small commits:

1. Move annotations and compatibility helpers.
2. Move resources and prompts registration.
3. Move literature/entity tools.
4. Move publication tools.
5. Move text annotation tools.
6. Move review tools.
7. Shrink `facade.py` to orchestration.

Each commit should pass the focused MCP tests before moving on.

## Risks And Mitigations

Risk: public schema drift during copy/move.

Mitigation: run existing facade schema/default tests after every domain move.

Risk: circular imports between `facade.py`, annotations, and tool modules.

Mitigation: domain modules import only annotations, dependencies, service
adapters, models, and clients. They must not import `create_pubtator_mcp()`.

Risk: compatibility helper becomes coupled to FastMCP private internals.

Mitigation: isolate private access in `compat.py` and keep tests focused on
PubTator public metadata rather than arbitrary FastMCP internals.

## Success Criteria

- `pubtator_link/mcp/facade.py` is primarily orchestration.
- Public tool names, resource URIs, prompt names, annotations, schemas, and
  defaults are unchanged.
- Domain tool modules can be understood independently.
- Private FastMCP inspection compatibility exists in one module.
- `make ci-local` passes.
- `make test-cov` passes at the enforced 80% threshold.
