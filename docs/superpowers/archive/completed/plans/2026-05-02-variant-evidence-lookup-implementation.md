# Variant Evidence Lookup Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a research-scoped variant evidence lookup tool that returns source-attributed ClinVar records and PubTator literature evidence without computing clinical classification.

**Architecture:** Add focused variant models, a ClinVar E-utilities client/service, and a coordinator service that combines ClinVar lookup, PubTator literature search, and publication metadata. Register one REST route and one MCP tool, and extend entity grounding to accept `Phenotype` while preserving research-use safety wording as source-attributed output.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, httpx, PubTator3 client, NCBI E-utilities, MCP FastMCP, pytest, Ruff, mypy, uv, Makefile.

---

## File Structure

- Create `pubtator_link/models/variants.py`: request/response models for variant evidence.
- Create `pubtator_link/services/clinvar.py`: ESearch/ESummary parsing for ClinVar.
- Create `pubtator_link/services/variant_evidence.py`: orchestration of ClinVar, PubTator literature, and citation metadata.
- Create `pubtator_link/api/routes/variants.py`: `POST /api/variants/evidence`.
- Modify `pubtator_link/api/routes/__init__.py`, `pubtator_link/server_manager.py`, and `pubtator_link/api/routes/dependencies.py`: route and service wiring.
- Modify `pubtator_link/mcp/tools/literature.py` and `pubtator_link/mcp/service_adapters.py`: `pubtator.lookup_variant_evidence`.
- Modify `pubtator_link/mcp/resources.py`, `pubtator_link/services/workflow_help.py`, and `tests/unit/mcp/test_mcp_facade.py`: capabilities and workflow registration.
- Modify `pubtator_link/config.py`, `pubtator_link/models/requests.py`, `pubtator_link/api/routes/entities.py`, and MCP entity signatures: add `Phenotype`.
- Test files: `tests/unit/test_clinvar_service.py`, `tests/unit/test_variant_evidence_service.py`, `tests/test_routes/test_variants.py`, `tests/test_routes/test_entities.py`, `tests/unit/mcp/test_mcp_service_adapters.py`, `tests/unit/mcp/test_mcp_facade.py`, `tests/integration/test_mcp_http_protocol.py`.

### Task 1: Variant Evidence Models

**Files:**
- Create: `pubtator_link/models/variants.py`
- Modify: `pubtator_link/models/__init__.py`
- Test: `tests/unit/test_variant_evidence_models.py`

- [ ] **Step 1: Write failing model tests**

Create:

```python
from pubtator_link.models.variants import VariantEvidenceRequest, VariantEvidenceResponse


def test_variant_request_requires_gene_and_one_variant_expression() -> None:
    request = VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C")

    assert request.gene == "MEFV"
    assert request.variant == "c.2177T>C"


def test_variant_response_has_no_computed_classification_field() -> None:
    response = VariantEvidenceResponse(
        query={"gene": "MEFV", "variant": "c.2177T>C"},
        warnings=["Classifications are source-attributed; PubTator-Link does not compute clinical significance."],
    )

    dumped = response.model_dump()
    assert "computed_classification" not in dumped
    assert response.source_classifications == []
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_variant_evidence_models.py -q`
Expected: FAIL because models do not exist.

- [ ] **Step 3: Add models**

Define:

```python
VariantEvidenceSource = Literal["clinvar", "pubtator"]

class VariantEvidenceRequest(BaseModel):
    gene: str = Field(min_length=1)
    variant: str | None = Field(default=None, min_length=1)
    protein: str | None = Field(default=None, min_length=1)
    condition: str | None = Field(default=None, min_length=1)
    sources: list[VariantEvidenceSource] = Field(default_factory=lambda: ["clinvar", "pubtator"])
    max_literature_pmids: int = Field(default=20, ge=0, le=100)
    include_citations: bool = True
```

Add validators requiring `variant` or `protein`, plus `NormalizedVariant`, `SourceClassification`, `VariantLiteratureEvidence`, `VariantConflict`, and `VariantEvidenceResponse`.

- [ ] **Step 4: Run model tests**

Run: `uv run pytest tests/unit/test_variant_evidence_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/variants.py pubtator_link/models/__init__.py tests/unit/test_variant_evidence_models.py
git commit -m "feat: add variant evidence models"
```

### Task 2: ClinVar E-Utilities Client

**Files:**
- Create: `pubtator_link/services/clinvar.py`
- Test: `tests/unit/test_clinvar_service.py`

- [ ] **Step 1: Write failing tests**

Create:

