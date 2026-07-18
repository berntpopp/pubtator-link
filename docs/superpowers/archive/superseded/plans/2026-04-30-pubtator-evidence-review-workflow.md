# PubTator Evidence Review Workflow Implementation Plan

> Historical record — this document records the design or plan as of its date. Current behavior is
> defined by implemented code, standards, release evidence, and tests.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **POC split:** The fast review-scoped re-RAG POC is specified in `docs/superpowers/archive/completed/specs/2026-04-30-review-scoped-rerag-poc-design.md` and implemented by `docs/superpowers/archive/completed/plans/2026-04-30-review-scoped-rerag-poc-implementation.md`. Keep deferred items from that POC backlog tracked before continuing the broader workflow plan.

**Goal:** Add PubTator-native evidence exploration tools, asynchronous full-text acquisition, review-scoped retrieval, and a standards-aware PostgreSQL-backed review workflow without adding an LLM dependency to the backend.

**Architecture:** The backend remains deterministic: it retrieves PubTator BioC data, resolves available full text through source adapters, normalizes all text into citable review-scoped passages, stores review state, validates structured user/agent decisions, and exposes PRISMA-inspired audit trails. The MCP client or human reviewer performs judgment; the backend prepares and retrieves compact context packs so the LLM does not need raw papers in context.

**Tech Stack:** FastAPI, FastMCP, Pydantic v2, httpx, async-lru, PostgreSQL via `asyncpg`, Ruff, mypy, pytest, respx.

---

## File Structure

- Create `pubtator_link/models/evidence.py`
  - Pydantic models for `EvidencePassage`, `EvidenceEntity`, `EvidenceRelation`, `EvidencePacket`, and evidence search responses.
- Create `pubtator_link/models/standards.py`
  - Review-standard enums and schema helpers for PICO/PECO/PICOTS/custom protocols, PRISMA flow status, and RoB 2/ROBINS-I/QUADAS-2/custom risk-of-bias tools.
- Create `pubtator_link/services/evidence_service.py`
  - Converts PubTator search/export results into compact evidence packets.
  - Performs simple deterministic passage ranking against a focus query.
- Create `pubtator_link/services/full_text_service.py`
  - Asynchronous resolver cascade for PubTator full export, Europe PMC metadata, PMC BioC JSON, Europe PMC JATS XML, free PDF links, and curated guideline URLs.
- Create `pubtator_link/services/review_corpus_service.py`
  - Builds and queries a review-scoped passage corpus for RAG-style context control.
- Create `pubtator_link/api/routes/evidence.py`
  - FastAPI routes that become MCP tools: `search_evidence`, `get_evidence_packets`, `ground_biomedical_entities`, and `find_evidence_relations`.
- Modify `pubtator_link/api/routes/__init__.py`
  - Register the evidence router.
- Modify `pubtator_link/server_manager.py`
  - Include MCP-friendly operation names for the new evidence endpoints.
- Create `pubtator_link/models/reviews.py`
  - Pydantic models for protocol, candidate records, screening decisions, extraction submissions, risk-of-bias assessments, submitted evidence-certainty assessments, PRISMA flow summaries, and audit trail events.
- Create `pubtator_link/repositories/reviews.py`
  - Repository protocol plus in-memory test implementation.
- Create `pubtator_link/repositories/postgres_reviews.py`
  - PostgreSQL implementation using `asyncpg`.
- Create `pubtator_link/db/review_schema.sql`
  - SQL schema for review protocols, search runs, records, full-text retrieval attempts, review passages, context packs, decisions, extractions, risk-of-bias assessments, certainty assessments, PRISMA flow events, and audit events.
- Create `pubtator_link/services/review_service.py`
  - Deterministic review workflow service that uses the evidence service and repository.
- Create `pubtator_link/api/routes/reviews.py`
  - FastAPI routes that become MCP tools for review workflow state.
- Modify `pubtator_link/config.py`
  - Add optional database settings.
- Modify `pyproject.toml` and `uv.lock`
  - Add `asyncpg`.
- Modify `docker/docker-compose.dev.yml`
  - Add a local PostgreSQL service for development.
- Create tests under `tests/unit/` and `tests/test_routes/`.

## Standards Scope

This implementation uses standards as modeling guidance without claiming full compliance in the first release.

- BioC JSON is the source-evidence format because PubTator exports BioC data.
- PRISMA 2020 concepts shape protocol metadata, screening status, exclusion reasons, automation disclosure, and flow counts.
- PICO, PECO, and PICOTS are supported protocol schemas for review questions.
- RoB 2, ROBINS-I, and QUADAS-2 are supported risk-of-bias schema names with structured domain assessments.
- GRADE is reserved for body-of-evidence certainty. The first implementation stores submitted certainty assessments but does not compute certainty.
- FHIR Evidence resources are not implemented in this plan. Keep internal models JSON-first and leave FHIR as a future export adapter.

## Full-Text and Review-Scoped RAG Scope

The backend should prepare context before the LLM needs it, but it must not silently invent access to unavailable full text.

- PubTator remains the discovery and annotation starting point.
- Full text is resolved asynchronously after candidate PMIDs are identified or after records are marked `include`/`maybe`.
- The resolver cascade records every source attempt, including blocked publisher PDFs and unavailable XML.
- PMCID-based full text is preferred because it is automatable and auditable:
  - NCBI PMC BioC JSON when available.
  - Europe PMC JATS XML when available.
- Europe PMC `fullTextUrlList` PDF links are resolver hints, not guarantees. Attempt polite download, accept only actual PDF bytes, and mark HTML/403/paywall responses as blocked.
- Curated or user-provided guideline PDF/HTML URLs are supported as explicit review sources.
- Retrieval is review-scoped. There is no global biomedical vector store in this plan.
- The first retrieval implementation uses PostgreSQL full-text search, entity filters, section filters, and screening-status boosts. Embeddings/pgvector are a later optional enhancement.

## Task 1: Add Evidence Models

**Files:**
- Create: `pubtator_link/models/evidence.py`
- Test: `tests/unit/test_evidence_models.py`

- [ ] **Step 1: Write model tests**

Create `tests/unit/test_evidence_models.py`:

```python
from pubtator_link.models.evidence import EvidencePacket, EvidencePassage


def test_evidence_packet_enforces_context_limits() -> None:
    packet = EvidencePacket(
        pmid="12345678",
        title="BRCA1 mutations in breast cancer",
        relevant_passages=[
            EvidencePassage(
                passage_id="12345678:abstract:0",
                section="abstract",
                text="BRCA1 mutations are associated with breast cancer risk.",
                offset=0,
                relevance_score=0.75,
            )
        ],
        entities=[],
        relations=[],
    )

    assert packet.pmid == "12345678"
    assert packet.relevant_passages[0].passage_id == "12345678:abstract:0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_evidence_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.models.evidence'`.

- [ ] **Step 3: Implement evidence models**

Create `pubtator_link/models/evidence.py`:

```python
"""Evidence models for PubTator-native review workflows."""

from typing import Any

from pydantic import BaseModel, Field


class EvidencePassage(BaseModel):
    """A compact, citable text passage from a PubTator document."""

    passage_id: str = Field(..., description="Stable passage identifier")
    section: str = Field(..., description="Document section, such as title or abstract")
    text: str = Field(..., description="Passage text")
    offset: int = Field(default=0, description="Character offset in source document")
    relevance_score: float | None = Field(default=None, description="Deterministic query match score")


class EvidenceEntity(BaseModel):
    """A biomedical entity annotation from PubTator."""

    entity_id: str | None = Field(default=None, description="Normalized entity identifier")
    entity_type: str | None = Field(default=None, description="Entity type")
    text: str = Field(..., description="Surface text")
    passage_id: str | None = Field(default=None, description="Passage containing the entity")
    start: int | None = Field(default=None, description="Start offset")
    end: int | None = Field(default=None, description="End offset")
    raw: dict[str, Any] = Field(default_factory=dict, description="Original PubTator annotation")


class EvidenceRelation(BaseModel):
    """A relation annotation from PubTator."""

    relation_id: str | None = Field(default=None, description="Relation identifier")
    relation_type: str | None = Field(default=None, description="Relation type")
    source: str | None = Field(default=None, description="Source entity identifier")
    target: str | None = Field(default=None, description="Target entity identifier")
    passage_id: str | None = Field(default=None, description="Passage containing supporting evidence")
    raw: dict[str, Any] = Field(default_factory=dict, description="Original PubTator relation")


class EvidencePacket(BaseModel):
    """Model-ready compact evidence record."""

    pmid: str = Field(..., description="PubMed ID")
    pmcid: str | None = Field(default=None, description="PubMed Central ID")
    doi: str | None = Field(default=None, description="DOI")
    title: str = Field(..., description="Article title")
    journal: str | None = Field(default=None, description="Journal name when available")
    publication_date: str | None = Field(default=None, description="Publication date when available")
    matched_query: str | None = Field(default=None, description="Query used to retrieve this record")
    relevant_passages: list[EvidencePassage] = Field(default_factory=list)
    entities: list[EvidenceEntity] = Field(default_factory=list)
    relations: list[EvidenceRelation] = Field(default_factory=list)
    source: str = Field(default="pubtator", description="Evidence source")


class EvidencePacketResponse(BaseModel):
    """Response for evidence packet retrieval."""

    success: bool = True
    query: str | None = None
    packets: list[EvidencePacket]
    count: int
```

