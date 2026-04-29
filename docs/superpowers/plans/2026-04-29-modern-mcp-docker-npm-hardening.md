# PubTator-Link Modern MCP And Docker NPM Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modernize PubTator-Link into a hosted Streamable HTTP MCP server with a curated research-use tool surface, and harden the Docker deployment so it works cleanly behind Nginx Proxy Manager like `../gtex-link`.

**Architecture:** Keep FastAPI as the REST backend and expose MCP as a first-class FastMCP facade instead of a raw OpenAPI conversion. Serve the facade at `/mcp` over Streamable HTTP in unified and container deployments, while keeping stdio as a local fallback. Harden the container with a non-root runtime, deterministic dependency resolution, health checks, read-only-compatible filesystem paths, Compose security options, and an NPM shared-network override.

**Tech Stack:** Python 3.11+, FastAPI, FastMCP 3.x, MCP Python SDK 1.27+, Pydantic 2, httpx, uvicorn/gunicorn, pytest, Ruff, mypy, uv, Docker BuildKit, Docker Compose, Nginx Proxy Manager.

---

## File Structure

- Modify `pyproject.toml`: fix Python compatibility, pin modern MCP/FastMCP ranges, add optional test/security tooling.
- Create `uv.lock`: deterministic dependency resolution.
- Create `pubtator_link/mcp/__init__.py`: MCP package marker.
- Create `pubtator_link/mcp/tools.py`: Pydantic request/response models for curated MCP tools.
- Create `pubtator_link/mcp/facade.py`: first-class FastMCP server, tool registration, resource registration, prompt registration.
- Create `pubtator_link/mcp/resources.py`: static capability, bioconcept, relation type, format, and compliance resources.
- Create `pubtator_link/mcp/prompts.py`: short user-invoked research workflow prompts.
- Modify `pubtator_link/server_manager.py`: mount curated MCP HTTP facade at `/mcp`, keep legacy OpenAPI conversion behind a compatibility helper.
- Modify `server.py`: ensure CLI unified mode starts REST plus MCP and HTTP mode remains REST-only.
- Modify `mcp_server.py`: keep stdio mode pointed at the curated facade.
- Create `tests/unit/mcp/test_mcp_facade.py`: tool, resource, prompt metadata tests.
- Create `tests/integration/test_mcp_http_protocol.py`: Streamable HTTP JSON-RPC smoke tests.
- Create `tests/unit/test_package_resolution.py`: guard Python version metadata and dependency floor.
- Modify `docker/Dockerfile`: harden build and runtime image.
- Modify `docker/gunicorn_conf.py`: proxy-aware production settings and safer worker defaults.
- Modify `docker/docker-compose.yml`: development Compose aligned with the modern server command.
- Modify `docker/docker-compose.prod.yml`: production resource/security controls.
- Create `docker/docker-compose.npm.yml`: Nginx Proxy Manager shared network deployment.
- Create `docker/.env.npm.example`: NPM deployment variables.
- Modify `docker/README.md`: document NPM proxy host setup and hardening tradeoffs.
- Modify `docs/MCP_CONNECTION_GUIDE.md`: HTTP-first Streamable HTTP setup for Claude and ChatGPT.
- Modify `README.md`: update MCP and Docker quick starts.

---

