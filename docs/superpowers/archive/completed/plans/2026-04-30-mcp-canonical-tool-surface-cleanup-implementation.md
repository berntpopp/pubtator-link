# MCP Canonical Tool Surface Cleanup Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one canonical flat-argument MCP tool per operation and remove duplicate `_v2` public tools, docs, capability entries, and dead adapter/model code.

**Architecture:** Keep REST and service-layer request models unchanged. Move the current flat `_v2` MCP signatures onto canonical tool names in `pubtator_link/mcp/facade.py`, then simplify `pubtator_link/mcp/service_adapters.py` so canonical adapter functions accept flat arguments and build internal request models where needed. Update resources, prompts, docs, and tests to advertise only canonical tool names.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic, pytest, Ruff, mypy, uv, Makefile targets.

---

## File Map

- Modify `pubtator_link/mcp/facade.py`: remove `_v2` imports and tool registrations; give canonical tools flat signatures.
- Modify `pubtator_link/mcp/service_adapters.py`: remove `_v2` helper functions; convert canonical adapter functions for duplicated operations to flat arguments.
- Modify `pubtator_link/mcp/tools.py`: remove MCP-only wrapper request classes that become unused after canonical tools are flat.
- Modify `pubtator_link/mcp/resources.py`: remove `_v2` names from capabilities, groups, sample calls, and large-output guidance.
- Modify `pubtator_link/mcp/prompts.py`: ensure workflow prompts mention canonical names only.
- Modify `docs/MCP_CONNECTION_GUIDE.md`: update examples and tool table to canonical names and flat arguments.
- Modify `tests/unit/mcp/test_mcp_facade.py`: assert canonical flat schemas and no `_v2` tools/capabilities.
- Modify `tests/unit/mcp/test_review_rerag_mcp.py`: replace `_v2` registration assertions with canonical flat schema assertions.
- Modify `tests/unit/mcp/test_mcp_service_adapters.py`: replace `_v2` adapter tests with canonical flat adapter tests.

## Task 1: Lock The Canonical Tool Surface With Failing Tests

**Files:**
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Modify: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Update facade tests to reject `_v2` tool registrations**

Replace `test_common_flat_v2_tools_are_registered` in `tests/unit/mcp/test_mcp_facade.py` with:

```python
def test_common_mcp_tools_are_flat_and_unversioned() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools
    tool_names = set(tools)

    assert not any(name.endswith("_v2") for name in tool_names)

    canonical_flat_tools = {
        "pubtator.search_literature": ("text",),
        "pubtator.search_biomedical_entities": ("query",),
        "pubtator.get_publication_passages": ("pmids",),
        "pubtator.inspect_review_index": ("review_id",),
        "pubtator.retrieve_review_context": ("review_id", "question"),
        "pubtator.retrieve_review_context_batch": ("review_id", "queries"),
    }

    for name, required_properties in canonical_flat_tools.items():
        assert name in tools
        properties = tools[name].parameters["properties"]
        assert "request" not in properties
        for property_name in required_properties:
            assert property_name in properties

    batch_schema = tools["pubtator.retrieve_review_context_batch"].parameters
    assert batch_schema["properties"]["response_mode"]["default"] == "compact"
```

- [ ] **Step 2: Update capabilities tests to reject `_v2` names everywhere**

In `tests/unit/mcp/test_mcp_facade.py`, replace assertions that expect `_v2` sample calls with:

```python
def test_capabilities_resource_uses_canonical_tool_names_only() -> None:
    capabilities = get_capabilities_resource()
    encoded = repr(capabilities)

    assert "_v2" not in encoded
    assert "pubtator.search_literature" in capabilities["tools"]
    assert "pubtator.retrieve_review_context_batch" in capabilities["sample_calls"]
    assert capabilities["large_output_guidance"]["prefer"] == "pubtator.get_publication_passages"
```

- [ ] **Step 3: Update review RAG MCP tests**