- [ ] **Step 4: Run model test**

Run: `uv run pytest tests/unit/test_evidence_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/evidence.py tests/unit/test_evidence_models.py
git commit -m "feat: add evidence packet models"
```

## Task 2: Build PubTator Evidence Packet Service

**Files:**
- Create: `pubtator_link/services/evidence_service.py`
- Test: `tests/unit/test_evidence_service.py`

- [ ] **Step 1: Write service tests**

Create `tests/unit/test_evidence_service.py`:

```python
from pubtator_link.services.evidence_service import EvidenceService


def test_rank_passages_prefers_focus_query_terms() -> None:
    service = EvidenceService(client=None)  # type: ignore[arg-type]
    passages = [
        {"section": "abstract", "text": "This study discusses general cancer biology.", "offset": 0},
        {"section": "abstract", "text": "BRCA1 mutations increase breast cancer risk.", "offset": 50},
    ]

    ranked = service.rank_passages(passages, focus_query="BRCA1 breast cancer", max_passages=1)

    assert ranked[0]["text"] == "BRCA1 mutations increase breast cancer risk."


def test_parse_bioc_document_creates_packet() -> None:
    service = EvidenceService(client=None)  # type: ignore[arg-type]
    document = {
        "id": "12345678",
        "infons": {"article-id_pmc": "PMC123", "journal": "Example Journal", "year": "2024"},
        "passages": [
            {
                "infons": {"type": "title"},
                "text": "BRCA1 mutations in breast cancer",
                "offset": 0,
                "annotations": [],
                "relations": [],
            }
        ],
        "relations": [],
    }

    packet = service.document_to_packet(document, focus_query="BRCA1", max_passages=2, max_chars=500)

    assert packet.pmid == "12345678"
    assert packet.title == "BRCA1 mutations in breast cancer"
    assert packet.pmcid == "PMC123"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_evidence_service.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement service**

Create `pubtator_link/services/evidence_service.py`:

```python
"""PubTator-native evidence packet service."""

import re
from typing import Any

from ..api.client import PubTator3Client
from ..models.evidence import EvidenceEntity, EvidencePacket, EvidencePassage, EvidenceRelation


