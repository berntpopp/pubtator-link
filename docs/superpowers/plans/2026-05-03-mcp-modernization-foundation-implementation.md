# MCP Modernization Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lean, resource-driven, durable MCP foundation that improves token efficiency, statefulness, and bounded parallel retrieval without adding duplicate workflows or dead compatibility code.

**Architecture:** Keep existing domain-owned MCP tool modules, add small catalog/profile/resource/context modules, and expose profile-aware registration through the facade. Review state moves to parameterized resources and durable event-sourced context while batch retrieval reuses shared reads across per-query work.

**Tech Stack:** Python 3.11, FastMCP, Pydantic v2, asyncpg/Postgres migrations, pytest, Ruff, mypy, Makefile targets.

---

## Working Rules

- Start from an isolated worktree/branch before implementation.
- Do not implement on `main` or `master`.
- Do not revert unrelated local changes.
- Use TDD for every task: failing test, verify fail, implement, verify pass.
- Prefer Makefile targets over ad hoc commands.
- Keep compatibility behavior in `full`; hide it from `lean`.
- Do not add `v2` tools, duplicate workflow APIs, or a central god registry.
- Use subagents only on tasks with disjoint write sets.

## Parallelization Map

Safe first wave:

- Agent A: Task 1 catalog/profile metadata and profile tests.
- Agent B: Task 2 output schema closure and tool description cleanup.
- Agent C: Task 4 resource URI parser and resource service tests.

Sequential integration points:

- Task 3 depends on Task 1 metadata.
- Task 5 depends on Task 4 resource patterns.
- Task 6 depends on DB schema and repository patterns.
- Task 7 depends on Task 6.
- Task 8 touches batch retrieval and should run after resource link models exist.

## Files