Replace `test_flat_v2_review_tools_are_registered_without_request_wrapper` in `tests/unit/mcp/test_review_rerag_mcp.py` with:

```python
def test_review_tools_are_registered_with_flat_canonical_schemas() -> None:
    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    for removed_name in (
        "pubtator.inspect_review_index_v2",
        "pubtator.retrieve_review_context_v2",
        "pubtator.retrieve_review_context_batch_v2",
    ):
        assert removed_name not in tools

    batch_schema = tools["pubtator.retrieve_review_context_batch"].parameters
    properties = batch_schema["properties"]
    assert "review_id" in properties
    assert "queries" in properties
    assert "request" not in properties
    assert properties["response_mode"]["default"] == "compact"
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: FAIL because `_v2` tools are still registered and canonical tools still expose `request` wrappers.

- [ ] **Step 5: Leave the failing tests uncommitted until implementation passes**

Do not commit failing tests by themselves. Continue to Task 2 and commit after the implementation makes them pass.

## Task 2: Convert Canonical MCP Tools To Flat Schemas And Remove `_v2` Registrations

**Files:**
- Modify: `pubtator_link/mcp/facade.py`

- [ ] **Step 1: Remove `_v2` adapter imports**

In `pubtator_link/mcp/facade.py`, remove these imports from `pubtator_link.mcp.service_adapters`:

```python
get_publication_passages_v2_impl,
inspect_review_index_v2_impl,
retrieve_review_context_batch_v2_impl,
retrieve_review_context_v2_impl,
search_biomedical_entities_v2_impl,
search_literature_v2_impl,
```

- [ ] **Step 2: Remove obsolete request-model imports**

Remove these imports from `pubtator_link.mcp.tools` if they are no longer needed after the flat conversion:

```python
GetPublicationPassagesMcpRequest,
InspectReviewIndexMcpRequest,
RetrieveReviewContextBatchMcpRequest,
RetrieveReviewContextMcpRequest,
SearchBiomedicalEntitiesRequest,
SearchLiteratureRequest,
```

Keep these request model imports because they remain wrapper-style and are not part of the duplicate cleanup:

```python
EstimatePublicationContextMcpRequest,
FetchPmcAnnotationsRequest,
FetchPublicationAnnotationsRequest,
FindEntityRelationsRequest,
GetTextAnnotationResultsRequest,
IndexReviewEvidenceMcpRequest,
SubmitTextAnnotationRequest,
```

- [ ] **Step 3: Replace `pubtator.search_literature` registration with flat arguments**

Change the canonical `search_literature` function to:

```python
async def search_literature(
    text: str,
    page: int = 1,
    sort: str | None = None,
    filters: str | None = None,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    """Use this when a user needs PubMed literature search through PubTator3. Use short biomedical queries, optional sort such as 'score desc' or 'date desc', and optional section filters. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    async with PubTator3Client() as client:
        return await search_literature_impl(
            client=client,
            text=text,
            page=page,
            sort=sort,
            filters=filters,
            sections=sections,
        )
```

Delete the entire `pubtator.search_literature_v2` tool registration.

- [ ] **Step 4: Replace `pubtator.get_publication_passages` registration with flat arguments**

Change the canonical `get_publication_passages` function to:

```python
async def get_publication_passages(
    pmids: list[str],
    sections: list[str] | None = None,
    mode: PublicationPassageMode = "compact_passages",
    full: bool = False,
    max_passages_per_pmid: int = 6,
    max_chars: int = 12000,
    include_tables: bool = True,
    include_references: bool = False,
) -> dict[str, Any]:
    """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. Prefer this over raw annotation export for routine grounding. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_publication_passage_service()
    return await get_publication_passages_impl(
        service=service,
        pmids=pmids,
        sections=sections,
        mode=mode,
        full=full,
        max_passages_per_pmid=max_passages_per_pmid,
        max_chars=max_chars,
        include_tables=include_tables,
        include_references=include_references,
    )
```

Delete the entire `pubtator.get_publication_passages_v2` tool registration.

- [ ] **Step 5: Replace `pubtator.search_biomedical_entities` registration with flat arguments**

Change the canonical `search_biomedical_entities` function to:

```python
async def search_biomedical_entities(
    query: str,
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]
    | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    async with PubTator3Client() as client:
        return await search_biomedical_entities_impl(
            client=client,
            query=query,
            concept=concept,
            limit=limit,
        )
```

Delete the entire `pubtator.search_biomedical_entities_v2` tool registration.

- [ ] **Step 6: Replace `pubtator.inspect_review_index` registration with flat arguments**

Change the canonical `inspect_review_index` function to:

```python
async def inspect_review_index(
    review_id: str,
    pmids: list[str] | None = None,
    include_passage_samples: bool = False,
    sample_per_pmid: int = 2,
) -> dict[str, Any]:
    """Use this when a user needs to inspect indexed PMIDs, source coverage, sections, passage counts, and failures for a review_id. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_review_context_service()
    return await inspect_review_index_impl(
        service=service,
        review_id=review_id,
        pmids=pmids,
        include_passage_samples=include_passage_samples,
        sample_per_pmid=sample_per_pmid,
    )
```

Delete the entire `pubtator.inspect_review_index_v2` tool registration.

- [ ] **Step 7: Replace `pubtator.retrieve_review_context` registration with flat arguments**

Change the canonical `retrieve_review_context` function to:

```python
async def retrieve_review_context(
    review_id: str,
    question: str,
    pmids: list[str] | None = None,
    entity_ids: list[str] | None = None,
    sections: list[str] | None = None,
    max_passages: int = 8,
    max_chars: int = 6000,
    include_diagnostics: bool = False,
    include_tables: bool = False,
    include_references: bool = False,
    table_mode: ReviewTableMode = "preview",
    allow_truncated_passages: bool = True,
    max_chars_per_passage: int = 2200,
) -> dict[str, Any]:
    """Use this when a review needs compact citable context from prepared review passages instead of raw BioC export. Use short keyword questions, PMID filters for paper-specific evidence, and diagnostics for zero-result debugging. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
    service = await get_review_context_service()
    return await retrieve_review_context_impl(
        service=service,
        review_id=review_id,
        question=question,
        pmids=pmids,
        entity_ids=entity_ids,
        sections=sections,
        max_passages=max_passages,
        max_chars=max_chars,
        include_diagnostics=include_diagnostics,
        include_tables=include_tables,
        include_references=include_references,
        table_mode=table_mode,
        allow_truncated_passages=allow_truncated_passages,
        max_chars_per_passage=max_chars_per_passage,
    )
```

Delete the entire `pubtator.retrieve_review_context_v2` tool registration.

- [ ] **Step 8: Replace `pubtator.retrieve_review_context_batch` registration with flat arguments**

Change the canonical `retrieve_review_context_batch` function to:

```python
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
        service=service,
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

Delete the entire `pubtator.retrieve_review_context_batch_v2` tool registration.

- [ ] **Step 9: Run facade tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: some failures remain from adapters/resources until Tasks 3 and 4 are complete.

## Task 3: Simplify MCP Adapter Functions And Delete Dead Request Classes

**Files:**
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Replace `_v2` adapter tests with canonical flat adapter tests**

In `tests/unit/mcp/test_mcp_service_adapters.py`, rename and update the `_v2` adapter tests to import canonical adapter functions:

```python
async def test_retrieve_review_context_batch_adapter_builds_request_from_flat_args() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl
    from pubtator_link.models.review_rerag import (
        ContextPack,
        PreparationStatus,
        RetrieveReviewContextBatchResponse,
    )

    class RecordingService:
        review_id = None
        request = None

        async def retrieve_context_batch(self, review_id, request):
            self.review_id = review_id
            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                response_mode=request.response_mode,
                results=[],
                merged_context_pack=ContextPack(question="", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="rev",
        queries=["MEFV", "colchicine"],
        response_mode="diagnostics",
        max_chars=8000,
        max_response_chars=12000,
        include_tables=False,
    )

    assert service.review_id == "rev"
    assert service.request.response_mode == "diagnostics"
    assert service.request.max_response_chars == 12000
    assert service.request.include_tables is False
    assert result["response_mode"] == "diagnostics"
```

Apply the same pattern to the existing tests for:

- `retrieve_review_context_impl`
- `inspect_review_index_impl`
- `search_literature_impl`
- `search_biomedical_entities_impl`
- `get_publication_passages_impl`

- [ ] **Step 2: Run adapter tests to verify failure**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: FAIL because canonical adapter functions still expect wrapper request objects.

- [ ] **Step 3: Convert `search_biomedical_entities_impl` to flat arguments**

Change the function signature and body to:

```python
async def search_biomedical_entities_impl(
    *,
    client: PubTator3Client,
    query: str,
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    normalized_query = query.strip()
    raw_response = await client.autocomplete_entity(
        query=normalized_query,
        concept=concept,
        limit=limit,
    )
    raw_results = cast(list[dict[str, Any]], raw_response)
    matches = [
        EntityMatch(
            identifier=item.get("_id", ""),
            name=item.get("name", ""),
            type=item.get("biotype", concept or "Unknown"),
            score=item.get("score"),
            synonyms=item.get("synonyms", []),
            db_id=item.get("db_id"),
            db=item.get("db"),
            match=item.get("match"),
        )
        for item in raw_results
    ]
    return EntityAutocompleteResponse(
        success=True,
        query=normalized_query,
        matches=matches,
        total_matches=len(matches),
        concept_filter=concept,
    ).model_dump()
```

Delete `search_biomedical_entities_v2_impl`.

- [ ] **Step 4: Convert `get_publication_passages_impl` to flat arguments**

Change the function signature and request construction to:

```python
async def get_publication_passages_impl(
    *,
    service: PublicationPassageService,
    pmids: list[str],
    sections: list[str] | None = None,
    mode: PublicationPassageMode = "compact_passages",
    full: bool = False,
    max_passages_per_pmid: int = 6,
    max_chars: int = 12000,
    include_tables: bool = True,
    include_references: bool = False,
) -> dict[str, Any]:
    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=pmids,
            sections=sections or [],
            mode=mode,
            full=full,
            max_passages_per_pmid=max_passages_per_pmid,
            max_chars=max_chars,
            include_tables=include_tables,
            include_references=include_references,
        )
    )
    return response.model_dump()
```

Delete `get_publication_passages_v2_impl`.

- [ ] **Step 5: Convert `search_literature_impl` to flat arguments**

Change the function signature and body to:

```python
async def search_literature_impl(
    *,
    client: PubTator3Client,
    text: str,
    page: int = 1,
    sort: str | None = None,
    filters: str | None = None,
    sections: list[str] | None = None,
) -> dict[str, Any]:
    normalized_text = text.strip()
    result = await client.search_publications(
        text=normalized_text,
        page=page,
        sort=sort,
        filters=filters,
        sections=",".join(sections) if sections else None,
    )
    search_results = [
        SearchResult(
            pmid=item.get("pmid", ""),
            title=item.get("title", ""),
            abstract=item.get("abstract"),
            authors=item.get("authors", []),
            journal=item.get("journal"),
            pub_date=item.get("pub_date"),
            annotations=item.get("annotations", []),
            score=item.get("score"),
            pmcid=item.get("pmcid"),
            doi=item.get("doi"),
            date=item.get("date"),
            text_hl=item.get("text_hl"),
            citations=item.get("citations"),
        )
        for item in result.get("results", [])
    ]
    total_results = int(result.get("total", 0))
    per_page = int(result.get("per_page", 20))
    total_pages = (total_results + per_page - 1) // per_page if per_page else 0
    return SearchResponse(
        success=True,
        query=normalized_text,
        results=search_results,
        total_results=total_results,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_order=sort,
    ).model_dump()
```

Delete `search_literature_v2_impl`.

- [ ] **Step 6: Convert review adapter functions to flat arguments**

Convert `inspect_review_index_impl`, `retrieve_review_context_impl`, and `retrieve_review_context_batch_impl` to the same signatures used by the canonical facade functions in Task 2. Each function should build the existing internal service request model with `pmids or []`, `entity_ids or []`, and `sections or []`.

Delete these functions:

```python
inspect_review_index_v2_impl
retrieve_review_context_v2_impl
retrieve_review_context_batch_v2_impl
```

- [ ] **Step 7: Delete unused MCP wrapper request classes**

In `pubtator_link/mcp/tools.py`, delete these classes if `rg` confirms no references remain:

```python
SearchLiteratureRequest
GetPublicationPassagesMcpRequest
SearchBiomedicalEntitiesRequest
InspectReviewIndexMcpRequest
RetrieveReviewContextMcpRequest
RetrieveReviewContextBatchMcpRequest
```

Keep `EstimatePublicationContextMcpRequest`, `FetchPublicationAnnotationsRequest`, `FetchPmcAnnotationsRequest`, `FindEntityRelationsRequest`, `SubmitTextAnnotationRequest`, `GetTextAnnotationResultsRequest`, and `IndexReviewEvidenceMcpRequest`.

- [ ] **Step 8: Remove unused imports**

Run:

```bash
uv run ruff check pubtator_link/mcp tests/unit/mcp --select F401
```

Expected: Ruff identifies no unused imports after cleanup. If it reports unused imports, remove only those imports.

- [ ] **Step 9: Run adapter and facade tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py -q
```

Expected: adapter/facade tests pass except capabilities/docs assertions that Task 4 will address.

- [ ] **Step 10: Commit code and MCP unit tests**

Run:

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/tools.py tests/unit/mcp/test_mcp_facade.py tests/unit/mcp/test_review_rerag_mcp.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "refactor: canonicalize mcp tool surface"
```

## Task 4: Clean Capabilities, Prompts, And Active Docs

**Files:**
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/prompts.py`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Update `get_capabilities_resource()`**

In `pubtator_link/mcp/resources.py`, remove every `_v2` name from `tools`, `tool_groups`, `large_output_guidance`, `sample_calls`, and `review_rerag.tools`.

The canonical `tools` list should include:

```python
[
    "pubtator.search_literature",
    "pubtator.get_publication_passages",
    "pubtator.estimate_publication_context",
    "pubtator.fetch_publication_annotations",
    "pubtator.fetch_pmc_annotations",
    "pubtator.search_biomedical_entities",
    "pubtator.find_entity_relations",
    "pubtator.submit_text_annotation",
    "pubtator.get_text_annotation_results",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context",
    "pubtator.retrieve_review_context_batch",
    "pubtator.get_server_capabilities",
]
```

Update sample calls to use canonical names:

```python
"pubtator.search_literature": {
    "text": "MEFV colchicine familial Mediterranean fever guideline",
    "sort": "score desc",
},
"pubtator.get_publication_passages": {
    "pmids": ["40234174"],
    "mode": "compact_passages",
    "max_chars": 12000,
},
"pubtator.retrieve_review_context_batch": {
    "review_id": "fmf-colchicine-guidelines",
    "queries": [
        "MEFV colchicine",
        "familial Mediterranean fever child",
        "EULAR PReS recommendation",
    ],
    "response_mode": "compact",
    "max_chars": 12000,
    "max_response_chars": 24000,
},
"pubtator.retrieve_review_context_batch:diagnostics": {
    "review_id": "fmf-colchicine-guidelines",
    "queries": ["MEFV colchicine", "FMF guideline"],
    "response_mode": "diagnostics",
},
```

- [ ] **Step 2: Ensure prompts mention canonical tools only**

Check `pubtator_link/mcp/prompts.py` with:

```bash
rg -n "_v2|request wrapper|flat-argument|compatibility" pubtator_link/mcp/prompts.py
```

Expected: no matches.

If matches exist, replace them with canonical tool names and compact workflow language.

- [ ] **Step 3: Update `docs/MCP_CONNECTION_GUIDE.md`**

Replace active workflow examples:

```markdown
1. `pubtator.search_literature` to find candidate PMIDs.
2. `pubtator.index_review_evidence` to prepare the selected corpus.
3. `pubtator.inspect_review_index` to verify PMIDs, sections, source coverage, counts, and failures.
4. `pubtator.retrieve_review_context` or `pubtator.retrieve_review_context_batch` for compact citable passages.
5. `pubtator.get_publication_passages` for explicit PMID section retrieval.
```

Remove `_v2` rows from the tool table. If the table describes schema shape, state:

```markdown
Canonical MCP tools use flat top-level arguments. Do not wrap inputs in `{ "request": ... }`.
```

- [ ] **Step 4: Run active-reference scan**

Run:

```bash
rg -n "_v2|request wrapper|flat-argument|compatibility search_literature" pubtator_link tests docs/MCP_CONNECTION_GUIDE.md -S
```

Expected: no active-code, active-test, or active-doc matches. Historical specs/plans under `docs/superpowers/` may still mention `_v2`; do not rewrite historical implementation records unless a current test imports them.

- [ ] **Step 5: Run MCP unit tests**

Run:

```bash
uv run pytest tests/unit/mcp -q
```

Expected: all MCP unit tests pass.

- [ ] **Step 6: Commit docs/resources cleanup**

Run:

```bash
git add pubtator_link/mcp/resources.py pubtator_link/mcp/prompts.py docs/MCP_CONNECTION_GUIDE.md tests/unit/mcp/test_mcp_facade.py
git commit -m "docs: document canonical mcp tools"
```

## Task 5: Full Verification And Docker Smoke Check

**Files:**
- No planned source edits.

- [ ] **Step 1: Run focused route/service regression tests**

Run:

```bash
uv run pytest tests/test_routes/test_reviews.py tests/test_routes/test_search.py tests/unit/test_review_context_service.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run formatting, linting, and type checking**

Run:

```bash
make format
make lint
make typecheck-fast
```

Expected: all commands exit 0.

- [ ] **Step 3: Run full local CI**

Run:

```bash
make ci-local
```

Expected: all formatting, linting, type checking, and tests pass. PostgreSQL integration tests may skip if `PUBTATOR_LINK_TEST_DATABASE_URL` is unset; report that clearly.

- [ ] **Step 4: Rebuild and restart Docker MCP**

Run:

```bash
make docker-build
make docker-up
```

Expected: Docker Compose starts `pubtator_link_server` on the configured host port.

- [ ] **Step 5: Smoke test health endpoint**

Run:

```bash
curl -fsS http://127.0.0.1:8011/health
```

Expected response includes:

```json
{"status":"healthy"}
```

- [ ] **Step 6: Smoke test MCP tool list does not expose `_v2`**

Use the existing MCP protocol test suite first:

```bash
uv run pytest tests/integration/test_mcp_http_protocol.py -q
```

Expected: tests pass after updating any expected tool names to canonical names only.

If manual inspection is needed, use the MCP client path already present in the repo rather than adding new scripts.

- [ ] **Step 7: Final commit if verification required test/docs tweaks**

If Step 1-6 required additional edits, commit them:

```bash
git add <changed-files>
git commit -m "test: verify canonical mcp surface"
```

If no files changed, do not create an empty commit.

## Self-Review Checklist

- [ ] The plan removes all public `_v2` tools.
- [ ] The plan keeps REST contracts unchanged.
- [ ] The plan keeps active docs and capabilities canonical.
- [ ] The plan includes failing tests before production changes.
- [ ] The plan includes focused tests and `make ci-local`.
- [ ] The plan avoids compatibility aliases, because the approved direction is focused cleanup with no dead public tool names.