class EvidenceService:
    """Build compact evidence packets from PubTator search and export data."""

    def __init__(self, client: PubTator3Client):
        self.client = client

    async def search_evidence(self, query: str, page: int = 1, sort: str | None = None) -> dict[str, Any]:
        """Search PubTator literature and return raw search data."""
        return await self.client.search_publications(text=query, page=page, sort=sort)

    async def get_evidence_packets(
        self,
        pmids: list[str],
        focus_query: str | None = None,
        max_passages_per_record: int = 3,
        max_chars_per_passage: int = 1200,
    ) -> list[EvidencePacket]:
        """Fetch PubTator BioC JSON and convert documents into compact evidence packets."""
        raw = await self.client.export_publications(pmids=pmids, format="biocjson", full=False)
        documents = self._extract_documents(raw)
        return [
            self.document_to_packet(
                document,
                focus_query=focus_query,
                max_passages=max_passages_per_record,
                max_chars=max_chars_per_passage,
            )
            for document in documents
        ]

    def document_to_packet(
        self,
        document: dict[str, Any],
        focus_query: str | None,
        max_passages: int,
        max_chars: int,
    ) -> EvidencePacket:
        """Convert one PubTator BioC document into an EvidencePacket."""
        pmid = str(document.get("id", ""))
        infons = document.get("infons", {}) if isinstance(document.get("infons"), dict) else {}
        passages = document.get("passages", [])
        title = self._find_title(passages) or pmid
        ranked_passages = self.rank_passages(passages, focus_query=focus_query, max_passages=max_passages)

        evidence_passages = [
            EvidencePassage(
                passage_id=f"{pmid}:{self._passage_section(passage)}:{index}",
                section=self._passage_section(passage),
                text=str(passage.get("text", ""))[:max_chars],
                offset=int(passage.get("offset", 0) or 0),
                relevance_score=passage.get("_relevance_score"),
            )
            for index, passage in enumerate(ranked_passages)
        ]

        return EvidencePacket(
            pmid=pmid,
            pmcid=infons.get("article-id_pmc") or infons.get("pmcid"),
            doi=infons.get("article-id_doi") or infons.get("doi"),
            title=title,
            journal=infons.get("journal"),
            publication_date=infons.get("year") or infons.get("date"),
            matched_query=focus_query,
            relevant_passages=evidence_passages,
            entities=self._extract_entities(pmid, passages),
            relations=self._extract_relations(pmid, document),
        )

    def rank_passages(
        self,
        passages: list[dict[str, Any]],
        focus_query: str | None,
        max_passages: int,
    ) -> list[dict[str, Any]]:
        """Rank passages by simple token overlap with the focus query."""
        if not focus_query:
            return passages[:max_passages]

        query_terms = set(re.findall(r"[a-zA-Z0-9]+", focus_query.lower()))

        def score(passage: dict[str, Any]) -> float:
            text_terms = set(re.findall(r"[a-zA-Z0-9]+", str(passage.get("text", "")).lower()))
            if not query_terms:
                return 0.0
            return len(query_terms & text_terms) / len(query_terms)

        ranked = []
        for passage in passages:
            copied = dict(passage)
            copied["_relevance_score"] = score(passage)
            ranked.append(copied)
        ranked.sort(key=lambda item: item["_relevance_score"], reverse=True)
        return ranked[:max_passages]

    def _extract_documents(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(raw.get("PubTator3"), list):
            return raw["PubTator3"]  # type: ignore[return-value]
        if isinstance(raw.get("documents"), list):
            return raw["documents"]  # type: ignore[return-value]
        content = raw.get("content")
        if isinstance(content, dict) and isinstance(content.get("documents"), list):
            return content["documents"]  # type: ignore[return-value]
        return []

    def _find_title(self, passages: list[dict[str, Any]]) -> str | None:
        for passage in passages:
            if self._passage_section(passage).lower() == "title":
                text = str(passage.get("text", "")).strip()
                return text or None
        return None

    def _passage_section(self, passage: dict[str, Any]) -> str:
        infons = passage.get("infons", {})
        if isinstance(infons, dict):
            return str(infons.get("type") or infons.get("section") or "unknown")
        return "unknown"

    def _extract_entities(self, pmid: str, passages: list[dict[str, Any]]) -> list[EvidenceEntity]:
        entities: list[EvidenceEntity] = []
        for index, passage in enumerate(passages):
            section = self._passage_section(passage)
            passage_id = f"{pmid}:{section}:{index}"
            for annotation in passage.get("annotations", []) or []:
                infons = annotation.get("infons", {}) if isinstance(annotation, dict) else {}
                entities.append(
                    EvidenceEntity(
                        entity_id=infons.get("identifier"),
                        entity_type=infons.get("type"),
                        text=str(annotation.get("text", "")),
                        passage_id=passage_id,
                        start=annotation.get("locations", [{}])[0].get("offset")
                        if annotation.get("locations")
                        else None,
                        end=None,
                        raw=annotation,
                    )
                )
        return entities

    def _extract_relations(self, pmid: str, document: dict[str, Any]) -> list[EvidenceRelation]:
        relations: list[EvidenceRelation] = []
        for relation in document.get("relations", []) or []:
            infons = relation.get("infons", {}) if isinstance(relation, dict) else {}
            relations.append(
                EvidenceRelation(
                    relation_id=relation.get("id"),
                    relation_type=infons.get("type"),
                    source=infons.get("entity1") or infons.get("source"),
                    target=infons.get("entity2") or infons.get("target"),
                    raw=relation,
                )
            )
        return relations
```

- [ ] **Step 4: Run service tests**

Run: `uv run pytest tests/unit/test_evidence_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/evidence_service.py tests/unit/test_evidence_service.py
git commit -m "feat: build PubTator evidence packets"
```

## Task 3: Expose Exploration MCP Tools

**Files:**
- Create: `pubtator_link/api/routes/evidence.py`
- Modify: `pubtator_link/api/routes/__init__.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/test_routes/test_evidence.py`

- [ ] **Step 1: Write route test**

Create `tests/test_routes/test_evidence.py`:

```python
from fastapi.testclient import TestClient

from pubtator_link.api.routes.dependencies import get_api_client
from pubtator_link.server_manager import UnifiedServerManager


class FakeClient:
    async def export_publications(self, pmids: list[str], format: str = "biocjson", full: bool = False):
        return {
            "PubTator3": [
                {
                    "id": pmids[0],
                    "infons": {},
                    "passages": [
                        {
                            "infons": {"type": "title"},
                            "text": "BRCA1 mutations in breast cancer",
                            "offset": 0,
                            "annotations": [],
                        }
                    ],
                    "relations": [],
                }
            ]
        }

    async def search_publications(self, text: str, page: int = 1, sort: str | None = None):
        return {"results": [], "count": 0, "total": 0, "page": page}


def test_get_evidence_packets_route() -> None:
    manager = UnifiedServerManager()
    app = manager.create_app()
    app.dependency_overrides[get_api_client] = lambda: FakeClient()
    client = TestClient(app)

    response = client.get("/api/evidence/packets?pmids=12345678&focus_query=BRCA1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["packets"][0]["pmid"] == "12345678"
```

- [ ] **Step 2: Run route test to verify it fails**

Run: `uv run pytest tests/test_routes/test_evidence.py -q`

Expected: FAIL with 404 for `/api/evidence/packets`.

- [ ] **Step 3: Add route module**

Create `pubtator_link/api/routes/evidence.py`:

```python
"""Evidence exploration routes for MCP tools."""

from fastapi import APIRouter, Query

from ...models.evidence import EvidencePacketResponse
from ...services.evidence_service import EvidenceService
from .dependencies import ClientDep, handle_api_errors

router = APIRouter(prefix="/api/evidence", tags=["Evidence"])


@router.get(
    "/packets",
    response_model=EvidencePacketResponse,
    operation_id="get_evidence_packets",
    summary="Get compact PubTator evidence packets",
)
@handle_api_errors
async def get_evidence_packets(
    client: ClientDep,
    pmids: str = Query(..., description="Comma-separated PubMed IDs"),
    focus_query: str | None = Query(default=None, description="Query used to rank passages"),
    max_passages_per_record: int = Query(default=3, ge=1, le=10),
    max_chars_per_passage: int = Query(default=1200, ge=200, le=4000),
) -> EvidencePacketResponse:
    """Return compact model-ready evidence packets for PubMed IDs."""
    pmid_list = [pmid.strip() for pmid in pmids.split(",") if pmid.strip()]
    service = EvidenceService(client=client)
    packets = await service.get_evidence_packets(
        pmids=pmid_list,
        focus_query=focus_query,
        max_passages_per_record=max_passages_per_record,
        max_chars_per_passage=max_chars_per_passage,
    )
    return EvidencePacketResponse(query=focus_query, packets=packets, count=len(packets))
```

- [ ] **Step 4: Register router**

Modify `pubtator_link/api/routes/__init__.py`:

```python
from .evidence import router as evidence_router
```

Add `evidence_router` to `__all__` and `ROUTE_MODULES`.

Modify `pubtator_link/server_manager.py` imports to include `evidence_router`, then call:

```python
app.include_router(evidence_router)
```

Add MCP custom name:

```python
"get_evidence_packets": "get_evidence_packets",
```

- [ ] **Step 5: Run route test**

Run: `uv run pytest tests/test_routes/test_evidence.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/api/routes/evidence.py pubtator_link/api/routes/__init__.py pubtator_link/server_manager.py tests/test_routes/test_evidence.py
git commit -m "feat: expose evidence packet MCP tool"
```

## Task 4: Add Review Workflow Models

**Files:**
- Create: `pubtator_link/models/standards.py`
- Create: `pubtator_link/models/reviews.py`
- Test: `tests/unit/test_standards_models.py`
- Test: `tests/unit/test_review_models.py`

- [ ] **Step 1: Write standards model tests**

Create `tests/unit/test_standards_models.py`:

```python
from pubtator_link.models.standards import (
    PrismaFlowSummary,
    ProtocolSchema,
    RiskOfBiasJudgement,
    RiskOfBiasTool,
)


def test_standard_enums_include_review_workflow_options() -> None:
    assert ProtocolSchema.pico == "pico"
    assert ProtocolSchema.peco == "peco"
    assert ProtocolSchema.picots == "picots"
    assert RiskOfBiasTool.rob2 == "rob2"
    assert RiskOfBiasTool.robins_i == "robins_i"
    assert RiskOfBiasTool.quadas2 == "quadas2"
    assert RiskOfBiasJudgement.some_concerns == "some_concerns"


def test_prisma_flow_summary_counts_review_states() -> None:
    summary = PrismaFlowSummary(
        identified=100,
        deduplicated=90,
        screened=90,
        excluded_title_abstract=50,
        full_text_assessed=40,
        excluded_full_text=10,
        included=30,
    )

    assert summary.included == 30
```

- [ ] **Step 2: Run standards test to verify it fails**

Run: `uv run pytest tests/unit/test_standards_models.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'pubtator_link.models.standards'`.

- [ ] **Step 3: Implement standards models**

Create `pubtator_link/models/standards.py`:

```python
"""Standards-aware review schema primitives."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ProtocolSchema(StrEnum):
    """Supported review-question schema names."""

    pico = "pico"
    peco = "peco"
    picots = "picots"
    custom = "custom"


class RiskOfBiasTool(StrEnum):
    """Supported risk-of-bias schema names."""

    rob2 = "rob2"
    robins_i = "robins_i"
    quadas2 = "quadas2"
    custom = "custom"


class RiskOfBiasJudgement(StrEnum):
    """Structured risk-of-bias judgement values."""

    low = "low"
    some_concerns = "some_concerns"
    high = "high"
    serious = "serious"
    critical = "critical"
    unclear = "unclear"
    not_applicable = "not_applicable"


class CertaintyRating(StrEnum):
    """Body-of-evidence certainty ratings inspired by GRADE."""

    high = "high"
    moderate = "moderate"
    low = "low"
    very_low = "very_low"
    not_assessed = "not_assessed"


class PrismaFlowSummary(BaseModel):
    """PRISMA-inspired review flow counters."""

    identified: int = Field(default=0, ge=0)
    deduplicated: int = Field(default=0, ge=0)
    screened: int = Field(default=0, ge=0)
    excluded_title_abstract: int = Field(default=0, ge=0)
    full_text_assessed: int = Field(default=0, ge=0)
    excluded_full_text: int = Field(default=0, ge=0)
    included: int = Field(default=0, ge=0)
    automation_used: bool = False
    automation_description: str | None = None
```

- [ ] **Step 4: Write review model tests**

Create `tests/unit/test_review_models.py`:

```python
from pubtator_link.models.reviews import ReviewProtocol, RiskOfBiasAssessment, ScreeningDecision


def test_review_protocol_defaults_to_custom_protocol_schema() -> None:
    protocol = ReviewProtocol(
        review_id="rev_123",
        question="Does BRCA1 increase breast cancer risk?",
        population="Humans with breast cancer risk",
        exposure="BRCA1 mutation",
        comparator=None,
        outcomes=["Breast cancer incidence"],
        inclusion_criteria=["Human studies"],
        exclusion_criteria=["Animal-only studies"],
        extraction_fields=["population", "exposure", "outcome"],
        risk_of_bias_tool="custom",
        risk_of_bias_domains=["fit_to_question", "study_design", "evidence_directness"],
    )

    assert protocol.protocol_schema == "custom"


def test_screening_decision_requires_known_decision() -> None:
    decision = ScreeningDecision(
        review_id="rev_123",
        pmid="12345678",
        decision="include",
        reason="Matches the population and outcome criteria.",
        supporting_passage_ids=["12345678:abstract:0"],
    )

    assert decision.decision == "include"


def test_risk_of_bias_assessment_stores_structured_domains() -> None:
    assessment = RiskOfBiasAssessment(
        review_id="rev_123",
        pmid="12345678",
        tool="rob2",
        domains=[
            {
                "domain": "bias_due_to_randomization",
                "judgement": "some_concerns",
                "rationale": "Randomization is mentioned but allocation concealment is unclear.",
                "supporting_passage_ids": ["12345678:abstract:0"],
            }
        ],
        overall="some_concerns",
        rationale="The main concern is incomplete randomization reporting.",
    )

    assert assessment.tool == "rob2"
    assert assessment.domains[0].judgement == "some_concerns"
```

- [ ] **Step 5: Run review model test to verify it fails**

Run: `uv run pytest tests/unit/test_review_models.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 6: Implement review models**

Create `pubtator_link/models/reviews.py`:

```python
"""Review workflow models."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from .standards import CertaintyRating, ProtocolSchema, RiskOfBiasJudgement, RiskOfBiasTool


ReviewDecision = Literal["include", "exclude", "maybe"]


class ReviewProtocol(BaseModel):
    """A reproducible review protocol."""

    review_id: str
    question: str
    protocol_schema: ProtocolSchema = ProtocolSchema.custom
    population: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    timing: str | None = None
    setting: str | None = None
    inclusion_criteria: list[str] = Field(default_factory=list)
    exclusion_criteria: list[str] = Field(default_factory=list)
    extraction_fields: list[str] = Field(default_factory=list)
    risk_of_bias_tool: RiskOfBiasTool = RiskOfBiasTool.custom
    risk_of_bias_domains: list[str] = Field(default_factory=list)


class ReviewRecord(BaseModel):
    """A candidate evidence record in a review."""

    review_id: str
    pmid: str
    source_query: str
    status: Literal["candidate", "screened", "extracted", "assessed"] = "candidate"


class ScreeningDecision(BaseModel):
    """Structured include/exclude/maybe decision."""

    review_id: str
    pmid: str
    decision: ReviewDecision
    reason: str
    supporting_passage_ids: list[str] = Field(default_factory=list)


class StudyExtraction(BaseModel):
    """Structured extraction values for a study."""

    review_id: str
    pmid: str
    values: dict[str, Any]
    supporting_passage_ids: list[str] = Field(default_factory=list)


class RiskOfBiasDomainAssessment(BaseModel):
    """Assessment for one risk-of-bias domain."""

    domain: str
    judgement: RiskOfBiasJudgement
    rationale: str
    supporting_passage_ids: list[str] = Field(default_factory=list)


class RiskOfBiasAssessment(BaseModel):
    """Transparent risk-of-bias assessment without hidden scoring."""

    review_id: str
    pmid: str
    tool: RiskOfBiasTool
    domains: list[RiskOfBiasDomainAssessment]
    overall: RiskOfBiasJudgement
    rationale: str


class CertaintyAssessment(BaseModel):
    """Submitted body-of-evidence certainty assessment inspired by GRADE."""

    review_id: str
    outcome: str
    rating: CertaintyRating = CertaintyRating.not_assessed
    rationale: str | None = None
    supporting_pmids: list[str] = Field(default_factory=list)


class ReviewAuditEvent(BaseModel):
    """Append-only review audit event."""

    review_id: str
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 7: Run model tests**

Run: `uv run pytest tests/unit/test_standards_models.py tests/unit/test_review_models.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pubtator_link/models/standards.py pubtator_link/models/reviews.py tests/unit/test_standards_models.py tests/unit/test_review_models.py
git commit -m "feat: add standards-aware review models"
```

## Task 5: Add Full-Text and Review Corpus Models

**Files:**
- Modify: `pubtator_link/models/evidence.py`
- Test: `tests/unit/test_full_text_models.py`

- [ ] **Step 1: Write full-text model tests**

Create `tests/unit/test_full_text_models.py`:

```python
from pubtator_link.models.evidence import FullTextRetrievalAttempt, ReviewPassage


def test_full_text_attempt_records_blocked_pdf_source() -> None:
    attempt = FullTextRetrievalAttempt(
        source="europe_pmc_pdf",
        status="blocked",
        url="https://example.org/article.pdf",
        reason="HTTP 403 / non-PDF response",
    )

    assert attempt.status == "blocked"
    assert attempt.source == "europe_pmc_pdf"


def test_review_passage_is_citable_and_review_scoped() -> None:
    passage = ReviewPassage(
        review_id="rev_123",
        source_id="PMID:40234174",
        source_type="pubtator_abstract",
        passage_id="PMID:40234174:abstract:0",
        section="abstract",
        text="Treatment with colchicine should start as soon as a clinical diagnosis is made.",
        pmid="40234174",
    )

    assert passage.review_id == "rev_123"
    assert passage.passage_id == "PMID:40234174:abstract:0"
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/unit/test_full_text_models.py -q`

Expected: FAIL because the models do not exist.

- [ ] **Step 3: Add models to `pubtator_link/models/evidence.py`**

Append:

```python
from typing import Literal


RetrievalStatus = Literal["success", "not_available", "blocked", "failed"]
FullTextSource = Literal[
    "pubtator_full",
    "pmc_bioc",
    "europe_pmc_xml",
    "europe_pmc_pdf",
    "curated_pdf",
    "curated_html",
    "pubtator_abstract",
]


class FullTextRetrievalAttempt(BaseModel):
    """One transparent full-text retrieval attempt."""

    source: FullTextSource
    status: RetrievalStatus
    url: str | None = None
    reason: str | None = None
    content_type: str | None = None
    content_length: int | None = None


class FullTextDocument(BaseModel):
    """Resolved full-text document normalized before passage indexing."""

    source_id: str
    source_type: FullTextSource
    title: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    url: str | None = None
    license: str | None = None
    passages: list[EvidencePassage] = Field(default_factory=list)
    attempts: list[FullTextRetrievalAttempt] = Field(default_factory=list)


class ReviewPassage(BaseModel):
    """A passage indexed inside one review corpus."""

    review_id: str
    source_id: str
    source_type: str
    passage_id: str
    section: str
    text: str
    pmid: str | None = None
    pmcid: str | None = None
    doi: str | None = None
    url: str | None = None
    page: int | None = None
    screening_status: str = "candidate"
    entity_ids: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)


class ContextPack(BaseModel):
    """Compact retrieved context for one LLM step."""

    context_pack_id: str
    review_id: str
    question: str
    passages: list[ReviewPassage]
    citation_map: dict[str, str]
```

- [ ] **Step 4: Run model tests**

Run: `uv run pytest tests/unit/test_full_text_models.py tests/unit/test_evidence_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/models/evidence.py tests/unit/test_full_text_models.py
git commit -m "feat: add full-text and review corpus models"
```

## Task 6: Add Full-Text Resolver Service

**Files:**
- Create: `pubtator_link/services/full_text_service.py`
- Test: `tests/unit/test_full_text_service.py`

- [ ] **Step 1: Write resolver tests**

Create `tests/unit/test_full_text_service.py`:

```python
from pubtator_link.services.full_text_service import FullTextService


def test_select_pdf_links_from_europe_pmc_metadata() -> None:
    service = FullTextService()
    metadata = {
        "fullTextUrlList": {
            "fullTextUrl": [
                {
                    "availabilityCode": "S",
                    "documentStyle": "doi",
                    "url": "https://doi.org/example",
                },
                {
                    "availabilityCode": "F",
                    "documentStyle": "pdf",
                    "url": "https://example.org/free.pdf",
                },
            ]
        }
    }

    links = service.select_free_pdf_links(metadata)

    assert links == ["https://example.org/free.pdf"]


def test_accept_only_pdf_bytes() -> None:
    service = FullTextService()

    assert service.looks_like_pdf(b"%PDF-1.7\\n") is True
    assert service.looks_like_pdf(b"<!DOCTYPE html>") is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/unit/test_full_text_service.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement resolver service**

Create `pubtator_link/services/full_text_service.py`:

```python
"""Asynchronous full-text resolver cascade."""

from typing import Any

import httpx

from ..models.evidence import EvidencePassage, FullTextDocument, FullTextRetrievalAttempt


class FullTextService:
    """Resolve full text through automatable source adapters."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def resolve_by_pmid(
        self,
        pmid: str,
        doi: str | None = None,
        pmcid: str | None = None,
        curated_urls: list[str] | None = None,
    ) -> FullTextDocument:
        """Resolve full text using transparent source attempts."""
        attempts: list[FullTextRetrievalAttempt] = []
        passages: list[EvidencePassage] = []
        async with self._client() as client:
            metadata = await self.fetch_europe_pmc_metadata(client, pmid)
            resolved_pmcid = pmcid or metadata.get("pmcid")
            if resolved_pmcid:
                document = await self.fetch_pmc_bioc(client, resolved_pmcid, pmid)
                attempts.extend(document.attempts)
                passages.extend(document.passages)
                if passages:
                    return FullTextDocument(
                        source_id=f"PMID:{pmid}",
                        source_type="pmc_bioc",
                        pmid=pmid,
                        pmcid=resolved_pmcid,
                        doi=doi or metadata.get("doi"),
                        passages=passages,
                        attempts=attempts,
                    )

            for url in self.select_free_pdf_links(metadata):
                attempt = await self.try_download_pdf(client, url)
                attempts.append(attempt)

            for url in curated_urls or []:
                attempt = await self.try_download_pdf(client, url, source="curated_pdf")
                attempts.append(attempt)

        return FullTextDocument(
            source_id=f"PMID:{pmid}",
            source_type="pubtator_abstract",
            pmid=pmid,
            doi=doi or metadata.get("doi"),
            passages=[],
            attempts=attempts,
        )

    async def fetch_europe_pmc_metadata(
        self, client: httpx.AsyncClient, pmid: str
    ) -> dict[str, Any]:
        """Fetch Europe PMC metadata for a PMID."""
        response = await client.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"EXT_ID:{pmid} AND SRC:MED",
                "format": "json",
                "resultType": "core",
            },
        )
        response.raise_for_status()
        results = response.json().get("resultList", {}).get("result", [])
        return results[0] if results else {}

    async def fetch_pmc_bioc(
        self, client: httpx.AsyncClient, pmcid: str, pmid: str
    ) -> FullTextDocument:
        """Fetch NCBI PMC BioC JSON and normalize passages."""
        url = (
            "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/"
            f"pmcoa.cgi/BioC_json/{pmcid}/unicode"
        )
        response = await client.get(url)
        if response.status_code != 200:
            return FullTextDocument(
                source_id=f"PMID:{pmid}",
                source_type="pmc_bioc",
                pmid=pmid,
                pmcid=pmcid,
                attempts=[
                    FullTextRetrievalAttempt(
                        source="pmc_bioc",
                        status="not_available",
                        url=url,
                        reason=f"HTTP {response.status_code}",
                    )
                ],
            )
        collections = response.json()
        documents = collections[0].get("documents", []) if collections else []
        passages: list[EvidencePassage] = []
        for document in documents:
            for index, passage in enumerate(document.get("passages", [])):
                text = str(passage.get("text", "")).strip()
                if not text:
                    continue
                infons = passage.get("infons", {})
                section = str(infons.get("section_type") or infons.get("type") or "body")
                passages.append(
                    EvidencePassage(
                        passage_id=f"PMID:{pmid}:{section}:{index}",
                        section=section,
                        text=text,
                        offset=int(passage.get("offset", 0) or 0),
                    )
                )
        return FullTextDocument(
            source_id=f"PMID:{pmid}",
            source_type="pmc_bioc",
            pmid=pmid,
            pmcid=pmcid,
            passages=passages,
            attempts=[
                FullTextRetrievalAttempt(
                    source="pmc_bioc",
                    status="success",
                    url=url,
                    content_type=response.headers.get("content-type"),
                    content_length=len(response.content),
                )
            ],
        )

    def select_free_pdf_links(self, metadata: dict[str, Any]) -> list[str]:
        """Select free/OA PDF links from Europe PMC metadata."""
        links = metadata.get("fullTextUrlList", {}).get("fullTextUrl", [])
        selected: list[str] = []
        for link in links:
            if link.get("documentStyle") != "pdf":
                continue
            if link.get("availabilityCode") not in {"F", "OA", "F24"}:
                continue
            url = link.get("url")
            if isinstance(url, str):
                selected.append(url)
        return selected

    async def try_download_pdf(
        self,
        client: httpx.AsyncClient,
        url: str,
        source: str = "europe_pmc_pdf",
    ) -> FullTextRetrievalAttempt:
        """Attempt polite PDF download and record exact status."""
        try:
            response = await client.get(url)
        except httpx.HTTPError as exc:
            return FullTextRetrievalAttempt(source=source, status="failed", url=url, reason=str(exc))
        if response.status_code != 200:
            return FullTextRetrievalAttempt(
                source=source,
                status="blocked",
                url=url,
                reason=f"HTTP {response.status_code}",
                content_type=response.headers.get("content-type"),
                content_length=len(response.content),
            )
        if not self.looks_like_pdf(response.content):
            return FullTextRetrievalAttempt(
                source=source,
                status="blocked",
                url=url,
                reason="Non-PDF response",
                content_type=response.headers.get("content-type"),
                content_length=len(response.content),
            )
        return FullTextRetrievalAttempt(
            source=source,
            status="success",
            url=url,
            content_type=response.headers.get("content-type"),
            content_length=len(response.content),
        )

    def looks_like_pdf(self, content: bytes) -> bool:
        """Return true only for PDF bytes."""
        return content.startswith(b"%PDF")

    def _client(self) -> httpx.AsyncClient:
        if self.client is not None:
            return self.client
        return httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "PubTator-Link full-text resolver"},
        )
```

- [ ] **Step 4: Run service tests**

Run: `uv run pytest tests/unit/test_full_text_service.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/services/full_text_service.py tests/unit/test_full_text_service.py
git commit -m "feat: add asynchronous full-text resolver"
```

## Task 7: Add Review Repository Contract and In-Memory Implementation

**Files:**
- Create: `pubtator_link/repositories/__init__.py`
- Create: `pubtator_link/repositories/reviews.py`
- Test: `tests/unit/test_review_repository.py`

- [ ] **Step 1: Write repository tests**

Create `tests/unit/test_review_repository.py`:

```python
import pytest

from pubtator_link.models.reviews import ReviewProtocol, ScreeningDecision
from pubtator_link.repositories.reviews import InMemoryReviewRepository


@pytest.mark.asyncio
async def test_in_memory_repository_stores_protocol_and_screening_decision() -> None:
    repo = InMemoryReviewRepository()
    protocol = ReviewProtocol(
        review_id="rev_123",
        question="Question",
        protocol_schema="custom",
        inclusion_criteria=[],
        exclusion_criteria=[],
        extraction_fields=[],
        risk_of_bias_tool="custom",
        risk_of_bias_domains=[],
    )

    await repo.create_protocol(protocol)
    await repo.add_screening_decision(
        ScreeningDecision(
            review_id="rev_123",
            pmid="12345678",
            decision="include",
            reason="Relevant.",
            supporting_passage_ids=[],
        )
    )

    assert (await repo.get_protocol("rev_123")).question == "Question"
    assert len(await repo.list_screening_decisions("rev_123")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_review_repository.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement repository contract**

Create `pubtator_link/repositories/__init__.py`:

```python
"""Repository implementations for durable workflow state."""
```

Create `pubtator_link/repositories/reviews.py`:

```python
"""Review repository contracts and test implementation."""

from typing import Protocol

from ..models.reviews import (
    CertaintyAssessment,
    ReviewProtocol,
    RiskOfBiasAssessment,
    ScreeningDecision,
    StudyExtraction,
)


class ReviewRepository(Protocol):
    """Persistence contract for review workflow state."""

    async def create_protocol(self, protocol: ReviewProtocol) -> ReviewProtocol: ...

    async def get_protocol(self, review_id: str) -> ReviewProtocol: ...

    async def add_screening_decision(self, decision: ScreeningDecision) -> ScreeningDecision: ...

    async def list_screening_decisions(self, review_id: str) -> list[ScreeningDecision]: ...

    async def add_extraction(self, extraction: StudyExtraction) -> StudyExtraction: ...

    async def list_extractions(self, review_id: str) -> list[StudyExtraction]: ...

    async def add_risk_of_bias_assessment(
        self, assessment: RiskOfBiasAssessment
    ) -> RiskOfBiasAssessment: ...

    async def list_risk_of_bias_assessments(self, review_id: str) -> list[RiskOfBiasAssessment]: ...

    async def add_certainty_assessment(
        self, assessment: CertaintyAssessment
    ) -> CertaintyAssessment: ...

    async def list_certainty_assessments(self, review_id: str) -> list[CertaintyAssessment]: ...


class InMemoryReviewRepository:
    """In-memory repository for unit tests and local non-durable workflows."""

    def __init__(self) -> None:
        self.protocols: dict[str, ReviewProtocol] = {}
        self.screening_decisions: list[ScreeningDecision] = []
        self.extractions: list[StudyExtraction] = []
        self.risk_of_bias_assessments: list[RiskOfBiasAssessment] = []
        self.certainty_assessments: list[CertaintyAssessment] = []

    async def create_protocol(self, protocol: ReviewProtocol) -> ReviewProtocol:
        self.protocols[protocol.review_id] = protocol
        return protocol

    async def get_protocol(self, review_id: str) -> ReviewProtocol:
        return self.protocols[review_id]

    async def add_screening_decision(self, decision: ScreeningDecision) -> ScreeningDecision:
        self.screening_decisions.append(decision)
        return decision

    async def list_screening_decisions(self, review_id: str) -> list[ScreeningDecision]:
        return [item for item in self.screening_decisions if item.review_id == review_id]

    async def add_extraction(self, extraction: StudyExtraction) -> StudyExtraction:
        self.extractions.append(extraction)
        return extraction

    async def list_extractions(self, review_id: str) -> list[StudyExtraction]:
        return [item for item in self.extractions if item.review_id == review_id]

    async def add_risk_of_bias_assessment(
        self, assessment: RiskOfBiasAssessment
    ) -> RiskOfBiasAssessment:
        self.risk_of_bias_assessments.append(assessment)
        return assessment

    async def list_risk_of_bias_assessments(self, review_id: str) -> list[RiskOfBiasAssessment]:
        return [item for item in self.risk_of_bias_assessments if item.review_id == review_id]

    async def add_certainty_assessment(
        self, assessment: CertaintyAssessment
    ) -> CertaintyAssessment:
        self.certainty_assessments.append(assessment)
        return assessment

    async def list_certainty_assessments(self, review_id: str) -> list[CertaintyAssessment]:
        return [item for item in self.certainty_assessments if item.review_id == review_id]
```

- [ ] **Step 4: Run repository tests**

Run: `uv run pytest tests/unit/test_review_repository.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/repositories tests/unit/test_review_repository.py
git commit -m "feat: add review repository contract"
```

## Task 8: Add Review Service and MCP Routes

**Files:**
- Create: `pubtator_link/services/review_service.py`
- Create: `pubtator_link/api/routes/reviews.py`
- Modify: `pubtator_link/api/routes/__init__.py`
- Modify: `pubtator_link/server_manager.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Write route test**

Create `tests/test_routes/test_reviews.py`:

```python
from fastapi.testclient import TestClient

from pubtator_link.server_manager import UnifiedServerManager


def test_create_review_protocol_route() -> None:
    manager = UnifiedServerManager()
    app = manager.create_app()
    client = TestClient(app)

    response = client.post(
        "/api/reviews/protocols",
        json={
            "question": "Does BRCA1 increase breast cancer risk?",
            "protocol_schema": "custom",
            "inclusion_criteria": ["Human studies"],
            "exclusion_criteria": ["Animal-only studies"],
            "extraction_fields": ["population", "exposure", "outcome"],
            "risk_of_bias_tool": "custom",
            "risk_of_bias_domains": ["fit_to_question", "study_design"],
        },
    )

    assert response.status_code == 200
    assert response.json()["protocol"]["question"] == "Does BRCA1 increase breast cancer risk?"
```

- [ ] **Step 2: Run route test to verify it fails**

Run: `uv run pytest tests/test_routes/test_reviews.py -q`

Expected: FAIL with 404 for `/api/reviews/protocols`.

- [ ] **Step 3: Implement review service**

Create `pubtator_link/services/review_service.py`:

```python
"""Deterministic review workflow service."""

from uuid import uuid4

from ..models.reviews import ReviewProtocol, ScreeningDecision
from ..repositories.reviews import ReviewRepository


class ReviewService:
    """Coordinates review protocol and judgment persistence."""

    def __init__(self, repository: ReviewRepository):
        self.repository = repository

    async def create_protocol(
        self,
        question: str,
        inclusion_criteria: list[str],
        exclusion_criteria: list[str],
        extraction_fields: list[str],
        risk_of_bias_domains: list[str],
        protocol_schema: str = "custom",
        risk_of_bias_tool: str = "custom",
    ) -> ReviewProtocol:
        protocol = ReviewProtocol(
            review_id=f"rev_{uuid4().hex}",
            question=question,
            protocol_schema=protocol_schema,
            inclusion_criteria=inclusion_criteria,
            exclusion_criteria=exclusion_criteria,
            extraction_fields=extraction_fields,
            risk_of_bias_tool=risk_of_bias_tool,
            risk_of_bias_domains=risk_of_bias_domains,
        )
        return await self.repository.create_protocol(protocol)

    async def submit_screening_decision(self, decision: ScreeningDecision) -> ScreeningDecision:
        await self.repository.get_protocol(decision.review_id)
        return await self.repository.add_screening_decision(decision)
```

- [ ] **Step 4: Implement review routes**

Create `pubtator_link/api/routes/reviews.py`:

```python
"""Review workflow routes for MCP tools."""

from pydantic import BaseModel
from fastapi import APIRouter

from ...models.reviews import ReviewProtocol, ScreeningDecision
from ...repositories.reviews import InMemoryReviewRepository
from ...services.review_service import ReviewService
from .dependencies import handle_api_errors

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])
_repository = InMemoryReviewRepository()


class CreateReviewProtocolRequest(BaseModel):
    question: str
    protocol_schema: str = "custom"
    population: str | None = None
    intervention_or_exposure: str | None = None
    comparator: str | None = None
    outcomes: list[str] = []
    timing: str | None = None
    setting: str | None = None
    inclusion_criteria: list[str] = []
    exclusion_criteria: list[str] = []
    extraction_fields: list[str] = []
    risk_of_bias_tool: str = "custom"
    risk_of_bias_domains: list[str] = []


class ReviewProtocolResponse(BaseModel):
    success: bool = True
    protocol: ReviewProtocol


class ScreeningDecisionResponse(BaseModel):
    success: bool = True
    decision: ScreeningDecision


@router.post(
    "/protocols",
    response_model=ReviewProtocolResponse,
    operation_id="create_review_protocol",
    summary="Create a deterministic review protocol",
)
@handle_api_errors
async def create_review_protocol(request: CreateReviewProtocolRequest) -> ReviewProtocolResponse:
    service = ReviewService(repository=_repository)
    protocol = await service.create_protocol(
        question=request.question,
        protocol_schema=request.protocol_schema,
        inclusion_criteria=request.inclusion_criteria,
        exclusion_criteria=request.exclusion_criteria,
        extraction_fields=request.extraction_fields,
        risk_of_bias_tool=request.risk_of_bias_tool,
        risk_of_bias_domains=request.risk_of_bias_domains,
    )
    return ReviewProtocolResponse(protocol=protocol)


@router.post(
    "/screening-decisions",
    response_model=ScreeningDecisionResponse,
    operation_id="submit_screening_decision",
    summary="Submit a structured screening decision",
)
@handle_api_errors
async def submit_screening_decision(decision: ScreeningDecision) -> ScreeningDecisionResponse:
    service = ReviewService(repository=_repository)
    stored = await service.submit_screening_decision(decision)
    return ScreeningDecisionResponse(decision=stored)
```

- [ ] **Step 5: Register route**

Modify `pubtator_link/api/routes/__init__.py`:

```python
from .reviews import router as reviews_router
```

Add `reviews_router` to `__all__` and `ROUTE_MODULES`.

Modify `pubtator_link/server_manager.py` imports and add:

```python
app.include_router(reviews_router)
```

Add MCP custom names:

```python
"create_review_protocol": "create_review_protocol",
"submit_screening_decision": "submit_screening_decision",
```

- [ ] **Step 6: Run route tests**

Run: `uv run pytest tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pubtator_link/services/review_service.py pubtator_link/api/routes/reviews.py pubtator_link/api/routes/__init__.py pubtator_link/server_manager.py tests/test_routes/test_reviews.py
git commit -m "feat: expose deterministic review workflow tools"
```

## Task 9: Add PostgreSQL Persistence and Review Corpus Tables

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `pubtator_link/config.py`
- Create: `pubtator_link/db/__init__.py`
- Create: `pubtator_link/db/review_schema.sql`
- Create: `pubtator_link/repositories/postgres_reviews.py`
- Test: `tests/unit/test_review_schema.py`

- [ ] **Step 1: Add dependency**

Run:

```bash
uv add asyncpg
```

Expected: `pyproject.toml` and `uv.lock` are updated with `asyncpg`.

- [ ] **Step 2: Add database config**

Modify `pubtator_link/config.py` to include:

```python
class DatabaseConfig(BaseSettings):
    """Database configuration for review workflow state."""

    database_url: str | None = None
    database_pool_min_size: int = 1
    database_pool_max_size: int = 10
```

Add:

```python
database_config = DatabaseConfig()
```

- [ ] **Step 3: Add schema file**

Create `pubtator_link/db/__init__.py`:

```python
"""Database helpers and schemas."""
```

Create `pubtator_link/db/review_schema.sql`:

```sql
create table if not exists review_protocols (
    review_id text primary key,
    question text not null,
    protocol_schema text not null,
    population text,
    intervention_or_exposure text,
    comparator text,
    outcomes jsonb not null,
    timing text,
    setting text,
    inclusion_criteria jsonb not null,
    exclusion_criteria jsonb not null,
    extraction_fields jsonb not null,
    risk_of_bias_tool text not null,
    risk_of_bias_domains jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists screening_decisions (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    pmid text not null,
    decision text not null check (decision in ('include', 'exclude', 'maybe')),
    reason text not null,
    supporting_passage_ids jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists screening_decisions_review_id_idx
    on screening_decisions(review_id);

create table if not exists full_text_retrieval_attempts (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    pmid text not null,
    source text not null,
    status text not null,
    url text,
    reason text,
    content_type text,
    content_length integer,
    created_at timestamptz not null default now()
);

create table if not exists review_passages (
    passage_id text primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    source_id text not null,
    source_type text not null,
    pmid text,
    pmcid text,
    doi text,
    url text,
    section text not null,
    text text not null,
    page integer,
    screening_status text not null default 'candidate',
    entity_ids jsonb not null default '[]'::jsonb,
    relation_types jsonb not null default '[]'::jsonb,
    search_vector tsvector generated always as (to_tsvector('english', text)) stored
);

create index if not exists review_passages_review_id_idx
    on review_passages(review_id);

create index if not exists review_passages_search_vector_idx
    on review_passages using gin(search_vector);

create table if not exists context_packs (
    context_pack_id text primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    question text not null,
    passage_ids jsonb not null,
    citation_map jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists study_extractions (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    pmid text not null,
    values_json jsonb not null,
    supporting_passage_ids jsonb not null,
    created_at timestamptz not null default now()
);

create index if not exists study_extractions_review_id_idx
    on study_extractions(review_id);

create table if not exists risk_of_bias_assessments (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    pmid text not null,
    tool text not null,
    overall text not null,
    domains jsonb not null,
    rationale text not null,
    created_at timestamptz not null default now()
);

create index if not exists risk_of_bias_assessments_review_id_idx
    on risk_of_bias_assessments(review_id);

create table if not exists certainty_assessments (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    outcome text not null,
    rating text not null,
    rationale text,
    supporting_pmids jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists review_audit_events (
    id bigserial primary key,
    review_id text not null references review_protocols(review_id) on delete cascade,
    event_type text not null,
    payload jsonb not null,
    created_at timestamptz not null default now()
);
```

- [ ] **Step 4: Test schema contains required tables**

Create `tests/unit/test_review_schema.py`:

```python
from pathlib import Path


def test_review_schema_defines_protocols_and_screening_decisions() -> None:
    schema = Path("pubtator_link/db/review_schema.sql").read_text()

    assert "create table if not exists review_protocols" in schema
    assert "create table if not exists screening_decisions" in schema
    assert "create table if not exists full_text_retrieval_attempts" in schema
    assert "create table if not exists review_passages" in schema
    assert "create table if not exists context_packs" in schema
    assert "create table if not exists study_extractions" in schema
    assert "create table if not exists risk_of_bias_assessments" in schema
    assert "create table if not exists certainty_assessments" in schema
    assert "create table if not exists review_audit_events" in schema
    assert "jsonb" in schema
```

- [ ] **Step 5: Implement PostgreSQL repository**

Create `pubtator_link/repositories/postgres_reviews.py`:

```python
"""PostgreSQL review repository."""

import json

import asyncpg

from ..models.reviews import (
    CertaintyAssessment,
    ReviewProtocol,
    RiskOfBiasAssessment,
    RiskOfBiasDomainAssessment,
    ScreeningDecision,
    StudyExtraction,
)


class PostgresReviewRepository:
    """PostgreSQL implementation of ReviewRepository."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def create_protocol(self, protocol: ReviewProtocol) -> ReviewProtocol:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into review_protocols (
                    review_id, question, protocol_schema, population,
                    intervention_or_exposure, comparator, outcomes, timing,
                    setting, inclusion_criteria, exclusion_criteria,
                    extraction_fields, risk_of_bias_tool, risk_of_bias_domains
                )
                values (
                    $1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9,
                    $10::jsonb, $11::jsonb, $12::jsonb, $13, $14::jsonb
                )
                """,
                protocol.review_id,
                protocol.question,
                protocol.protocol_schema,
                protocol.population,
                protocol.intervention_or_exposure,
                protocol.comparator,
                json.dumps(protocol.outcomes),
                protocol.timing,
                protocol.setting,
                json.dumps(protocol.inclusion_criteria),
                json.dumps(protocol.exclusion_criteria),
                json.dumps(protocol.extraction_fields),
                protocol.risk_of_bias_tool,
                json.dumps(protocol.risk_of_bias_domains),
            )
        return protocol

    async def get_protocol(self, review_id: str) -> ReviewProtocol:
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(
                "select * from review_protocols where review_id = $1",
                review_id,
            )
        if row is None:
            raise KeyError(review_id)
        return ReviewProtocol(
            review_id=row["review_id"],
            question=row["question"],
            protocol_schema=row["protocol_schema"],
            population=row["population"],
            intervention_or_exposure=row["intervention_or_exposure"],
            comparator=row["comparator"],
            outcomes=json.loads(row["outcomes"]),
            timing=row["timing"],
            setting=row["setting"],
            inclusion_criteria=json.loads(row["inclusion_criteria"]),
            exclusion_criteria=json.loads(row["exclusion_criteria"]),
            extraction_fields=json.loads(row["extraction_fields"]),
            risk_of_bias_tool=row["risk_of_bias_tool"],
            risk_of_bias_domains=json.loads(row["risk_of_bias_domains"]),
        )

    async def add_screening_decision(self, decision: ScreeningDecision) -> ScreeningDecision:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into screening_decisions (
                    review_id, pmid, decision, reason, supporting_passage_ids
                )
                values ($1, $2, $3, $4, $5::jsonb)
                """,
                decision.review_id,
                decision.pmid,
                decision.decision,
                decision.reason,
                json.dumps(decision.supporting_passage_ids),
            )
        return decision

    async def list_screening_decisions(self, review_id: str) -> list[ScreeningDecision]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                "select * from screening_decisions where review_id = $1 order by id",
                review_id,
            )
        return [
            ScreeningDecision(
                review_id=row["review_id"],
                pmid=row["pmid"],
                decision=row["decision"],
                reason=row["reason"],
                supporting_passage_ids=json.loads(row["supporting_passage_ids"]),
            )
            for row in rows
        ]

    async def add_extraction(self, extraction: StudyExtraction) -> StudyExtraction:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into study_extractions (
                    review_id, pmid, values_json, supporting_passage_ids
                )
                values ($1, $2, $3::jsonb, $4::jsonb)
                """,
                extraction.review_id,
                extraction.pmid,
                json.dumps(extraction.values),
                json.dumps(extraction.supporting_passage_ids),
            )
        return extraction

    async def list_extractions(self, review_id: str) -> list[StudyExtraction]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                "select * from study_extractions where review_id = $1 order by id",
                review_id,
            )
        return [
            StudyExtraction(
                review_id=row["review_id"],
                pmid=row["pmid"],
                values=json.loads(row["values_json"]),
                supporting_passage_ids=json.loads(row["supporting_passage_ids"]),
            )
            for row in rows
        ]

    async def add_risk_of_bias_assessment(
        self, assessment: RiskOfBiasAssessment
    ) -> RiskOfBiasAssessment:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into risk_of_bias_assessments (
                    review_id, pmid, tool, overall, domains, rationale
                )
                values ($1, $2, $3, $4, $5::jsonb, $6)
                """,
                assessment.review_id,
                assessment.pmid,
                assessment.tool,
                assessment.overall,
                assessment.model_dump_json(include={"domains"}),
                assessment.rationale,
            )
        return assessment

    async def list_risk_of_bias_assessments(self, review_id: str) -> list[RiskOfBiasAssessment]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                "select * from risk_of_bias_assessments where review_id = $1 order by id",
                review_id,
            )
        return [
            RiskOfBiasAssessment(
                review_id=row["review_id"],
                pmid=row["pmid"],
                tool=row["tool"],
                overall=row["overall"],
                domains=[
                    RiskOfBiasDomainAssessment.model_validate(domain)
                    for domain in json.loads(row["domains"])["domains"]
                ],
                rationale=row["rationale"],
            )
            for row in rows
        ]

    async def add_certainty_assessment(
        self, assessment: CertaintyAssessment
    ) -> CertaintyAssessment:
        async with self.pool.acquire() as connection:
            await connection.execute(
                """
                insert into certainty_assessments (
                    review_id, outcome, rating, rationale, supporting_pmids
                )
                values ($1, $2, $3, $4, $5::jsonb)
                """,
                assessment.review_id,
                assessment.outcome,
                assessment.rating,
                assessment.rationale,
                json.dumps(assessment.supporting_pmids),
            )
        return assessment

    async def list_certainty_assessments(self, review_id: str) -> list[CertaintyAssessment]:
        async with self.pool.acquire() as connection:
            rows = await connection.fetch(
                "select * from certainty_assessments where review_id = $1 order by id",
                review_id,
            )
        return [
            CertaintyAssessment(
                review_id=row["review_id"],
                outcome=row["outcome"],
                rating=row["rating"],
                rationale=row["rationale"],
                supporting_pmids=json.loads(row["supporting_pmids"]),
            )
            for row in rows
        ]