- Create: `pubtator_link/mcp/profiles.py`
- Create: `pubtator_link/mcp/catalog.py`
- Create: `pubtator_link/mcp/catalog_docs.py`
- Create: `pubtator_link/mcp/review_resources.py`
- Create: `pubtator_link/services/llm_review_context.py`
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/metadata.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/tools/*.py`
- Modify: `pubtator_link/mcp/contracts.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `pubtator_link/db/review_schema.sql`
- Create: `pubtator_link/db/migrations/0004_review_llm_context.sql`
- Create: `scripts/generate_mcp_tool_catalog.py`
- Create/modify: `docs/mcp-tool-catalog.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `README.md`
- Modify: `tests/unit/mcp/test_mcp_facade.py`
- Create: `tests/unit/mcp/test_mcp_profiles.py`
- Create: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Create: `tests/unit/mcp/test_mcp_review_resources.py`
- Create: `tests/unit/test_llm_review_context_service.py`
- Modify: `tests/unit/test_review_rerag_repository.py`
- Modify: `tests/unit/test_review_schema_sql.py`
- Modify: `tests/integration/test_review_schema_postgres.py`
- Modify: `tests/unit/test_review_context_service.py`

## Task 0: Create Implementation Worktree

**Files:**
- No source files modified.

- [ ] **Step 1: Check current branch and dirty state**

Run:

```bash
git status --short --branch
```

Expected: branch and dirty files are visible. Do not clean or revert unrelated files.

- [ ] **Step 2: Create an isolated worktree**

Run:

```bash
git worktree add ../pubtator-link-mcp-modernization -b codex/mcp-modernization-foundation
cd ../pubtator-link-mcp-modernization
```

Expected: new worktree on `codex/mcp-modernization-foundation`.

- [ ] **Step 3: Install dependencies if needed**

Run:

```bash
make install
```

Expected: `uv sync --group dev` completes.

## Task 1: Add Profile Model And Profile-Aware Facade

**Files:**
- Create: `pubtator_link/mcp/profiles.py`
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/tools/*.py`
- Modify: `pubtator_link/mcp/metadata.py`
- Create: `tests/unit/mcp/test_mcp_profiles.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing profile tests**

Create `tests/unit/mcp/test_mcp_profiles.py`:

```python
from __future__ import annotations


LEAN_TOOLS = {
    "pubtator.workflow_help",
    "pubtator.get_server_capabilities",
    "pubtator.diagnostics",
    "pubtator.search_literature",
    "pubtator.search_guidelines",
    "pubtator.search_biomedical_entities",
    "pubtator.lookup_variant_evidence",
    "pubtator.get_publication_metadata",
    "pubtator.get_publication_passages",
    "pubtator.preflight_review_sources",
    "pubtator.index_review_evidence",
    "pubtator.inspect_review_index",
    "pubtator.retrieve_review_context_batch",
    "pubtator.get_review_audit_trail",
    "pubtator.record_review_context",
}


def tool_names(profile: str) -> set[str]:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    return set(create_pubtator_mcp(profile=profile)._tool_manager._tools)


def test_lean_profile_exposes_only_core_llm_tools() -> None:
    assert tool_names("lean") == LEAN_TOOLS


def test_full_profile_keeps_compatibility_tools() -> None:
    names = tool_names("full")

    assert "pubtator.retrieve_review_context" in names
    assert "pubtator.get_review_passages_by_id" in names
    assert "pubtator.get_neighboring_review_passages" in names
    assert "pubtator.export_review_audit_bundle" in names
    assert LEAN_TOOLS.issubset(names)


def test_readonly_profile_excludes_write_and_export_tools() -> None:
    names = tool_names("readonly")

    assert "pubtator.index_review_evidence" not in names
    assert "pubtator.record_review_context" not in names
    assert "pubtator.export_review_audit_bundle" not in names
    assert "pubtator.retrieve_review_context_batch" in names
    assert "pubtator.get_review_audit_trail" in names
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_profiles.py -q
```

Expected: FAIL because `create_pubtator_mcp(profile=...)` and profiles do not exist.

- [ ] **Step 3: Add profile helpers**

Create `pubtator_link/mcp/profiles.py`:

```python
from __future__ import annotations

from typing import Literal

MCPToolProfile = Literal["lean", "full", "readonly"]

DEFAULT_MCP_PROFILE: MCPToolProfile = "lean"


def normalize_mcp_profile(value: str | None) -> MCPToolProfile:
    if value in {"lean", "full", "readonly"}:
        return value
    if value is None or value == "":
        return DEFAULT_MCP_PROFILE
    raise ValueError("mcp_profile must be one of: lean, full, readonly")
```

- [ ] **Step 4: Add config setting**

In `pubtator_link/config.py`, add near feature flags:

```python
    mcp_profile: Literal["lean", "full", "readonly"] = Field(
        default="lean",
        description="MCP tool registration profile",
    )
```

- [ ] **Step 5: Make facade profile-aware**

Change `create_pubtator_mcp()` in `pubtator_link/mcp/facade.py`:

```python
from pubtator_link.config import settings
from pubtator_link.mcp.profiles import MCPToolProfile, normalize_mcp_profile


def create_pubtator_mcp(profile: MCPToolProfile | str | None = None) -> FastMCP:
    selected_profile = normalize_mcp_profile(str(profile) if profile is not None else settings.mcp_profile)
    mcp = FastMCP(...)
    register_metadata(mcp, profile=selected_profile)
    register_literature_tools(mcp, profile=selected_profile)
    register_discovery_tools(mcp, profile=selected_profile)
    register_diagnostics_tools(mcp, profile=selected_profile)
    register_publication_tools(mcp, profile=selected_profile)
    register_text_annotation_tools(mcp, profile=selected_profile)
    register_review_tools(mcp, profile=selected_profile)
    install_inspection_managers(mcp)
    return mcp
```

Then update each `register_*_tools` function to accept `profile: MCPToolProfile = "lean"` and skip non-profile tools with early `if profile == ...` blocks. Keep the skip logic local and simple; do not create a central registration god object.

- [ ] **Step 6: Run profile tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS after updating expected default facade behavior to lean.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/config.py pubtator_link/mcp tests/unit/mcp
git commit -m "feat: add profile-aware MCP facade"
```

## Task 2: Close Output Schema Gap And Clean Tool Descriptions

**Files:**
- Modify: `pubtator_link/mcp/tools/publications.py`
- Modify: `pubtator_link/mcp/tools/text_annotations.py`
- Modify: `pubtator_link/mcp/tools/discovery.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add failing output schema coverage test**

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_full_profile_all_tools_have_output_schemas() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="full")
    missing = [
        name
        for name, tool in mcp._tool_manager._tools.items()
        if not _tool_output_schema(tool)
    ]

    assert missing == []
```

- [ ] **Step 2: Run failing schema test**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py::test_full_profile_all_tools_have_output_schemas -q
```

Expected: FAIL listing tools without output schemas.

- [ ] **Step 3: Register missing output schemas**

Add `output_schema=...model_json_schema()` to:

- `get_server_capabilities`
- `find_entity_relations`
- `submit_text_annotation`
- `get_text_annotation_results`
- `fetch_publication_annotations`
- `get_publication_passages`
- `get_publication_metadata`
- `estimate_publication_context`
- `fetch_pmc_annotations`

Use the existing Pydantic response models already imported or import the correct
models from `pubtator_link.models.*`.

- [ ] **Step 4: Apply description rubric**

For each modified tool description, use this structure:

```python
"""Use this when <specific task>. Do not use this for <preferred other tool/resource>. Next: <next tool/resource>."""
```

Examples:

```python
"""Use this when a client needs compact passage text for known PMIDs without a review index. Do not use this for prepared review RAG; use pubtator.retrieve_review_context_batch after indexing. Next: cite passage IDs or preflight/index sources for review work."""
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/mcp/tools tests/unit/mcp/test_mcp_facade.py
git commit -m "fix: complete MCP output schemas and descriptions"
```

## Task 3: Add Runtime-Derived Tool Catalog And Generated Docs

**Files:**
- Create: `pubtator_link/mcp/catalog.py`
- Create: `pubtator_link/mcp/catalog_docs.py`
- Create: `scripts/generate_mcp_tool_catalog.py`
- Create/modify: `docs/mcp-tool-catalog.md`
- Create: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing catalog tests**

Create `tests/unit/mcp/test_mcp_tool_catalog.py`:

```python
from __future__ import annotations


def test_catalog_covers_full_profile_runtime_tools() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="full")
    runtime_names = set(mcp._tool_manager._tools)
    catalog = build_tool_catalog(mcp, profile="full")

    assert set(catalog) == runtime_names


def test_catalog_entries_have_token_efficient_fields() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")

    for name, entry in catalog.items():
        assert entry.name == name
        assert entry.description.startswith("Use this when ")
        assert entry.category
        assert entry.profiles
        assert entry.example
        assert entry.has_output_schema is True
        assert len(entry.description) <= 420


def test_generated_catalog_is_current() -> None:
    from pathlib import Path

    from pubtator_link.mcp.catalog_docs import render_tool_catalog_markdown

    expected = render_tool_catalog_markdown()
    actual = Path("docs/mcp-tool-catalog.md").read_text()

    assert actual == expected
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: FAIL because catalog modules do not exist.

- [ ] **Step 3: Add catalog models and runtime extraction**

Create `pubtator_link/mcp/catalog.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pubtator_link.mcp.profiles import MCPToolProfile

ToolCategory = Literal["metadata", "diagnostics", "literature", "discovery", "publication", "review", "retrieval", "annotation", "audit"]
ToolStability = Literal["lean", "advanced", "compat", "admin"]


@dataclass(frozen=True)
class ToolCatalogEntry:
    name: str
    title: str
    category: ToolCategory
    profiles: tuple[MCPToolProfile, ...]
    stability: ToolStability
    description: str
    do_not_use_for: str
    example: str
    next_tools: tuple[str, ...] = ()
    resource_links: tuple[str, ...] = ()
    output_schema_name: str | None = None
    has_output_schema: bool = False


@dataclass(frozen=True)
class ToolCatalogSupplement:
    category: ToolCategory
    profiles: tuple[MCPToolProfile, ...]
    stability: ToolStability
    do_not_use_for: str
    example: str
    next_tools: tuple[str, ...] = ()
    resource_links: tuple[str, ...] = ()


TOOL_CATALOG_SUPPLEMENTS: dict[str, ToolCatalogSupplement] = {
    # Add one small supplement for every full-profile runtime tool.
}


def _tool_output_schema(tool: Any) -> dict[str, Any] | None:
    schema = getattr(tool, "output_schema", None) or getattr(tool, "outputSchema", None)
    if schema is None:
        metadata = getattr(tool, "fn_metadata", None)
        schema = getattr(metadata, "output_schema", None) if metadata is not None else None
    return schema if isinstance(schema, dict) else None


def build_tool_catalog(mcp: Any, *, profile: MCPToolProfile) -> dict[str, ToolCatalogEntry]:
    catalog: dict[str, ToolCatalogEntry] = {}
    for name, tool in mcp._tool_manager._tools.items():
        supplement = TOOL_CATALOG_SUPPLEMENTS[name]
        output_schema = _tool_output_schema(tool)
        catalog[name] = ToolCatalogEntry(
            name=name,
            title=getattr(tool, "title", None) or name,
            category=supplement.category,
            profiles=supplement.profiles,
            stability=supplement.stability,
            description=str(getattr(tool, "description", "") or ""),
            do_not_use_for=supplement.do_not_use_for,
            example=supplement.example,
            next_tools=supplement.next_tools,
            resource_links=supplement.resource_links,
            output_schema_name=(output_schema or {}).get("title"),
            has_output_schema=output_schema is not None,
        )
    return catalog
```

Populate `TOOL_CATALOG_SUPPLEMENTS` for all full-profile tools. Mark lean tools
with `profiles=("lean", "full")`, readonly-safe tools with `"readonly"`, and
compat tools with `stability="compat"`. The supplement must not duplicate title,
description, parameter schema, or output schema data already held by runtime
registration.

- [ ] **Step 4: Add markdown renderer**

Create `pubtator_link/mcp/catalog_docs.py`:

```python
from __future__ import annotations

from pubtator_link.mcp.catalog import build_tool_catalog
from pubtator_link.mcp.facade import create_pubtator_mcp


def render_tool_catalog_markdown() -> str:
    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    lines = [
        "# PubTator-Link MCP Tool Catalog",
        "",
        "Generated from runtime MCP catalog metadata. Do not edit by hand.",
        "",
    ]
    for name in sorted(catalog):
        entry = catalog[name]
        lines.extend(
            [
                f"## `{entry.name}`",
                "",
                f"- Title: {entry.title}",
                f"- Category: {entry.category}",
                f"- Profiles: {', '.join(entry.profiles)}",
                f"- Stability: {entry.stability}",
                f"- Description: {entry.description}",
                f"- Do not use for: {entry.do_not_use_for}",
                f"- Example: `{entry.example}`",
                f"- Has output schema: {entry.has_output_schema}",
                f"- Next tools: {', '.join(entry.next_tools) if entry.next_tools else 'none'}",
                f"- Resource links: {', '.join(entry.resource_links) if entry.resource_links else 'none'}",
                "",
            ]
        )
    return "\n".join(lines)
```

- [ ] **Step 5: Add generator script**

Create `scripts/generate_mcp_tool_catalog.py`:

```python
from __future__ import annotations

from pathlib import Path

from pubtator_link.mcp.catalog_docs import render_tool_catalog_markdown


def main() -> None:
    Path("docs/mcp-tool-catalog.md").write_text(render_tool_catalog_markdown())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Generate docs and run tests**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/mcp/catalog.py pubtator_link/mcp/catalog_docs.py scripts/generate_mcp_tool_catalog.py docs/mcp-tool-catalog.md tests/unit/mcp/test_mcp_tool_catalog.py
git commit -m "feat: generate MCP tool catalog"
```

## Task 4: Add Review Resource Templates

**Files:**
- Create: `pubtator_link/mcp/review_resources.py`
- Modify: `pubtator_link/mcp/metadata.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Create: `tests/unit/mcp/test_mcp_review_resources.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write failing resource tests**

Create `tests/unit/mcp/test_mcp_review_resources.py`:

```python
from __future__ import annotations


def test_review_resource_templates_are_registered() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="lean")
    templates = getattr(mcp._resource_manager, "_templates", {})
    template_uris = set(templates)

    assert "pubtator://reviews/{review_id}" in template_uris
    assert "pubtator://reviews/{review_id}/sessions" in template_uris
    assert "pubtator://reviews/{review_id}/sessions/{session_id}" in template_uris
    assert "pubtator://reviews/{review_id}/passages/{passage_id}" in template_uris
    assert "pubtator://reviews/{review_id}/audit" in template_uris
    assert "pubtator://reviews/{review_id}/audit/{passage_id}" in template_uris
    assert "pubtator://reviews/{review_id}/llm-context" in template_uris
    assert "pubtator://reviews/{review_id}/llm-context/latest" in template_uris
    assert "pubtator://capabilities/tools/{tool_name}" in template_uris


def test_tool_detail_resource_reads_catalog_entry() -> None:
    from pubtator_link.mcp.review_resources import get_tool_detail_resource

    payload = get_tool_detail_resource("pubtator.retrieve_review_context_batch")

    assert payload["name"] == "pubtator.retrieve_review_context_batch"
    assert payload["profile_visibility"]
    assert payload["description"].startswith("Use this when ")
```

- [ ] **Step 2: Run failing resource tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_review_resources.py -q
```

Expected: FAIL because resource templates do not exist.

- [ ] **Step 3: Add resource helpers**

Create `pubtator_link/mcp/review_resources.py` with pure helpers first:

```python
from __future__ import annotations

from typing import Any

from pubtator_link.mcp.catalog import build_tool_catalog
from pubtator_link.mcp.facade import create_pubtator_mcp


def get_tool_detail_resource(tool_name: str) -> dict[str, Any]:
    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    entry = catalog.get(tool_name)
    if entry is None:
        return {"error": {"code": "not_found", "message": f"Unknown tool: {tool_name}"}}
    return {
        "name": entry.name,
        "title": entry.title,
        "category": entry.category,
        "profile_visibility": list(entry.profiles),
        "stability": entry.stability,
        "description": entry.description,
        "do_not_use_for": entry.do_not_use_for,
        "example": entry.example,
        "next_tools": list(entry.next_tools),
        "resource_links": list(entry.resource_links),
    }
```

- [ ] **Step 4: Register resource templates**

In `pubtator_link/mcp/metadata.py`, register template functions with FastMCP
using parameterized `@mcp.resource("pubtator://.../{param}")` decorators. The
installed FastMCP version supports this and wires `resources/templates/list`.
The tool detail template should call `get_tool_detail_resource`.

Do not implement resource subscription in this task. The installed MCP SDK
advertises `subscribe=False`; defer subscriptions instead of adding a low-level
compatibility shim.

- [ ] **Step 5: Add review resource service adapters**

Add helpers in `pubtator_link/mcp/service_adapters.py` for:

- review summary resource
- sessions list resource
- session detail resource
- passage detail resource
- compact audit summary resource
- passage audit resource
- LLM context resource placeholder returning empty context until Task 7

Each helper returns bounded dictionaries and never calls upstream APIs.

- [ ] **Step 6: Run resource and facade tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_review_resources.py tests/unit/mcp/test_mcp_facade.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/mcp tests/unit/mcp/test_mcp_review_resources.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add MCP review resource templates"
```

## Task 5: Add Resource Links To Retrieval Responses

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing next-context test**

Add to `tests/unit/test_review_context_service.py`:

```python
async def test_batch_retrieval_returns_next_context_resource_links() -> None:
    service, repository = make_review_context_service_with_passages()

    result = await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(queries=["mefv colchicine"], max_total_passages=2),
    )

    assert result.next_context_options
    option = result.next_context_options[0]
    assert option.kind in {"passage", "neighboring_passages", "audit"}
    assert option.resource.startswith("pubtator://reviews/review-1/")
```

Adjust helper names to match the existing test fixture patterns in
`tests/unit/test_review_context_service.py`.

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py::test_batch_retrieval_returns_next_context_resource_links -q
```

Expected: FAIL because `next_context_options` does not exist.

- [ ] **Step 3: Add model**

In `pubtator_link/models/review_rerag.py`, add:

```python
NextContextKind = Literal["passage", "neighboring_passages", "audit", "llm_context"]


class NextContextOption(BaseModel):
    kind: NextContextKind
    resource: str
    reason: str
```

Add `next_context_options: list[NextContextOption] = Field(default_factory=list)`
to `RetrieveReviewContextBatchResponse`.

- [ ] **Step 4: Populate links**

In `ReviewContextService.retrieve_context_batch`, after merged passages are
known, create links for selected passage IDs:

```python
next_context_options = []
for passage in merged.context_pack.passages[:5]:
    next_context_options.extend(
        [
            NextContextOption(
                kind="passage",
                resource=f"pubtator://reviews/{review_id}/passages/{passage.passage_id}",
                reason="Load the exact prepared passage as resource context.",
            ),
            NextContextOption(
                kind="neighboring_passages",
                resource=f"pubtator://reviews/{review_id}/passages/{passage.passage_id}?before=1&after=1",
                reason="Expand local context around a cited passage.",
            ),
            NextContextOption(
                kind="audit",
                resource=f"pubtator://reviews/{review_id}/audit/{passage.passage_id}",
                reason="Load compact audit data for this passage.",
            ),
        ]
    )
```

If `session_id` is present, include it as a query parameter.

- [ ] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pubtator_link/models/review_rerag.py pubtator_link/services/review_context_service.py tests/unit/test_review_context_service.py
git commit -m "feat: return review resource links from retrieval"
```

## Task 6: Add Durable LLM Context Schema And Repository

**Files:**
- Modify: `pubtator_link/db/review_schema.sql`
- Create: `pubtator_link/db/migrations/0004_review_llm_context.sql`
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/repositories/review_rerag.py`
- Modify: `tests/unit/test_review_schema_sql.py`
- Modify: `tests/unit/test_review_rerag_repository.py`
- Modify: `tests/integration/test_review_schema_postgres.py`

- [ ] **Step 1: Write failing schema tests**

Add assertions to `tests/unit/test_review_schema_sql.py`:

```python
def test_review_llm_context_tables_are_declared() -> None:
    schema = Path("pubtator_link/db/review_schema.sql").read_text()

    assert "CREATE TABLE IF NOT EXISTS review_llm_context" in schema
    assert "CREATE TABLE IF NOT EXISTS review_llm_context_events" in schema
    assert "CREATE INDEX IF NOT EXISTS idx_review_llm_context_events_review" in schema
```

- [ ] **Step 2: Run failing schema test**

Run:

```bash
uv run pytest tests/unit/test_review_schema_sql.py::test_review_llm_context_tables_are_declared -q
```

Expected: FAIL.

- [ ] **Step 3: Add SQL schema**

Add to `review_schema.sql` and migration `0004_review_llm_context.sql`:

```sql
CREATE TABLE IF NOT EXISTS review_llm_context (
    context_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_id TEXT NOT NULL,
    session_id TEXT,
    kind TEXT NOT NULL DEFAULT 'retrieval_context',
    topic TEXT,
    research_question TEXT,
    question_hash TEXT,
    request JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    selected_pmids TEXT[] NOT NULL DEFAULT '{}',
    rejected_pmids TEXT[] NOT NULL DEFAULT '{}',
    preferred_entity_ids TEXT[] NOT NULL DEFAULT '{}',
    active_queries TEXT[] NOT NULL DEFAULT '{}',
    successful_queries TEXT[] NOT NULL DEFAULT '{}',
    failed_queries TEXT[] NOT NULL DEFAULT '{}',
    selected_passage_ids TEXT[] NOT NULL DEFAULT '{}',
    audit_passage_ids TEXT[] NOT NULL DEFAULT '{}',
    open_questions JSONB NOT NULL DEFAULT '[]'::jsonb,
    user_decisions JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_next_commands JSONB NOT NULL DEFAULT '[]'::jsonb,
    stable_citation_keys JSONB NOT NULL DEFAULT '{}'::jsonb,
    cache_key TEXT,
    token_estimate INTEGER,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_llm_context_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    context_id UUID REFERENCES review_llm_context(context_id) ON DELETE CASCADE,
    review_id TEXT NOT NULL,
    session_id TEXT,
    event_type TEXT NOT NULL,
    summary TEXT,
    pmids TEXT[] NOT NULL DEFAULT '{}',
    passage_ids TEXT[] NOT NULL DEFAULT '{}',
    queries TEXT[] NOT NULL DEFAULT '{}',
    decision JSONB,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_events_review
    ON review_llm_context_events (review_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_review_latest
    ON review_llm_context (review_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_llm_context_session_latest
    ON review_llm_context (review_id, session_id, created_at DESC);
```

- [ ] **Step 4: Add models**

In `models/review_rerag.py`, add `ReviewLlmContext`, `ReviewLlmContextEvent`,
`RecordReviewContextRequest`, and `RecordReviewContextResponse` Pydantic models
with bounded list defaults, compact `request` / `response_summary` dictionaries,
`token_estimate`, and event type literals from the design. Models should store
passage IDs and summaries by default, not article text.

- [ ] **Step 5: Add repository methods**

Extend repository protocol and implementation with:

```python
async def record_llm_context_event(
    self,
    review_id: str,
    request: RecordReviewContextRequest,
) -> RecordReviewContextResponse:
    ...

async def get_latest_llm_context(
    self, review_id: str, *, session_id: str | None = None
) -> ReviewLlmContext | None:
    ...
```

The implementation inserts a compact context snapshot and event in one
transaction. Existing `record_review_audit_event` remains unchanged for audit
bundles.

- [ ] **Step 6: Run schema and repository tests**

Run:

```bash
uv run pytest tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/integration/test_review_schema_postgres.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/db pubtator_link/models/review_rerag.py pubtator_link/repositories/review_rerag.py tests/unit/test_review_schema_sql.py tests/unit/test_review_rerag_repository.py tests/integration/test_review_schema_postgres.py
git commit -m "feat: add durable review LLM context schema"
```

## Task 7: Expose LLM Context Service, Resource, And Tool

**Files:**
- Create: `pubtator_link/services/llm_review_context.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/mcp/review_resources.py`
- Create: `tests/unit/test_llm_review_context_service.py`
- Modify: `tests/unit/mcp/test_mcp_profiles.py`
- Modify: `tests/unit/mcp/test_mcp_review_resources.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/unit/test_llm_review_context_service.py`:

```python
from __future__ import annotations

import pytest

from pubtator_link.models.review_rerag import RecordReviewContextRequest
from pubtator_link.services.llm_review_context import LlmReviewContextService


@pytest.mark.asyncio
async def test_record_context_rejects_empty_event() -> None:
    service = LlmReviewContextService(repository=None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="summary, pmids, passage_ids, queries, or decision"):
        await service.record_context(
            "review-1",
            RecordReviewContextRequest(event_type="decision_recorded"),
        )
```

- [ ] **Step 2: Run failing service test**

Run:

```bash
uv run pytest tests/unit/test_llm_review_context_service.py -q
```

Expected: FAIL because service does not exist.

- [ ] **Step 3: Add service**

Create `pubtator_link/services/llm_review_context.py`:

```python
from __future__ import annotations

from typing import Protocol

from pubtator_link.models.review_rerag import (
    RecordReviewContextRequest,
    RecordReviewContextResponse,
    ReviewLlmContext,
)


class LlmReviewContextRepository(Protocol):
    async def record_llm_context_event(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        ...

    async def get_latest_llm_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        ...


class LlmReviewContextService:
    def __init__(self, repository: LlmReviewContextRepository) -> None:
        self.repository = repository

    async def record_context(
        self, review_id: str, request: RecordReviewContextRequest
    ) -> RecordReviewContextResponse:
        if not any(
            [
                request.summary,
                request.pmids,
                request.passage_ids,
                request.queries,
                request.decision,
            ]
        ):
            raise ValueError("summary, pmids, passage_ids, queries, or decision is required")
        return await self.repository.record_llm_context_event(review_id, request)

    async def get_context(
        self, review_id: str, *, session_id: str | None = None
    ) -> ReviewLlmContext | None:
        return await self.repository.get_latest_llm_context(review_id, session_id=session_id)
```

- [ ] **Step 4: Add MCP adapter and tool**

Add `record_review_context_impl` in `mcp/service_adapters.py`, register
`pubtator.record_review_context` in `mcp/tools/review.py`, and include
`output_schema=RecordReviewContextResponse.model_json_schema()`.

- [ ] **Step 5: Wire resource**

Update `pubtator_link/mcp/review_resources.py` and template registration so
`pubtator://reviews/{review_id}/llm-context` and
`pubtator://reviews/{review_id}/llm-context/latest` return the latest compact
context or an empty typed context with `review_id`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_llm_review_context_service.py tests/unit/mcp/test_mcp_profiles.py tests/unit/mcp/test_mcp_review_resources.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/services/llm_review_context.py pubtator_link/api/routes/dependencies.py pubtator_link/mcp pubtator_link/models/review_rerag.py tests/unit/test_llm_review_context_service.py tests/unit/mcp
git commit -m "feat: expose review LLM context over MCP"
```

## Task 8: Reduce Batch Retrieval Shared Reads

**Files:**
- Modify: `pubtator_link/services/review_context_service.py`
- Modify: `pubtator_link/services/review_context/diagnostics.py`
- Modify: `tests/unit/test_review_context_service.py`

- [ ] **Step 1: Write failing repository-call test**

Add a counting fake repository test in `tests/unit/test_review_context_service.py`:

```python
async def test_batch_retrieval_reads_shared_state_once_per_batch() -> None:
    service, repository = make_counting_review_context_service()

    await service.retrieve_context_batch(
        "review-1",
        RetrieveReviewContextBatchRequest(
            queries=["query one", "query two", "query three"],
            include_diagnostics=True,
        ),
    )

    assert repository.calls["preparation_status"] == 1
    assert repository.calls["indexed_pmids"] == 1
    assert repository.calls["available_sections"] == 1
    assert repository.calls["list_review_failed_sources"] == 1
```

Use existing fake repository patterns in the test file. Count only the methods
that currently repeat per query.

- [ ] **Step 2: Run failing test**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py::test_batch_retrieval_reads_shared_state_once_per_batch -q
```

Expected: FAIL because batch calls single retrieval repeatedly.

- [ ] **Step 3: Add shared batch state object**

In `review_context_service.py`, add a bounded snapshot dataclass:

```python
@dataclass(frozen=True)
class ReviewRetrievalSnapshot:
    preparation_status: PreparationStatus
    prepared_pmids: list[str]
    still_preparing_pmids: list[str]
    failed_pmids: list[str]
    indexed_pmids: list[str]
    available_sections: list[str]
    source_summaries: list[ReviewSourceSummary]
    failed_sources: list[FailedSourceSummary]
```

- [ ] **Step 4: Fetch shared state once**

At the start of `retrieve_context_batch()`, after session validation, fetch the
shared state once with `asyncio.gather()` where safe:

```python
status, preparation_pmids, indexed_pmids, available_sections, source_summaries, failed_sources = await asyncio.gather(
    self._preparation_status(review_id, session_id=request.session_id),
    self._preparation_pmids(review_id, session_id=request.session_id),
    self.repository.indexed_pmids(review_id, session_id=request.session_id),
    self.repository.available_sections(review_id, session_id=request.session_id),
    self.repository.list_review_sources(review_id, session_id=request.session_id),
    self.repository.list_review_failed_sources(review_id, session_id=request.session_id),
)
```

Pass this state into the per-query retrieval assembly so individual queries do
not repeat the same status reads.

- [ ] **Step 5: Preserve bounded parallel search**

Keep the existing semaphore around per-query `search_passages` calls. Do not
increase default concurrency. Do not submit unbounded tasks.

- [ ] **Step 6: Run focused tests**

Run:

```bash
uv run pytest tests/unit/test_review_context_service.py tests/unit/test_review_context_diagnostics.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add pubtator_link/services/review_context_service.py pubtator_link/services/review_context/diagnostics.py tests/unit/test_review_context_service.py
git commit -m "perf: share review batch retrieval state reads"
```

## Task 9: Documentation Cleanup

**Files:**
- Modify: `README.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `docs/2026-05-02-pubtator-link-consolidated-roadmap.md`
- Modify: `docs/mcp-tool-catalog.md`

- [ ] **Step 1: Search for stale guidance**

Run:

```bash
rg -n "_v2|prepare_mode|retrieve_review_context\\b|review_quickstart" README.md docs pubtator_link
```

Expected: identify stale public guidance. Keep source-code compatibility only
where needed; update docs to point to lean profile, batch retrieval, resources,
and durable context.

- [ ] **Step 2: Update docs**

Change public docs to state:

- Default MCP profile is `lean`.
- Use `PUBTATOR_LINK_MCP_PROFILE=full` for advanced/compat tools.
- Use `PUBTATOR_LINK_MCP_PROFILE=readonly` for read-only hosted research.
- Prefer `retrieve_review_context_batch`.
- Prefer resource templates for review/session/passage/audit state.
- Use `record_review_context` for durable review decisions.

- [ ] **Step 3: Run docs/catalog tests**

Run:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
uv run pytest tests/unit/mcp/test_mcp_tool_catalog.py -q
```

Expected: PASS and no unintended catalog diff after generation.

- [ ] **Step 4: Commit**

Run:

```bash
git add README.md docs scripts/generate_mcp_tool_catalog.py
git commit -m "docs: document lean MCP profile and resources"
```

## Task 10: Final Verification

**Files:**
- No source files modified unless verification finds a bug.

- [ ] **Step 1: Run formatting**

Run:

```bash
make format
```

Expected: Ruff formatting completes.

- [ ] **Step 2: Run local CI**

Run:

```bash
make ci-local
```

Expected: formatting, linting, type checking, and tests pass.

- [ ] **Step 3: Inspect final diff**

Run:

```bash
git status --short
git diff --stat main...HEAD
```

Expected: only scoped modernization files changed.

- [ ] **Step 4: Final commit if needed**

If verification fixes changed files, run:

```bash
git add .
git commit -m "chore: verify MCP modernization foundation"
```

Expected: branch contains clean, reviewed commits.

## Self-Review Checklist

- Spec coverage: Tasks 1-3 cover lean profile, token-efficient catalog, and output schema cleanup. Tasks 4-5 cover resource templates and resource links. Tasks 6-7 cover durable LLM context. Task 8 covers batch shared reads and bounded parallelism. Task 9 covers cleanup. Task 10 covers verification.
- Placeholder scan: no task uses TBD/TODO/fill-in placeholders as acceptance criteria.
- Type consistency: profile names are `lean`, `full`, `readonly`; context tool is `pubtator.record_review_context`; resource URIs match the design spec.
- Scope check: hosted OAuth, semantic vector search, local-file roots, and full cancellation/progress transport work are intentionally out of this plan.