## Task 1: Fix Dependency Resolution Baseline

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/unit/test_package_resolution.py`
- Create: `uv.lock`

- [ ] **Step 1: Add failing metadata tests**

Create `tests/unit/test_package_resolution.py`:

```python
"""Packaging guardrails for supported runtime dependencies."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _project_metadata() -> dict[str, object]:
    return tomllib.loads(Path("pyproject.toml").read_text())["project"]


def test_project_requires_python_311_or_newer() -> None:
    metadata = _project_metadata()

    assert metadata["requires-python"] == ">=3.11"


def test_modern_mcp_dependencies_are_declared() -> None:
    metadata = _project_metadata()
    dependencies = "\n".join(metadata["dependencies"])

    assert "mcp[cli]>=1.27.0,<2.0.0" in dependencies
    assert "fastmcp>=3.2.0,<4.0.0" in dependencies
    assert "fastapi>=0.115.0,<1.0.0" in dependencies
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
pytest tests/unit/test_package_resolution.py -q
```

Expected: fail because `requires-python` is `>=3.9` and MCP/FastMCP dependency ranges are too loose.

- [ ] **Step 3: Update package metadata**

In `pyproject.toml`, replace the project Python version and dependency section values:

```toml
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: MIT License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Bio-Informatics",
    "Topic :: Software Development :: Libraries :: Python Modules",
]
dependencies = [
    "fastapi>=0.115.0,<1.0.0",
    "uvicorn[standard]>=0.32.0,<1.0.0",
    "pydantic>=2.10.0,<3.0.0",
    "pydantic-settings>=2.6.0,<3.0.0",
    "httpx>=0.28.0,<1.0.0",
    "async-lru>=2.0.4,<3.0.0",
    "structlog>=24.4.0,<26.0.0",
    "orjson>=3.10.0,<4.0.0",
    "beautifulsoup4>=4.12.0,<5.0.0",
    "lxml>=5.2.0,<7.0.0",
    "rich>=13.9.0,<15.0.0",
    "typer[rich]>=0.12.0,<1.0.0",
    "mcp[cli]>=1.27.0,<2.0.0",
    "fastmcp>=3.2.0,<4.0.0",
    "gunicorn>=23.0.0,<24.0.0",
]
```

Also update:

```toml
[tool.ruff]
target-version = "py311"

[tool.mypy]
python_version = "3.11"
```

- [ ] **Step 4: Lock dependencies**

Run:

```bash
uv lock
```

Expected: creates `uv.lock` and succeeds without Python 3.9 resolution errors.

- [ ] **Step 5: Verify package tests**

Run:

```bash
uv run pytest tests/unit/test_package_resolution.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock tests/unit/test_package_resolution.py
git commit -m "chore: modernize python and mcp dependency baseline"
```

---

## Task 2: Add A Curated PubTator MCP Facade

**Files:**
- Create: `pubtator_link/mcp/__init__.py`
- Create: `pubtator_link/mcp/tools.py`
- Create: `pubtator_link/mcp/resources.py`
- Create: `pubtator_link/mcp/prompts.py`
- Create: `pubtator_link/mcp/facade.py`
- Create: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Write facade registration tests**

Create `tests/unit/mcp/test_mcp_facade.py`:

```python
from __future__ import annotations


def test_curated_facade_registers_pubtator_tools() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tool_names = set(mcp._tool_manager._tools.keys())

    assert "pubtator.search_literature" in tool_names
    assert "pubtator.fetch_publication_annotations" in tool_names
    assert "pubtator.fetch_pmc_annotations" in tool_names
    assert "pubtator.search_biomedical_entities" in tool_names
    assert "pubtator.find_entity_relations" in tool_names
    assert "pubtator.submit_text_annotation" in tool_names
    assert "pubtator.get_text_annotation_results" in tool_names
    assert "pubtator.get_server_capabilities" in tool_names
    assert "pubtator.clear_api_cache" not in tool_names


def test_curated_facade_registers_resources_and_prompts() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()

    assert "pubtator://capabilities" in mcp._resource_manager._resources
    assert "pubtator://bioconcepts" in mcp._resource_manager._resources
    assert "pubtator://compliance/research-use" in mcp._resource_manager._resources
    assert "search_biomedical_literature" in mcp._prompt_manager._prompts
    assert "annotate_research_text" in mcp._prompt_manager._prompts


def test_tool_metadata_is_research_scoped() -> None:
    from pubtator_link.mcp.resources import RESEARCH_USE_NOTICE

    assert "not for diagnosis" in RESEARCH_USE_NOTICE
    assert "clinical decision support" in RESEARCH_USE_NOTICE
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: fail because `pubtator_link.mcp` does not exist.

- [ ] **Step 3: Add MCP package marker**

Create `pubtator_link/mcp/__init__.py`:

```python
"""Curated MCP surface for PubTator-Link."""
```

- [ ] **Step 4: Add request schemas**

Create `pubtator_link/mcp/tools.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SearchLiteratureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    page: int = Field(default=1, ge=1, le=1000)
    sort: str | None = Field(default=None, description="Examples: 'score desc', 'date desc'.")
    filters: str | None = Field(default=None, description="Optional PubTator search filters as JSON.")
    sections: str | None = Field(default=None, description="Comma-separated document sections.")


class FetchPublicationAnnotationsRequest(BaseModel):
    pmids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson"
    full: bool = False


class FetchPmcAnnotationsRequest(BaseModel):
    pmcids: list[str] = Field(min_length=1, max_length=50)
    format: Literal["biocxml", "biocjson"] = "biocjson"


class SearchBiomedicalEntitiesRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"] | None = None
    limit: int = Field(default=10, ge=1, le=100)


class FindEntityRelationsRequest(BaseModel):
    entity_id: str = Field(min_length=1, description="PubTator entity ID such as @CHEMICAL_remdesivir.")
    relation_type: str | None = None
    target_entity_type: str | None = None


class SubmitTextAnnotationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    bioconcepts: str = Field(default="Gene", description="Comma-separated PubTator bioconcepts or 'all'.")


class GetTextAnnotationResultsRequest(BaseModel):
    session_id: str = Field(min_length=8)
```

- [ ] **Step 5: Add resources**

Create `pubtator_link/mcp/resources.py`:

```python
from __future__ import annotations

from typing import Any

from pubtator_link.config import api_config, text_processing_config

RESEARCH_USE_NOTICE = (
    "Research and biomedical literature exploration use only; not for diagnosis, "
    "treatment, triage, patient management, or clinical decision support. Do not "
    "submit identifiable patient data to public demo instances."
)


def get_capabilities_resource() -> dict[str, Any]:
    return {
        "server": "pubtator-link",
        "transport": "streamable_http",
        "endpoint": "/mcp",
        "tools": [
            "pubtator.search_literature",
            "pubtator.fetch_publication_annotations",
            "pubtator.fetch_pmc_annotations",
            "pubtator.search_biomedical_entities",
            "pubtator.find_entity_relations",
            "pubtator.submit_text_annotation",
            "pubtator.get_text_annotation_results",
            "pubtator.get_server_capabilities",
        ],
        "notice": RESEARCH_USE_NOTICE,
    }


def get_bioconcepts_resource() -> dict[str, Any]:
    return {"bioconcepts": list(api_config.bioconcept_types)}


def get_relation_types_resource() -> dict[str, Any]:
    return {"relation_types": list(api_config.relation_types)}


def get_formats_resource() -> dict[str, Any]:
    return {"publication_formats": list(api_config.export_formats)}


def get_research_use_resource() -> dict[str, str]:
    return {"notice": RESEARCH_USE_NOTICE}


def get_text_processing_resource() -> dict[str, Any]:
    return {"supported_bioconcepts": list(text_processing_config.supported_bioconcepts)}
```

- [ ] **Step 6: Add prompts**

Create `pubtator_link/mcp/prompts.py`:

```python
from __future__ import annotations

from pubtator_link.mcp.resources import RESEARCH_USE_NOTICE


def search_biomedical_literature_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Use pubtator.search_literature to find relevant "
        "PubMed literature. Use pubtator.search_biomedical_entities first when the "
        "query needs a canonical PubTator entity identifier. Summarize PMIDs, titles, "
        "entity IDs, and limits of the retrieval."
    )


def annotate_research_text_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Use pubtator.submit_text_annotation for biomedical "
        "named entity recognition in research text, then poll pubtator.get_text_annotation_results "
        "with the returned session_id. Report extracted entities as suggestions, not clinical facts."
    )


def review_pubtator_annotations_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Review returned PubTator annotations against the supplied "
        "research text. Flag unsupported, ambiguous, or context-mismatched entity suggestions."
    )
```

- [ ] **Step 7: Add facade skeleton**

Create `pubtator_link/mcp/facade.py`:

```python
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.prompts import (
    annotate_research_text_prompt,
    review_pubtator_annotations_prompt,
    search_biomedical_literature_prompt,
)
from pubtator_link.mcp.resources import (
    RESEARCH_USE_NOTICE,
    get_bioconcepts_resource,
    get_capabilities_resource,
    get_formats_resource,
    get_relation_types_resource,
    get_research_use_resource,
    get_text_processing_resource,
)
from pubtator_link.mcp.tools import (
    FetchPmcAnnotationsRequest,
    FetchPublicationAnnotationsRequest,
    FindEntityRelationsRequest,
    GetTextAnnotationResultsRequest,
    SearchBiomedicalEntitiesRequest,
    SearchLiteratureRequest,
    SubmitTextAnnotationRequest,
)


def create_pubtator_mcp() -> FastMCP:
    mcp = FastMCP(
        name="pubtator-link",
        instructions=(
            "PubTator-Link exposes PubTator3 biomedical literature, entity, relation, "
            f"and text annotation capabilities. {RESEARCH_USE_NOTICE}"
        ),
    )

    @mcp.tool(name="pubtator.get_server_capabilities", title="Get PubTator-Link Capabilities")
    def get_server_capabilities() -> dict[str, Any]:
        """Use this when a client needs supported tools, transports, formats, and limitations."""
        return get_capabilities_resource()

    @mcp.tool(name="pubtator.search_literature", title="Search Biomedical Literature")
    async def search_literature(request: SearchLiteratureRequest) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.fetch_publication_annotations", title="Fetch Publication Annotations")
    async def fetch_publication_annotations(request: FetchPublicationAnnotationsRequest) -> dict[str, Any]:
        """Use this when a user provides PubMed IDs and needs PubTator annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.fetch_pmc_annotations", title="Fetch PMC Annotations")
    async def fetch_pmc_annotations(request: FetchPmcAnnotationsRequest) -> dict[str, Any]:
        """Use this when a user provides PMC IDs and needs PubTator full-text annotations. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.search_biomedical_entities", title="Search Biomedical Entities")
    async def search_biomedical_entities(request: SearchBiomedicalEntitiesRequest) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.find_entity_relations", title="Find Entity Relations")
    async def find_entity_relations(request: FindEntityRelationsRequest) -> dict[str, Any]:
        """Use this when a user has a PubTator entity ID and needs literature-derived related entities. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.submit_text_annotation", title="Submit Text Annotation")
    async def submit_text_annotation(request: SubmitTextAnnotationRequest) -> dict[str, Any]:
        """Use this when research text should be submitted for PubTator biomedical named entity recognition. Do not submit identifiable patient data to public demo instances."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.tool(name="pubtator.get_text_annotation_results", title="Get Text Annotation Results")
    async def get_text_annotation_results(request: GetTextAnnotationResultsRequest) -> dict[str, Any]:
        """Use this when a user has a PubTator text annotation session ID and needs its results."""
        raise NotImplementedError("Task 3 wires this tool to PubTator3 services.")

    @mcp.resource("pubtator://capabilities")
    def capabilities() -> dict[str, Any]:
        return get_capabilities_resource()

    @mcp.resource("pubtator://bioconcepts")
    def bioconcepts() -> dict[str, Any]:
        return get_bioconcepts_resource()

    @mcp.resource("pubtator://relation-types")
    def relation_types() -> dict[str, Any]:
        return get_relation_types_resource()

    @mcp.resource("pubtator://formats")
    def formats() -> dict[str, Any]:
        return get_formats_resource()

    @mcp.resource("pubtator://text-processing")
    def text_processing() -> dict[str, Any]:
        return get_text_processing_resource()

    @mcp.resource("pubtator://compliance/research-use")
    def research_use() -> dict[str, str]:
        return get_research_use_resource()

    @mcp.prompt(name="search_biomedical_literature", title="Search Biomedical Literature")
    def search_literature_prompt() -> str:
        return search_biomedical_literature_prompt()

    @mcp.prompt(name="annotate_research_text", title="Annotate Research Text")
    def annotate_text_prompt() -> str:
        return annotate_research_text_prompt()

    @mcp.prompt(name="review_pubtator_annotations", title="Review PubTator Annotations")
    def review_annotations_prompt() -> str:
        return review_pubtator_annotations_prompt()

    return mcp
```

- [ ] **Step 8: Verify registration tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add pubtator_link/mcp tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add curated pubtator mcp facade"
```

---

## Task 3: Wire Curated Tools To Existing Services

**Files:**
- Modify: `pubtator_link/mcp/facade.py`
- Create: `pubtator_link/mcp/service_adapters.py`
- Create: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write adapter tests with injected fake client**

Create `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_search_entities_adapter_calls_client() -> None:
    from pubtator_link.mcp.service_adapters import search_biomedical_entities_impl
    from pubtator_link.mcp.tools import SearchBiomedicalEntitiesRequest

    class FakeClient:
        async def autocomplete_entity(self, query: str, concept: str | None, limit: int) -> list[dict[str, object]]:
            return [{"_id": "@GENE_672", "name": "BRCA1", "biotype": "Gene", "score": 1.0}]

    result = await search_biomedical_entities_impl(
        SearchBiomedicalEntitiesRequest(query="BRCA1", concept="Gene"),
        client=FakeClient(),
    )

    assert result["success"] is True
    assert result["matches"][0]["identifier"] == "@GENE_672"


@pytest.mark.asyncio
async def test_publication_adapter_validates_pmids() -> None:
    from pubtator_link.mcp.service_adapters import fetch_publication_annotations_impl
    from pubtator_link.mcp.tools import FetchPublicationAnnotationsRequest

    class FakeService:
        async def export_publications_list(self, pmids: list[str], format: str, full: bool) -> dict[str, object]:
            return {"pmids": pmids, "format": format, "full_text": full, "count": len(pmids)}

    result = await fetch_publication_annotations_impl(
        FetchPublicationAnnotationsRequest(pmids=["29355051"], format="biocjson"),
        service=FakeService(),
    )

    assert result["pmids"] == ["29355051"]
    assert result["format"] == "biocjson"
```

- [ ] **Step 2: Run failing adapter tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py -q
```

Expected: fail because `service_adapters.py` does not exist.

- [ ] **Step 3: Add service adapters**

Create `pubtator_link/mcp/service_adapters.py`:

```python
from __future__ import annotations

from typing import Any

from pubtator_link.api.client import PubTator3Client
from pubtator_link.models.responses import EntityMatch, EntityAutocompleteResponse
from pubtator_link.mcp.tools import (
    FetchPublicationAnnotationsRequest,
    SearchBiomedicalEntitiesRequest,
)
from pubtator_link.services.publication_service import PublicationService


async def search_biomedical_entities_impl(
    request: SearchBiomedicalEntitiesRequest,
    *,
    client: PubTator3Client,
) -> dict[str, Any]:
    raw_results = await client.autocomplete_entity(
        query=request.query.strip(),
        concept=request.concept,
        limit=request.limit,
    )
    matches = [
        EntityMatch(
            identifier=item.get("_id", ""),
            name=item.get("name", ""),
            type=item.get("biotype", request.concept or "Unknown"),
            score=item.get("score"),
            synonyms=item.get("synonyms", []),
            db_id=item.get("db_id"),
            db=item.get("db"),
            match=item.get("match"),
        ).model_dump()
        for item in raw_results
    ]
    return EntityAutocompleteResponse(
        success=True,
        query=request.query.strip(),
        matches=matches,
        total_matches=len(matches),
        concept_filter=request.concept,
    ).model_dump()


async def fetch_publication_annotations_impl(
    request: FetchPublicationAnnotationsRequest,
    *,
    service: PublicationService,
) -> dict[str, Any]:
    result = await service.export_publications_list(
        pmids=request.pmids,
        format=request.format,
        full=request.full,
    )
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return dict(result)
```

- [ ] **Step 4: Wire facade to adapters**

In `pubtator_link/mcp/facade.py`, import adapters and application services:

```python
from pubtator_link.api.client import PubTator3Client
from pubtator_link.mcp.service_adapters import (
    fetch_publication_annotations_impl,
    search_biomedical_entities_impl,
)
from pubtator_link.services.publication_service import PublicationService
```

Replace `search_biomedical_entities` body:

```python
        async with PubTator3Client() as client:
            return await search_biomedical_entities_impl(request, client=client)
```

Replace `fetch_publication_annotations` body:

```python
        async with PubTator3Client() as client:
            service = PublicationService(client=client)
            return await fetch_publication_annotations_impl(request, service=service)
```

- [ ] **Step 5: Add remaining adapters incrementally**

Add the remaining adapter functions in `service_adapters.py`, each with a fake-client test before implementation:

```python
async def search_literature_impl(request: SearchLiteratureRequest, *, client: PubTator3Client) -> dict[str, Any]: ...
async def fetch_pmc_annotations_impl(request: FetchPmcAnnotationsRequest, *, service: PublicationService) -> dict[str, Any]: ...
async def find_entity_relations_impl(request: FindEntityRelationsRequest, *, client: PubTator3Client) -> dict[str, Any]: ...
async def submit_text_annotation_impl(request: SubmitTextAnnotationRequest, *, client: PubTator3Client) -> dict[str, Any]: ...
async def get_text_annotation_results_impl(request: GetTextAnnotationResultsRequest, *, client: PubTator3Client) -> dict[str, Any]: ...
```

Use the existing route modules as the behavioral reference:

- `pubtator_link/api/routes/search.py`
- `pubtator_link/api/routes/publications.py`
- `pubtator_link/api/routes/relations.py`
- `pubtator_link/api/routes/annotations.py`

- [ ] **Step 6: Run adapter and route tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/test_routes -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/service_adapters.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: wire pubtator mcp tools to services"
```

---

## Task 4: Serve Streamable HTTP MCP At `/mcp`

**Files:**
- Modify: `pubtator_link/server_manager.py`
- Modify: `mcp_server.py`
- Create: `tests/integration/test_mcp_http_protocol.py`
- Modify: `tests/unit/test_server_manager.py` if present or create focused equivalent.

- [ ] **Step 1: Write HTTP protocol smoke test**

Create `tests/integration/test_mcp_http_protocol.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_unified_app_mounts_streamable_http_mcp() -> None:
    from pubtator_link.server_manager import UnifiedServerManager

    manager = UnifiedServerManager()
    app = manager.create_app(include_mcp=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        initialize = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )

        assert initialize.status_code in {200, 202}

        tools = client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

    assert tools.status_code == 200
    names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    assert "pubtator.search_literature" in names
    assert "pubtator.clear_api_cache" not in names
```

- [ ] **Step 2: Run failing smoke test**

Run:

```bash
uv run pytest tests/integration/test_mcp_http_protocol.py -q
```

Expected: fail because `create_app(include_mcp=True)` does not exist and the current global ASGI app does not mount MCP.

- [ ] **Step 3: Add MCP mount helper**

In `pubtator_link/server_manager.py`, import:

```python
from pubtator_link.mcp.facade import create_pubtator_mcp
```

Change `create_app` signature:

```python
    def create_app(self, *, include_mcp: bool = False) -> FastAPI:
```

At the end of `create_app`, before `self.app = app`, add:

```python
        if include_mcp:
            mcp = create_pubtator_mcp()
            app.mount(settings.mcp_path, mcp.http_app(path=settings.mcp_path))
            self.mcp = mcp
```

If installed FastMCP 3.x expects a relative path when mounted, use:

```python
            app.mount(settings.mcp_path, mcp.http_app(path="/"))
```

and keep the integration test as the source of truth.

- [ ] **Step 4: Use the curated facade in unified mode**

In `start_unified_server`, replace:

```python
        app = self.create_app()

        # Create and mount MCP server
        self.mcp = await self.create_mcp_server(app)
        app.mount("/mcp", self.mcp.http_app())
```

with:

```python
        app = self.create_app(include_mcp=True)
```

Update logs:

```python
        self.logger.info("MCP Streamable HTTP facade mounted", path=settings.mcp_path)
```

- [ ] **Step 5: Mount MCP in the production ASGI app**

At the bottom of `pubtator_link/server_manager.py`, replace:

```python
app = _manager.create_app()
```

with:

```python
app = _manager.create_app(include_mcp=settings.transport == "unified")
```

- [ ] **Step 6: Point stdio entrypoint to curated facade**

In `mcp_server.py`, replace the `UnifiedServerManager` startup path with:

```python
from pubtator_link.mcp.facade import create_pubtator_mcp

mcp = create_pubtator_mcp()
mcp.run(transport="stdio")
```

Keep the stdout protection setup from the existing file.

- [ ] **Step 7: Verify Streamable HTTP smoke**

Run:

```bash
uv run pytest tests/integration/test_mcp_http_protocol.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/server_manager.py mcp_server.py tests/integration/test_mcp_http_protocol.py
git commit -m "feat: serve curated mcp facade over streamable http"
```

---

## Task 5: Add Tool Annotations And Structured Output Schemas

**Files:**
- Modify: `pubtator_link/mcp/facade.py`
- Modify: `pubtator_link/mcp/tools.py`
- Modify: `tests/unit/mcp/test_mcp_facade.py`

- [ ] **Step 1: Add metadata tests**

Append to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_public_hosted_tools_have_expected_annotations() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tools = mcp._tool_manager._tools

    for name in (
        "pubtator.search_literature",
        "pubtator.fetch_publication_annotations",
        "pubtator.search_biomedical_entities",
        "pubtator.find_entity_relations",
        "pubtator.get_server_capabilities",
    ):
        tool = tools[name]
        assert "Use this when" in tool.description
        assert "not for diagnosis" in tool.description
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False


def test_open_world_tools_are_marked_open_world() -> None:
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp()
    tool = mcp._tool_manager._tools["pubtator.search_literature"]

    assert tool.annotations.openWorldHint is True
```

- [ ] **Step 2: Run failing metadata tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: fail until annotations are added.

- [ ] **Step 3: Add annotation helper**

In `pubtator_link/mcp/facade.py`, add:

```python
from mcp.types import ToolAnnotations

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)

READ_ONLY_CLOSED_WORLD = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

REMOTE_JOB_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
```

- [ ] **Step 4: Attach annotations to tools**

For read-only PubTator/NCBI lookup tools, add:

```python
annotations=READ_ONLY_OPEN_WORLD
```

For `pubtator.get_server_capabilities`, add:

```python
annotations=READ_ONLY_CLOSED_WORLD
```

For `pubtator.submit_text_annotation`, add:

```python
annotations=REMOTE_JOB_ANNOTATIONS
```

Use descriptions that begin with “Use this when” and include the research-use notice.

- [ ] **Step 5: Verify metadata tests**

Run:

```bash
uv run pytest tests/unit/mcp/test_mcp_facade.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/facade.py pubtator_link/mcp/tools.py tests/unit/mcp/test_mcp_facade.py
git commit -m "feat: add mcp tool annotations and metadata"
```

---

## Task 6: Harden Docker Image

**Files:**
- Modify: `docker/Dockerfile`
- Create: `tests/unit/docker/test_dockerfile_hardening.py`

- [ ] **Step 1: Write Dockerfile hardening tests**

Create `tests/unit/docker/test_dockerfile_hardening.py`:

```python
from __future__ import annotations

from pathlib import Path


DOCKERFILE = Path("docker/Dockerfile").read_text()


def test_dockerfile_uses_python_311_and_uv_lock() -> None:
    assert "FROM python:3.11-slim" in DOCKERFILE
    assert "COPY uv.lock pyproject.toml README.md ./" in DOCKERFILE
    assert "uv sync --frozen" in DOCKERFILE


def test_dockerfile_runs_as_non_root_and_has_runtime_dirs() -> None:
    assert "USER app" in DOCKERFILE
    assert "/tmp/pubtator-link" in DOCKERFILE
    assert "/var/cache/pubtator-link" in DOCKERFILE


def test_dockerfile_healthcheck_uses_internal_health_endpoint() -> None:
    assert "HEALTHCHECK" in DOCKERFILE
    assert "http://localhost:8000/health" in DOCKERFILE
```

- [ ] **Step 2: Run failing hardening tests**

Run:

```bash
uv run pytest tests/unit/docker/test_dockerfile_hardening.py -q
```

Expected: fail because Dockerfile does not use `uv.lock` and runtime dirs are missing.

- [ ] **Step 3: Update Dockerfile builder**

In `docker/Dockerfile`, replace the builder install block with:

```dockerfile
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY uv.lock pyproject.toml README.md ./
RUN pip install --upgrade pip uv && \
    uv sync --frozen --no-dev --active
```

- [ ] **Step 4: Update Dockerfile production stage**

In the production stage, ensure these lines exist:

```dockerfile
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/home/app/web" \
    PUBTATOR_LINK_HOST=0.0.0.0 \
    PUBTATOR_LINK_PORT=8000 \
    PUBTATOR_LINK_TRANSPORT=unified \
    TMPDIR=/tmp/pubtator-link

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

RUN groupadd --system app && \
    useradd --system --gid app --home /home/app --create-home app && \
    mkdir -p /tmp/pubtator-link /var/cache/pubtator-link && \
    chown -R app:app /tmp/pubtator-link /var/cache/pubtator-link /home/app
```

Keep:

```dockerfile
USER app
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["gunicorn", "-c", "gunicorn_conf.py", "pubtator_link.server_manager:app"]
```

- [ ] **Step 5: Verify Dockerfile tests**

Run:

```bash
uv run pytest tests/unit/docker/test_dockerfile_hardening.py -q
```

Expected: pass.

- [ ] **Step 6: Build image**

Run:

```bash
docker build -f docker/Dockerfile -t pubtator-link:modern .
```

Expected: image builds successfully.

- [ ] **Step 7: Commit**

```bash
git add docker/Dockerfile tests/unit/docker/test_dockerfile_hardening.py
git commit -m "chore: harden docker image build"
```

---

## Task 7: Harden Docker Compose Production Settings

**Files:**
- Modify: `docker/docker-compose.yml`
- Modify: `docker/docker-compose.prod.yml`
- Create: `tests/unit/docker/test_compose_hardening.py`

- [ ] **Step 1: Write Compose hardening tests**

Create `tests/unit/docker/test_compose_hardening.py`:

```python
from __future__ import annotations

from pathlib import Path


BASE = Path("docker/docker-compose.yml").read_text()
PROD = Path("docker/docker-compose.prod.yml").read_text()


def test_base_compose_runs_unified_server_with_mcp() -> None:
    assert "PUBTATOR_LINK_TRANSPORT: unified" in BASE
    assert "pubtator_link.server_manager:app" in BASE


def test_prod_compose_has_security_controls() -> None:
    assert "read_only: true" in PROD
    assert "no-new-privileges:true" in PROD
    assert "cap_drop:" in PROD
    assert "- ALL" in PROD
    assert "/tmp/pubtator-link" in PROD


def test_prod_compose_does_not_publish_extra_ports() -> None:
    assert "ports: []" in PROD
```

- [ ] **Step 2: Run failing Compose tests**

Run:

```bash
uv run pytest tests/unit/docker/test_compose_hardening.py -q
```

Expected: fail because production Compose does not yet include these controls.

- [ ] **Step 3: Update production Compose**

In `docker/docker-compose.prod.yml`, add under `services.pubtator-link`:

```yaml
    ports: []

    read_only: true
    tmpfs:
      - /tmp/pubtator-link:rw,noexec,nosuid,size=64m

    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL

    pids_limit: 256
    init: true
```

Keep health checks and resource limits.

- [ ] **Step 4: Ensure base Compose uses the unified ASGI app**

In `docker/docker-compose.yml`, set:

```yaml
    command: ["uvicorn", "pubtator_link.server_manager:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
```

Keep:

```yaml
      PUBTATOR_LINK_TRANSPORT: unified
```

- [ ] **Step 5: Validate Compose config**

Run:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config
```

Expected: renders successfully.

- [ ] **Step 6: Verify Compose tests**

Run:

```bash
uv run pytest tests/unit/docker/test_compose_hardening.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add docker/docker-compose.yml docker/docker-compose.prod.yml tests/unit/docker/test_compose_hardening.py
git commit -m "chore: harden production compose deployment"
```

---

## Task 8: Add Nginx Proxy Manager Compose Override

**Files:**
- Create: `docker/docker-compose.npm.yml`
- Create: `docker/.env.npm.example`
- Modify: `docker/README.md`
- Modify: `tests/unit/docker/test_compose_hardening.py`

- [ ] **Step 1: Add NPM tests**

Append to `tests/unit/docker/test_compose_hardening.py`:

```python
NPM = Path("docker/docker-compose.npm.yml").read_text()
NPM_ENV = Path("docker/.env.npm.example").read_text()


def test_npm_compose_matches_shared_network_pattern() -> None:
    assert "npm_shared:" in NPM
    assert "external: true" in NPM
    assert "${NPM_SHARED_NETWORK_NAME:-npm_default}" in NPM
    assert "ports: []" in NPM


def test_npm_environment_documents_public_url_and_cors() -> None:
    assert "PUBTATOR_LINK_PUBLIC_DOMAIN" in NPM_ENV
    assert "PUBTATOR_LINK_PUBLIC_URL" in NPM_ENV
    assert "PUBTATOR_LINK_CORS_ORIGINS" in NPM_ENV
```

- [ ] **Step 2: Run failing NPM tests**

Run:

```bash
uv run pytest tests/unit/docker/test_compose_hardening.py -q
```

Expected: fail because NPM files do not exist.

- [ ] **Step 3: Create NPM Compose override**

Create `docker/docker-compose.npm.yml`:

```yaml
# NPM (Nginx Proxy Manager) production deployment
# Usage: docker compose --env-file docker/.env.npm -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml up -d

services:
  pubtator-link:
    environment:
      PUBTATOR_LINK_LOG_LEVEL: INFO
      PUBTATOR_LINK_LOG_FORMAT: json
      PUBTATOR_LINK_TRANSPORT: unified
      PUBTATOR_LINK_HOST: 0.0.0.0
      PUBTATOR_LINK_PORT: 8000
      PUBTATOR_LINK_PUBLIC_DOMAIN: "${PUBTATOR_LINK_PUBLIC_DOMAIN}"
      PUBTATOR_LINK_PUBLIC_URL: "${PUBTATOR_LINK_PUBLIC_URL}"
      PUBTATOR_LINK_CORS_ORIGINS: "${PUBTATOR_LINK_CORS_ORIGINS}"

    ports: []

    networks:
      - npm_shared
      - default

    command: ["gunicorn", "-c", "gunicorn_conf.py", "pubtator_link.server_manager:app"]

    logging:
      driver: "json-file"
      options:
        max-size: "50m"
        max-file: "5"
        labels: "service=pubtator-link,environment=production,proxy=npm"

networks:
  npm_shared:
    external: true
    name: "${NPM_SHARED_NETWORK_NAME:-npm_default}"
```

- [ ] **Step 4: Create NPM env example**

Create `docker/.env.npm.example`:

```env
NPM_SHARED_NETWORK_NAME=npm_default
PUBTATOR_LINK_PUBLIC_DOMAIN=pubtator.example.com
PUBTATOR_LINK_PUBLIC_URL=https://pubtator.example.com
PUBTATOR_LINK_CORS_ORIGINS=["https://pubtator.example.com"]
```

- [ ] **Step 5: Document NPM proxy host**

In `docker/README.md`, add:

```markdown
## Nginx Proxy Manager Deployment

1. Copy `docker/.env.npm.example` to `docker/.env.npm` and set your domain.
2. Ensure the NPM Docker network exists. The default is `npm_default`.
3. Start PubTator-Link without publishing host ports:

```bash
docker compose --env-file docker/.env.npm \
  -f docker/docker-compose.yml \
  -f docker/docker-compose.prod.yml \
  -f docker/docker-compose.npm.yml \
  up -d --build
```

4. In Nginx Proxy Manager, create a Proxy Host:
   - Domain Names: your `PUBTATOR_LINK_PUBLIC_DOMAIN`
   - Scheme: `http`
   - Forward Hostname / IP: `pubtator_link_server`
   - Forward Port: `8000`
   - Enable Websockets Support
   - Enable Block Common Exploits
   - Request a Let's Encrypt certificate and force SSL

The MCP endpoint is available at `https://your-domain.example/mcp`.
```

- [ ] **Step 6: Validate NPM Compose**

Run:

```bash
docker compose --env-file docker/.env.npm.example -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml config
```

Expected: renders successfully and service has no published host ports.

- [ ] **Step 7: Verify NPM tests**

Run:

```bash
uv run pytest tests/unit/docker/test_compose_hardening.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add docker/docker-compose.npm.yml docker/.env.npm.example docker/README.md tests/unit/docker/test_compose_hardening.py
git commit -m "chore: add nginx proxy manager deployment"
```

---

## Task 9: Make Gunicorn Proxy-Aware And Container-Friendly

**Files:**
- Modify: `docker/gunicorn_conf.py`
- Create: `tests/unit/docker/test_gunicorn_config.py`

- [ ] **Step 1: Add Gunicorn config tests**

Create `tests/unit/docker/test_gunicorn_config.py`:

```python
from __future__ import annotations

from pathlib import Path


CONFIG = Path("docker/gunicorn_conf.py").read_text()


def test_gunicorn_respects_pubtator_port_and_proxy_headers() -> None:
    assert "PUBTATOR_LINK_PORT" in CONFIG
    assert "forwarded_allow_ips" in CONFIG
    assert "secure_scheme_headers" in CONFIG


def test_gunicorn_worker_count_is_container_safe() -> None:
    assert 'os.environ.get("GUNICORN_WORKERS", "2")' in CONFIG
    assert "max_requests_jitter" in CONFIG
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
uv run pytest tests/unit/docker/test_gunicorn_config.py -q
```

Expected: fail because config uses `PORT` and CPU-count worker default.

- [ ] **Step 3: Update Gunicorn bind and workers**

In `docker/gunicorn_conf.py`, replace:

```python
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
```

with:

```python
bind = f"0.0.0.0:{os.environ.get('PUBTATOR_LINK_PORT', os.environ.get('PORT', '8000'))}"
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))
```

Remove the now-unused `multiprocessing` import.

- [ ] **Step 4: Add proxy header settings**

Add:

```python
forwarded_allow_ips = os.environ.get("GUNICORN_FORWARDED_ALLOW_IPS", "*")
secure_scheme_headers = {
    "X-FORWARDED-PROTO": "https",
    "X-FORWARDED-SSL": "on",
}
```

- [ ] **Step 5: Verify Gunicorn tests**

Run:

```bash
uv run pytest tests/unit/docker/test_gunicorn_config.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add docker/gunicorn_conf.py tests/unit/docker/test_gunicorn_config.py
git commit -m "chore: make gunicorn proxy aware"
```

---

## Task 10: Update HTTP-First MCP And Docker Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`
- Modify: `claude_desktop_config_example.json`

- [ ] **Step 1: Rewrite MCP connection guide source of truth**

In `docs/MCP_CONNECTION_GUIDE.md`, add this transport table near the top:

```markdown
| Mode | Endpoint | Status | Use Case |
|------|----------|--------|----------|
| Streamable HTTP | `/mcp` | Recommended | Claude HTTP, ChatGPT developer mode, hosted remote MCP clients |
| stdio | `pubtator-link-mcp` | Local fallback | Local desktop-only workflows |
```

- [ ] **Step 2: Add ChatGPT developer mode setup**

Add:

```markdown
### ChatGPT Developer Mode

Add a remote MCP connector with this URL:

```text
https://your-domain.example/mcp
```

Use no authentication only for local/private deployments. Public deployments should be protected by OAuth or an authenticated reverse proxy. PubTator-Link tools are research-oriented and must not be used for diagnosis, treatment, triage, patient management, or clinical decision support.
```

- [ ] **Step 3: Add Claude HTTP setup**

Add:

```markdown
### Claude HTTP

```bash
claude mcp add --transport http pubtator-link https://your-domain.example/mcp
```

For local development:

```bash
python server.py --transport unified
claude mcp add --transport http pubtator-link http://127.0.0.1:8000/mcp
```
```

- [ ] **Step 4: Update tool table**

Replace the old raw OpenAPI tool table with:

```markdown
| Tool | Use When |
|------|----------|
| `pubtator.search_literature` | Search PubMed literature through PubTator3 |
| `pubtator.fetch_publication_annotations` | Fetch annotations for PubMed IDs |
| `pubtator.fetch_pmc_annotations` | Fetch annotations for PMC full-text articles |
| `pubtator.search_biomedical_entities` | Find canonical PubTator biomedical entity IDs |
| `pubtator.find_entity_relations` | Explore literature-derived relations for a PubTator entity |
| `pubtator.submit_text_annotation` | Submit research text for PubTator biomedical NER |
| `pubtator.get_text_annotation_results` | Retrieve asynchronous text annotation results |
| `pubtator.get_server_capabilities` | Discover formats, bioconcepts, relation types, and limitations |
```

- [ ] **Step 5: Update Claude config example**

In `claude_desktop_config_example.json`, make HTTP first:

```json
{
  "mcpServers": {
    "pubtator-link": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp"
    },
    "pubtator-link-stdio": {
      "command": "pubtator-link-mcp",
      "env": {
        "PYTHONUNBUFFERED": "1",
        "PUBTATOR_LINK_LOG_LEVEL": "WARNING"
      }
    }
  }
}
```

- [ ] **Step 6: Run docs grep checks**

Run:

```bash
rg -n "transport.*type|STDIO Mode \\(Recommended|clear_api_cache|/sse|SSE" README.md docs/MCP_CONNECTION_GUIDE.md claude_desktop_config_example.json
```

Expected: no stale stdio-first recommendation, no `/sse`, and no public `clear_api_cache` recommendation.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/MCP_CONNECTION_GUIDE.md claude_desktop_config_example.json
git commit -m "docs: document hosted streamable http mcp"
```

---

## Task 11: Final Verification

**Files:**
- Create: `.planning/analysis/2026-04-29-modern-mcp-docker-npm-verification.md`

- [ ] **Step 1: Run unit and integration tests**

Run:

```bash
uv run pytest tests/unit/mcp tests/integration/test_mcp_http_protocol.py tests/unit/docker -q
```

Expected: pass.

- [ ] **Step 2: Run full repository checks**

Run:

```bash
uv run ruff check .
uv run mypy pubtator_link
uv run pytest -q
```

Expected: pass.

- [ ] **Step 3: Build Docker image**

Run:

```bash
docker build -f docker/Dockerfile -t pubtator-link:modern .
```

Expected: pass.

- [ ] **Step 4: Validate Compose files**

Run:

```bash
docker compose -f docker/docker-compose.yml config
docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config
docker compose --env-file docker/.env.npm.example -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml config
```

Expected: all render successfully.

- [ ] **Step 5: Run local container smoke**

Run:

```bash
docker compose -f docker/docker-compose.yml up -d --build
curl -fsS http://127.0.0.1:8000/health
curl -fsS -X POST http://127.0.0.1:8000/mcp \
  -H 'Accept: application/json, text/event-stream' \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1.0"}}}'
docker compose -f docker/docker-compose.yml down
```

Expected: health returns healthy JSON and MCP initialize returns HTTP 200 or 202.

- [ ] **Step 6: Record verification notes**

Create `.planning/analysis/2026-04-29-modern-mcp-docker-npm-verification.md`:

```markdown
# Modern MCP Docker NPM Verification

Date: 2026-04-29

## Commands

- `uv run pytest tests/unit/mcp tests/integration/test_mcp_http_protocol.py tests/unit/docker -q`
- `uv run ruff check .`
- `uv run mypy pubtator_link`
- `uv run pytest -q`
- `docker build -f docker/Dockerfile -t pubtator-link:modern .`
- `docker compose -f docker/docker-compose.yml config`
- `docker compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml config`
- `docker compose --env-file docker/.env.npm.example -f docker/docker-compose.yml -f docker/docker-compose.prod.yml -f docker/docker-compose.npm.yml config`
- Local health and MCP initialize curl smoke.

## Outcomes

Record exact pass/fail outcomes and any follow-up fixes made before final merge.
```

- [ ] **Step 7: Commit verification notes**

```bash
git add .planning/analysis/2026-04-29-modern-mcp-docker-npm-verification.md
git commit -m "test: record mcp docker npm verification"
```

---

## Acceptance Criteria

- `uv lock` and `uv run pytest` work on Python 3.11+.
- `/mcp` is a hosted Streamable HTTP endpoint in unified and production container modes.
- `uvicorn pubtator_link.server_manager:app` and Gunicorn production startup expose REST plus curated MCP when `PUBTATOR_LINK_TRANSPORT=unified`.
- Public hosted MCP no longer exposes `clear_api_cache`.
- Tool metadata is action-oriented and includes research-use limitations.
- Read-only tools are annotated as read-only; remote-job text submission is not mislabeled as read-only.
- MCP resources expose capabilities, bioconcepts, relation types, formats, text-processing support, and compliance notice.
- MCP prompts are short, user-invoked workflow templates.
- Docker image runs as a non-root user.
- Production Compose uses `read_only`, `tmpfs`, `cap_drop: [ALL]`, `no-new-privileges:true`, `pids_limit`, health checks, restart policy, and log rotation.
- NPM override joins the external `npm_default` network, publishes no host ports, and documents the proxy host configuration.
- Docker and MCP docs are HTTP-first and contain no `/sse` or stdio-first recommendations.
- Verification commands pass and are recorded.

## Self-Review

- Spec coverage: MCP modernization, Docker hardening, and NPM compatibility are covered by Tasks 1-11.
- Placeholder scan: no task uses `TBD`, empty test instructions, or deferred implementation without an explicit next task. Task 3 intentionally implements adapters incrementally and names the exact adapter functions and source files to copy behavior from.
- Type consistency: tool names use the `pubtator.*` prefix throughout; Docker environment variables use `PUBTATOR_LINK_*`; NPM network variable is `NPM_SHARED_NETWORK_NAME`.