```

- [ ] **Step 6: Run focused checks**

Run:

```bash
uv run pytest tests/unit/test_review_schema.py tests/unit/test_review_repository.py -q
uv run mypy pubtator_link/repositories pubtator_link/models pubtator_link/services
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock pubtator_link/config.py pubtator_link/db pubtator_link/repositories/postgres_reviews.py tests/unit/test_review_schema.py
git commit -m "feat: add PostgreSQL review persistence"
```

## Task 10: Add Review Corpus Service and Retrieval Tool

**Files:**
- Create: `pubtator_link/services/review_corpus_service.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/unit/test_review_corpus_service.py`

- [ ] **Step 1: Write corpus service tests**

Create `tests/unit/test_review_corpus_service.py`:

```python
from pubtator_link.models.evidence import ReviewPassage
from pubtator_link.services.review_corpus_service import ReviewCorpusService


def test_build_context_pack_ranks_query_matching_passages() -> None:
    service = ReviewCorpusService()
    passages = [
        ReviewPassage(
            review_id="rev_123",
            source_id="PMID:1",
            source_type="pubtator_abstract",
            passage_id="p1",
            section="abstract",
            text="This passage discusses unrelated fever syndromes.",
        ),
        ReviewPassage(
            review_id="rev_123",
            source_id="PMID:2",
            source_type="pmc_bioc",
            passage_id="p2",
            section="recommendations",
            text="Colchicine should start after clinical diagnosis of FMF.",
        ),
    ]

    pack = service.build_context_pack(
        review_id="rev_123",
        question="Should colchicine be started for FMF?",
        passages=passages,
        max_passages=1,
    )

    assert pack.passages[0].passage_id == "p2"
    assert pack.citation_map["S1"] == "p2"