```python
@pytest.mark.asyncio
async def test_clinvar_query_construction_uses_gene_and_variant() -> None:
    client = FakeClinVarHttpClient()
    service = ClinVarService(client)

    await service.lookup(gene="MEFV", variant_terms=["c.2177T>C"], condition="familial Mediterranean fever")

    assert client.esearch_terms[0] == 'MEFV[gene] AND "c.2177T>C" AND "familial Mediterranean fever"'


def test_parse_clinvar_summary_source_attributed_classification() -> None:
    record = parse_clinvar_summary(_summary_doc())

    assert record.source == "clinvar"
    assert record.classification == "Pathogenic"
    assert record.variation_id == "12345"
    assert record.url == "https://www.ncbi.nlm.nih.gov/clinvar/variation/12345/"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_clinvar_service.py -q`
Expected: FAIL because service does not exist.

- [ ] **Step 3: Implement ClinVar service**

Use the `NcbiDiscoveryClient`/`PublicationMetadataService` pattern: call `esearch.fcgi?db=clinvar&retmode=json`, then `esummary.fcgi?db=clinvar&retmode=json&id=...`. Parse variation IDs, allele IDs, preferred names, HGVS strings, review status, clinical significance labels, condition, last evaluated date, and URL.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_clinvar_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/clinvar.py tests/unit/test_clinvar_service.py
git commit -m "feat: add ClinVar evidence lookup service"
```

### Task 3: Variant Evidence Orchestration

**Files:**
- Create: `pubtator_link/services/variant_evidence.py`
- Test: `tests/unit/test_variant_evidence_service.py`

- [ ] **Step 1: Write failing orchestration tests**

Create:

```python
@pytest.mark.asyncio
async def test_lookup_variant_evidence_combines_clinvar_and_literature() -> None:
    service = VariantEvidenceService(
        clinvar=FakeClinVarService(),
        pubtator_client=FakePubTatorClient(),
        metadata_service=FakePublicationMetadataService(),
    )

    response = await service.lookup(VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C"))

    assert response.normalized_variants[0].source == "clinvar"
    assert response.source_classifications[0].classification == "Pathogenic"
    assert response.literature[0].pmid == "12345678"
    assert response.literature[0].citation_metadata.title == "Variant paper"


@pytest.mark.asyncio
async def test_clinvar_failure_returns_pubtator_partial_success() -> None:
    service = VariantEvidenceService(
        clinvar=FailingClinVarService(),
        pubtator_client=FakePubTatorClient(),
        metadata_service=FakePublicationMetadataService(),
    )

    response = await service.lookup(VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C"))

    assert response.success is True
    assert response.source_classifications == []
    assert response.literature
    assert any("ClinVar unavailable" in warning for warning in response.warnings)
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/test_variant_evidence_service.py -q`
Expected: FAIL because orchestration service does not exist.

- [ ] **Step 3: Implement service**

Build variant terms from `variant`, `protein`, ClinVar normalized names, and aliases. Query PubTator with `(<gene>) AND (<variant terms>)`, limit PMIDs, and attach metadata when `include_citations` is true. Always include the warning: `Classifications are source-attributed; PubTator-Link does not compute clinical significance.`

- [ ] **Step 4: Run service tests**

Run: `uv run pytest tests/unit/test_variant_evidence_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/variant_evidence.py tests/unit/test_variant_evidence_service.py
git commit -m "feat: combine variant database and literature evidence"
```

### Task 4: REST Route And Dependency Wiring

**Files:**
- Create: `pubtator_link/api/routes/variants.py`
- Modify: `pubtator_link/api/routes/__init__.py`
- Modify: `pubtator_link/api/routes/dependencies.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/test_routes/test_variants.py`

- [ ] **Step 1: Write failing route test**

Create:

```python
def test_lookup_variant_evidence_route_returns_source_attributed_records(client, monkeypatch) -> None:
    monkeypatch.setattr("pubtator_link.api.routes.variants.get_variant_evidence_service", fake_dependency)

    response = client.post(
        "/api/variants/evidence",
        json={"gene": "MEFV", "variant": "c.2177T>C", "include_citations": True},
    )

    assert response.status_code == 200
    assert response.json()["source_classifications"][0]["source"] == "clinvar"
```

- [ ] **Step 2: Run test to verify red**

Run: `uv run pytest tests/test_routes/test_variants.py -q`
Expected: FAIL because the route is absent.

- [ ] **Step 3: Add route and dependencies**

Create an `APIRouter(prefix="/api/variants", tags=["variants"])` with `POST /evidence`. Wire `get_clinvar_service()` and `get_variant_evidence_service()` in dependencies, and include the router in `server_manager.py`.

- [ ] **Step 4: Run route test**

Run: `uv run pytest tests/test_routes/test_variants.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/api/routes/variants.py pubtator_link/api/routes/__init__.py pubtator_link/api/routes/dependencies.py pubtator_link/server_manager.py tests/test_routes/test_variants.py
git commit -m "feat: expose variant evidence REST route"
```

### Task 5: MCP Tool And Capabilities

**Files:**
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/integration/test_mcp_http_protocol.py`

- [ ] **Step 1: Write failing MCP tests**

Add:

```python
def test_variant_evidence_tool_is_registered() -> None:
    mcp = create_pubtator_mcp()

    assert "pubtator.lookup_variant_evidence" in mcp._tool_manager._tools


@pytest.mark.asyncio
async def test_lookup_variant_evidence_adapter_calls_service() -> None:
    response = await lookup_variant_evidence_impl(
        gene="MEFV",
        variant="c.2177T>C",
        service=FakeVariantEvidenceService(),
    )

    assert response["query"]["gene"] == "MEFV"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/integration/test_mcp_http_protocol.py -q`
Expected: FAIL because the MCP tool is absent.

- [ ] **Step 3: Add MCP adapter and tool**

Add `lookup_variant_evidence_impl()` building `VariantEvidenceRequest`. Register `pubtator.lookup_variant_evidence` with concise description:

```text
Look up source-attributed variant records and literature evidence for a gene and variant. Does not compute clinical classification.
```

- [ ] **Step 4: Update capabilities and workflow help**

Add the tool to `tools`, `tool_groups["variant_evidence"]`, sample calls, and clinical genetics workflow. Include `pubtator.find_entity_relations` before broad literature search.

- [ ] **Step 5: Run MCP tests**

Run: `uv run pytest tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/integration/test_mcp_http_protocol.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/mcp/tools/literature.py pubtator_link/mcp/service_adapters.py pubtator_link/mcp/resources.py pubtator_link/services/workflow_help.py tests/unit/mcp/test_mcp_service_adapters.py tests/unit/mcp/test_mcp_facade.py tests/integration/test_mcp_http_protocol.py
git commit -m "feat: expose variant evidence MCP tool"
```

### Task 6: Phenotype Entity Grounding

**Files:**
- Modify: `pubtator_link/config.py`
- Modify: `pubtator_link/models/requests.py`
- Modify: `pubtator_link/mcp/tools/literature.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Test: `tests/test_routes/test_entities.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`

- [ ] **Step 1: Write failing tests**

Add:

```python
def test_phenotype_is_valid_entity_concept() -> None:
    request = EntityAutocompleteRequest(query="fever", concept="Phenotype")

    assert request.concept == "Phenotype"


@pytest.mark.asyncio
async def test_search_biomedical_entities_accepts_phenotype() -> None:
    result = await search_biomedical_entities_impl("familial Mediterranean fever", concept="Phenotype", client=FakeClient())

    assert result["concept"] == "Phenotype"
```

- [ ] **Step 2: Run tests to verify red**

Run: `uv run pytest tests/test_routes/test_entities.py tests/unit/mcp/test_mcp_service_adapters.py -q`
Expected: FAIL because `Phenotype` is not a valid concept.

- [ ] **Step 3: Add `Phenotype` concept**

Add `"Phenotype"` to `api_config.bioconcept_types`, request literals, MCP tool literals, and adapter literals. If PubTator upstream does not return HPO IDs directly, preserve upstream IDs and add `source="pubtator"`; do not introduce an ontology dependency.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_routes/test_entities.py tests/unit/mcp/test_mcp_service_adapters.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/config.py pubtator_link/models/requests.py pubtator_link/mcp/tools/literature.py pubtator_link/mcp/service_adapters.py tests/test_routes/test_entities.py tests/unit/mcp/test_mcp_service_adapters.py
git commit -m "feat: allow phenotype entity grounding"
```

### Task 7: Final Verification

- [ ] **Step 1: Run formatting**

Run: `make format`
Expected: exit 0.

- [ ] **Step 2: Run local CI**

Run: `make ci-local`
Expected: exit 0.

## Self-Review

Spec coverage:
- Gene plus variant input and source-attributed output: Tasks 1 and 3.
- ClinVar through E-utilities: Task 2.
- PubTator literature with citation metadata: Task 3.
- REST route and MCP tool: Tasks 4 and 5.
- HPO/Phenotype grounding path: Task 6.
- No computed classification and safety wording: Tasks 1, 3, and 5.
- `find_entity_relations` workflow promotion: Task 5.

Placeholder scan: no placeholder terms or unspecified commands remain.

Type consistency: `VariantEvidenceRequest`, `VariantEvidenceResponse`, `SourceClassification`, `NormalizedVariant`, and `VariantLiteratureEvidence` are used consistently across model, service, REST, and MCP tasks.