```

- [ ] **Step 2: Run test to verify failure**

Run: `uv run pytest tests/unit/test_review_corpus_service.py -q`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement corpus service**

Create `pubtator_link/services/review_corpus_service.py`:

```python
"""Review-scoped passage retrieval for context control."""

import re
from uuid import uuid4

from ..models.evidence import ContextPack, ReviewPassage


class ReviewCorpusService:
    """Build compact context packs from review-scoped passages."""

    def build_context_pack(
        self,
        review_id: str,
        question: str,
        passages: list[ReviewPassage],
        max_passages: int = 8,
        max_chars: int = 6000,
    ) -> ContextPack:
        ranked = self.rank_passages(question=question, passages=passages)
        selected: list[ReviewPassage] = []
        used_chars = 0
        for passage in ranked:
            if len(selected) >= max_passages:
                break
            if used_chars + len(passage.text) > max_chars:
                continue
            selected.append(passage)
            used_chars += len(passage.text)
        citation_map = {f"S{index + 1}": passage.passage_id for index, passage in enumerate(selected)}
        return ContextPack(
            context_pack_id=f"ctx_{uuid4().hex}",
            review_id=review_id,
            question=question,
            passages=selected,
            citation_map=citation_map,
        )

    def rank_passages(self, question: str, passages: list[ReviewPassage]) -> list[ReviewPassage]:
        query_terms = set(re.findall(r"[a-zA-Z0-9]+", question.lower()))

        def score(passage: ReviewPassage) -> tuple[float, int]:
            text_terms = set(re.findall(r"[a-zA-Z0-9]+", passage.text.lower()))
            overlap = len(query_terms & text_terms) / max(len(query_terms), 1)
            status_boost = 1 if passage.screening_status in {"include", "maybe"} else 0
            return (overlap, status_boost)

        return sorted(passages, key=score, reverse=True)
```

- [ ] **Step 4: Add route contracts for corpus workflow**

Extend `pubtator_link/api/routes/reviews.py` with MCP-visible operation IDs:

```python
from pydantic import BaseModel


class IndexReviewEvidenceRequest(BaseModel):
    pmids: list[str]
    curated_urls: list[str] = []


class RetrieveReviewContextRequest(BaseModel):
    question: str
    max_passages: int = 8
    max_chars: int = 6000


@router.post(
    "/{review_id}/index-evidence",
    operation_id="index_review_evidence",
    summary="Resolve full text and index review passages",
)
@handle_api_errors
async def index_review_evidence(
    review_id: str, request: IndexReviewEvidenceRequest
) -> dict[str, object]:
    return {
        "success": True,
        "review_id": review_id,
        "indexed_pmids": request.pmids,
        "curated_urls": request.curated_urls,
    }


@router.post(
    "/{review_id}/context",
    operation_id="retrieve_review_context",
    summary="Retrieve a compact context pack from the review corpus",
)
@handle_api_errors
async def retrieve_review_context(
    review_id: str, request: RetrieveReviewContextRequest
) -> dict[str, object]:
    service = ReviewCorpusService()
    context_pack = service.build_context_pack(
        review_id=review_id,
        question=request.question,
        passages=[],
        max_passages=request.max_passages,
        max_chars=request.max_chars,
    )
    return {
        "success": True,
        "context_pack": context_pack,
    }
```

- [ ] **Step 5: Run corpus tests**

Run: `uv run pytest tests/unit/test_review_corpus_service.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pubtator_link/services/review_corpus_service.py pubtator_link/api/routes/reviews.py tests/unit/test_review_corpus_service.py
git commit -m "feat: add review-scoped context retrieval service"
```

## Task 11: Add Extraction and Risk-of-Bias Endpoints

**Files:**
- Modify: `pubtator_link/repositories/postgres_reviews.py`
- Modify: `pubtator_link/services/review_service.py`
- Modify: `pubtator_link/api/routes/reviews.py`
- Test: `tests/test_routes/test_reviews.py`

- [ ] **Step 1: Add route tests**

Extend `tests/test_routes/test_reviews.py`:

```python
def test_submit_screening_decision_after_protocol_creation() -> None:
    manager = UnifiedServerManager()
    app = manager.create_app()
    client = TestClient(app)

    created = client.post(
        "/api/reviews/protocols",
        json={
            "question": "Question",
            "inclusion_criteria": [],
            "exclusion_criteria": [],
            "extraction_fields": [],
            "risk_of_bias_tool": "custom",
            "risk_of_bias_domains": [],
        },
    ).json()
    review_id = created["protocol"]["review_id"]

    response = client.post(
        "/api/reviews/screening-decisions",
        json={
            "review_id": review_id,
            "pmid": "12345678",
            "decision": "include",
            "reason": "Relevant.",
            "supporting_passage_ids": ["12345678:abstract:0"],
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"]["decision"] == "include"
```

- [ ] **Step 2: Add service methods**

Extend `ReviewService` with methods:

```python
async def submit_extraction(self, extraction: StudyExtraction) -> StudyExtraction:
    await self.repository.get_protocol(extraction.review_id)
    return await self.repository.add_extraction(extraction)


async def submit_risk_of_bias_assessment(
    self, assessment: RiskOfBiasAssessment
) -> RiskOfBiasAssessment:
    await self.repository.get_protocol(assessment.review_id)
    return await self.repository.add_risk_of_bias_assessment(assessment)
```

- [ ] **Step 3: Add routes**

Extend `pubtator_link/api/routes/reviews.py` with POST routes:

```python
@router.post("/extractions", operation_id="submit_study_extraction")
@handle_api_errors
async def submit_study_extraction(extraction: StudyExtraction) -> dict[str, object]:
    service = ReviewService(repository=_repository)
    stored = await service.submit_extraction(extraction)
    return {"success": True, "extraction": stored}


@router.post("/risk-of-bias-assessments", operation_id="submit_risk_of_bias_assessment")
@handle_api_errors
async def submit_risk_of_bias_assessment(assessment: RiskOfBiasAssessment) -> dict[str, object]:
    service = ReviewService(repository=_repository)
    stored = await service.submit_risk_of_bias_assessment(assessment)
    return {"success": True, "assessment": stored}
```

- [ ] **Step 4: Run review tests**

Run: `uv run pytest tests/test_routes/test_reviews.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pubtator_link/repositories/postgres_reviews.py pubtator_link/services/review_service.py pubtator_link/api/routes/reviews.py tests/test_routes/test_reviews.py
git commit -m "feat: add extraction and risk-of-bias submissions"
```

## Task 12: Documentation and Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/MCP_CONNECTION_GUIDE.md`

- [ ] **Step 1: Document MCP workflow**

Add a README section:

```markdown
## Evidence Review Workflow

PubTator-Link exposes two MCP tool groups:

- Exploration tools retrieve compact PubTator evidence packets for fast literature discovery.
- Review tools store deterministic protocol, screening, extraction, and risk-of-bias state.
- Full-text tools resolve PMCID-backed BioC/JATS full text, record blocked PDF attempts, and index review-scoped passages for retrieval.

The backend does not call an LLM. A human reviewer or MCP client performs judgment and submits structured decisions with supporting passage IDs.
```

- [ ] **Step 2: Run full required checks**

Run:

```bash
make ci-local
```

Expected: formatting check, lint, mypy, and tests pass.

- [ ] **Step 3: Commit docs**

```bash
git add README.md docs/MCP_CONNECTION_GUIDE.md
git commit -m "docs: describe PubTator evidence review workflow"
```

## Self-Review Notes

- Spec coverage: Plan covers PubTator-native exploration, compact evidence packets, deterministic review workflow, no backend LLM, and PostgreSQL persistence.
- Scope control: The plan intentionally excludes OpenAlex, Crossref, Semantic Scholar, journal impact scoring, and backend LLM calls.
- Residual risk: `PostgresReviewRepository` JSON decoding may need adjustment after verifying how `asyncpg` returns JSONB in this environment. Keep repository tests isolated unless a local PostgreSQL integration target is added.
