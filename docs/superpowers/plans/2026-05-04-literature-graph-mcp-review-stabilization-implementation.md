# Literature Graph MCP Review Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the literature graph MCP tools and review retrieval defaults after the 2026-05-04 MCP review findings.

**Architecture:** Add one shared paper mapping and availability helper, expand DOI-to-PMID resolution through provider fallbacks, then update compact response shaping and review retrieval budgeting. Keep existing service entry points and make response changes additive.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, pytest, uv, Ruff, mypy.

---

## Execution Notes

- Work in `/home/bernt-popp/development/pubtator-link` on branch `codex/llm-first-literature-graph-redesign`.
- Leave untracked `test.md` alone.
- Leave untracked `docs/superpowers/plans/2026-05-03-literature-map-epic-implementation.md` alone.
- Do not revert unrelated user changes.
- Use TDD for every task: write the focused failing tests, run them and confirm failure, implement, rerun focused tests, then commit with the exact message in that task.
- If using workers, tell each worker: other workers may be editing the repo; edit only the assigned files; do not revert or overwrite anyone else's changes.

## Parallelization

- Task 1 is foundational and must run first.
- After Task 1, Task 2 and Task 4 are independent enough to run in parallel because their write scopes do not overlap except tests.
- Task 3 depends on Tasks 1 and 2.
- Task 5 depends on Tasks 3 and 4.
- Task 6 is final verification and PR/Docker follow-through.

## File Map

- Create `pubtator_link/services/literature_paper_resolution.py`: shared `LiteraturePaper` construction, availability merging, and deduped signal helpers.
- Modify `pubtator_link/services/related_evidence.py`: use the shared metadata mapper, add normalized scores and candidate signals.
- Modify `pubtator_link/services/topic_literature_map.py`: use the shared mapper, preserve compact summary papers, add candidate signals, remove stale `prepare_mode` hints.
- Modify `pubtator_link/services/citation_graph.py`: use the shared mapper for source metadata, use the enhanced DOI resolver, add compact counts/status hints, remove stale `prepare_mode` hints.
- Modify `pubtator_link/services/literature_identifier_resolution.py`: add DOI fallback cascade status accounting.
- Modify `pubtator_link/services/ncbi_discovery.py`: add PubMed ESearch DOI lookup and remove stale `prepare_mode` hints.
- Modify `pubtator_link/models/literature_graph.py`: add compact response fields and candidate `signals`.
- Modify `pubtator_link/models/review_rerag.py`: add budget source and enriched recovery advice fields.
- Modify `pubtator_link/mcp/service_adapters.py`: detect omitted MCP budget args, auto-fit effective budgets, and set budget source.
- Modify `pubtator_link/mcp/tools/review.py`: make batch retrieval budget args optional at the MCP boundary.
- Modify `pubtator_link/mcp/resources.py`, `pubtator_link/mcp/catalog.py`, and `pubtator_link/services/workflow_help.py`: document graph workflow bundle and compact-mode semantics.
- Regenerate `docs/mcp-tool-catalog.md` with `uv run python scripts/generate_mcp_tool_catalog.py`.

---

### Task 1: Shared Literature Paper Resolver

**Files:**
- Create: `pubtator_link/services/literature_paper_resolution.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Test: `tests/unit/test_literature_paper_resolution.py`
- Test: `tests/unit/test_related_evidence_service.py`
- Test: `tests/unit/test_citation_graph_service.py`

- [ ] **Step 1: Write failing tests for availability semantics and source mapping**

Add `tests/unit/test_literature_paper_resolution.py`:

```python
from __future__ import annotations

from pubtator_link.models.literature_graph import LiteratureAvailability, LiteraturePaper
from pubtator_link.models.publication_metadata import PublicationAuthor, PublicationMetadata
from pubtator_link.services.literature_paper_resolution import (
    merge_literature_availability,
    paper_from_publication_metadata,
)


def test_pmcid_means_pmc_full_text_but_not_open_access_by_itself() -> None:
    metadata = PublicationMetadata(
        pmid="28386255",
        doi="10.3389/fimmu.2017.00253",
        pmcid="PMC5362626",
        title="Familial Mediterranean Fever",
        journal="Frontiers in Immunology",
        pub_year=2017,
        publication_types=["Review"],
        authors=[PublicationAuthor(last_name="Ozen", initials="S")],
        coverage="full_text",
    )

    paper = paper_from_publication_metadata(metadata, include_authors=True)

    assert paper.pmid == "28386255"
    assert paper.pmcid == "PMC5362626"
    assert paper.availability.has_pmc_full_text is True
    assert paper.availability.is_open_access is False
    assert paper.status == "resolved_full_text_candidate"
    assert paper.authors[0].name == "Ozen S"


def test_open_access_requires_explicit_availability_signal() -> None:
    metadata = PublicationMetadata(
        pmid="26802180",
        doi="10.1136/annrheumdis-2015-208690",
        title="EULAR recommendations for the management of familial Mediterranean fever",
        coverage="abstract_only",
    )
    explicit_oa = LiteratureAvailability(
        is_open_access=True,
        oa_status="bronze",
        full_text_url="https://example.org/eular",
    )

    paper = paper_from_publication_metadata(metadata, availability=explicit_oa)

    assert paper.availability.has_pmc_full_text is False
    assert paper.availability.is_open_access is True
    assert paper.availability.oa_status == "bronze"
    assert paper.status == "resolved_full_text_candidate"


def test_availability_merge_preserves_pmc_and_explicit_oa_independently() -> None:
    merged = merge_literature_availability(
        LiteraturePaper(
            pmid="1",
            pmcid="PMC1",
            availability=LiteratureAvailability(has_pmc_full_text=True),
        ),
        LiteraturePaper(
            pmid="1",
            availability=LiteratureAvailability(
                is_open_access=True,
                oa_status="green",
                license_or_access_hint="cc-by",
            ),
        ),
    )

    assert merged.availability.has_pmc_full_text is True
    assert merged.availability.is_open_access is True
    assert merged.availability.oa_status == "green"
    assert merged.availability.license_or_access_hint == "cc-by"
```

Update `tests/unit/test_related_evidence_service.py` by replacing the old PMCID-open-access expectation with:

```python
@pytest.mark.asyncio
async def test_metadata_full_text_pmc_candidate_does_not_imply_open_access_reason() -> None:
    service = RelatedEvidenceService(
        discovery_service=IntentDiscovery(),
        metadata_service=IntentMetadata(),
        citation_graph_service=IntentCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="1",
            max_results=5,
            include_citation_neighbors=False,
        )
    )

    reasons = set(response.candidates[0].match_reasons)
    assert "full_text_available" in reasons
    assert "open_access_available" not in reasons
    assert response.candidates[0].paper.availability.has_pmc_full_text is True
    assert response.candidates[0].paper.availability.is_open_access is False
```

Add this test to `tests/unit/test_citation_graph_service.py`:

```python
class MetadataWithPmcid:
    async def get_metadata(self, request):
        from pubtator_link.models.publication_metadata import PublicationMetadata

        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid="28386255",
                    doi="10.3389/fimmu.2017.00253",
                    pmcid="PMC5362626",
                    title="Familial Mediterranean Fever",
                    journal="Frontiers in Immunology",
                    pub_year=2017,
                    coverage="full_text",
                )
            ],
            failed_pmids={},
        )


@pytest.mark.asyncio
async def test_citation_graph_source_uses_shared_metadata_availability() -> None:
    service = CitationGraphService(
        discovery_service=FakeDiscovery(),
        metadata_service=MetadataWithPmcid(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            pmid="28386255",
            direction="cited_by",
            response_mode="compact",
        )
    )

    assert response.source.pmcid == "PMC5362626"
    assert response.source.availability.has_pmc_full_text is True
    assert response.source.availability.is_open_access is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_paper_resolution.py \
  tests/unit/test_related_evidence_service.py::test_metadata_full_text_pmc_candidate_does_not_imply_open_access_reason \
  tests/unit/test_citation_graph_service.py::test_citation_graph_source_uses_shared_metadata_availability \
  -q
```

Expected: FAIL because `literature_paper_resolution` does not exist, related evidence still treats PMCID as open access, and citation graph source metadata has no availability mapping.

- [ ] **Step 3: Implement the shared mapper and switch service call sites**

Create `pubtator_link/services/literature_paper_resolution.py`:

```python
"""Shared LiteraturePaper mapping and availability merge helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureAvailability,
    LiteratureGraphProvenance,
    LiteraturePaper,
    LiteraturePaperStatus,
)


def paper_from_publication_metadata(
    metadata: Any,
    *,
    include_authors: bool = False,
    availability: LiteratureAvailability | None = None,
) -> LiteraturePaper:
    has_pmc_full_text = getattr(metadata, "coverage", None) == "full_text" or bool(
        getattr(metadata, "pmcid", None)
    )
    merged_availability = LiteratureAvailability(
        has_pmc_full_text=has_pmc_full_text,
        is_open_access=False,
    )
    if availability is not None:
        merged_availability = _merge_availability_values(merged_availability, availability)
    status: LiteraturePaperStatus = (
        "resolved_full_text_candidate"
        if _has_full_text_signal(merged_availability)
        else "resolved_metadata_only"
    )
    return LiteraturePaper(
        pmid=getattr(metadata, "pmid", None),
        doi=getattr(metadata, "doi", None),
        pmcid=getattr(metadata, "pmcid", None),
        title=getattr(metadata, "title", None),
        journal=getattr(metadata, "journal", None),
        year=getattr(metadata, "pub_year", None),
        publication_types=list(getattr(metadata, "publication_types", []) or []),
        authors=_authors_from_metadata(metadata) if include_authors else [],
        availability=merged_availability,
        status=status,
        provenance=[LiteratureGraphProvenance(provider="pubmed_metadata")],
    )


def merge_literature_availability(
    primary: LiteraturePaper,
    fallback: LiteraturePaper,
) -> LiteraturePaper:
    availability = _merge_availability_values(primary.availability, fallback.availability)
    return primary.model_copy(
        update={
            "doi": primary.doi or fallback.doi,
            "pmcid": primary.pmcid or fallback.pmcid,
            "openalex_id": primary.openalex_id or fallback.openalex_id,
            "title": primary.title or fallback.title,
            "journal": primary.journal or fallback.journal,
            "year": primary.year or fallback.year,
            "publication_types": primary.publication_types or fallback.publication_types,
            "authors": primary.authors or fallback.authors,
            "availability": availability,
            "status": best_literature_status(primary, fallback, availability),
            "provenance": [*primary.provenance, *fallback.provenance],
        }
    )


def best_literature_status(
    primary: LiteraturePaper,
    fallback: LiteraturePaper,
    availability: LiteratureAvailability | None = None,
) -> LiteraturePaperStatus:
    merged = availability or _merge_availability_values(primary.availability, fallback.availability)
    if _has_full_text_signal(merged):
        return "resolved_full_text_candidate"
    if primary.status == "resolved_metadata_only" or fallback.status == "resolved_metadata_only":
        return "resolved_metadata_only"
    if primary.status == "publisher_entitlement_required":
        return primary.status
    return fallback.status


def deduped_signals(*groups: Iterable[str]) -> list[str]:
    signals: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for signal in group:
            if signal and signal not in seen:
                seen.add(signal)
                signals.append(signal)
    return signals


def _merge_availability_values(
    primary: LiteratureAvailability,
    fallback: LiteratureAvailability,
) -> LiteratureAvailability:
    return primary.model_copy(
        update={
            "has_pmc_full_text": primary.has_pmc_full_text or fallback.has_pmc_full_text,
            "is_open_access": primary.is_open_access or fallback.is_open_access,
            "has_pdf": primary.has_pdf or fallback.has_pdf,
            "full_text_url": primary.full_text_url or fallback.full_text_url,
            "oa_status": primary.oa_status or fallback.oa_status,
            "license_or_access_hint": primary.license_or_access_hint
            or fallback.license_or_access_hint,
        }
    )


def _has_full_text_signal(availability: LiteratureAvailability) -> bool:
    return (
        availability.has_pmc_full_text
        or availability.is_open_access
        or bool(availability.full_text_url)
    )


def _authors_from_metadata(metadata: Any) -> list[LiteratureAuthor]:
    return [
        LiteratureAuthor(name=author.display_name)
        for author in getattr(metadata, "authors", []) or []
        if getattr(author, "display_name", "")
    ]
```

Update service call sites:

```python
# related_evidence.py
from pubtator_link.services.literature_paper_resolution import paper_from_publication_metadata


def _paper_from_metadata(metadata: Any) -> LiteraturePaper:
    return paper_from_publication_metadata(metadata)
```

```python
# topic_literature_map.py
from pubtator_link.services.literature_paper_resolution import (
    best_literature_status,
    merge_literature_availability,
    paper_from_publication_metadata,
)


def _paper_from_metadata(metadata: Any) -> LiteraturePaper:
    return paper_from_publication_metadata(metadata, include_authors=True)
```

In `topic_literature_map.py`, rewrite `_merge_missing_paper_fields()` to delegate the availability/status pieces to `merge_literature_availability()` while preserving the existing richer-primary behavior.

In `citation_graph.py`, import `paper_from_publication_metadata` and replace the manual `LiteraturePaper(...)` construction in `_source_paper()` with:

```python
return paper_from_publication_metadata(metadata)
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_paper_resolution.py \
  tests/unit/test_related_evidence_service.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/test_citation_graph_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  pubtator_link/services/literature_paper_resolution.py \
  pubtator_link/services/related_evidence.py \
  pubtator_link/services/topic_literature_map.py \
  pubtator_link/services/citation_graph.py \
  tests/unit/test_literature_paper_resolution.py \
  tests/unit/test_related_evidence_service.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/test_citation_graph_service.py
git commit -m "feat: add shared literature paper resolver"
```

---

### Task 2: DOI-to-PMID Fallback Cascade

**Files:**
- Modify: `pubtator_link/services/literature_identifier_resolution.py`
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Test: `tests/unit/test_literature_identifier_resolution.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`
- Test: `tests/unit/test_citation_graph_service.py`

- [ ] **Step 1: Write failing tests for OpenAlex and PubMed ESearch fallbacks**

Add to `tests/unit/test_literature_identifier_resolution.py`:

```python
class UnresolvedIdConverter:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def convert_article_ids(self, ids: list[str], source: str = "auto"):
        self.calls.append(ids)
        return type("ArticleIdConversionResponse", (), {"records": []})()


class OpenAlexDoiResolver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_work_by_doi(self, doi: str):
        self.calls.append(doi)
        from pubtator_link.models.literature_graph import LiteraturePaper

        return LiteraturePaper(
            pmid="26802180",
            doi=doi,
            title="EULAR recommendations for the management of familial Mediterranean fever",
        )


class PubMedDoiResolver:
    def __init__(self, pmid: str | None) -> None:
        self.pmid = pmid
        self.calls: list[str] = []

    async def find_pmid_by_doi(self, doi: str) -> str | None:
        self.calls.append(doi)
        return self.pmid


@pytest.mark.asyncio
async def test_resolver_falls_back_to_openalex_after_id_converter_no_match() -> None:
    discovery = UnresolvedIdConverter()
    openalex = OpenAlexDoiResolver()
    pubmed = PubMedDoiResolver("999")
    resolver = DoiPmidResolver(
        discovery_service=discovery,
        openalex_service=openalex,
        pubmed_service=pubmed,
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.resolved == {"10.1136/annrheumdis-2015-208690": "26802180"}
    assert result.resolution_sources["10.1136/annrheumdis-2015-208690"] == "openalex"
    assert result.unresolved == set()
    assert openalex.calls == ["10.1136/annrheumdis-2015-208690"]
    assert pubmed.calls == []


@pytest.mark.asyncio
async def test_resolver_falls_back_to_pubmed_esearch_after_openalex_no_match() -> None:
    class EmptyOpenAlex:
        async def get_work_by_doi(self, doi: str):
            from pubtator_link.models.literature_graph import LiteraturePaper

            return LiteraturePaper(doi=doi)

    resolver = DoiPmidResolver(
        discovery_service=UnresolvedIdConverter(),
        openalex_service=EmptyOpenAlex(),
        pubmed_service=PubMedDoiResolver("26802180"),
    )

    result = await resolver.resolve(["10.1136/annrheumdis-2015-208690"], max_ids=20)

    assert result.resolved == {"10.1136/annrheumdis-2015-208690": "26802180"}
    assert result.resolution_sources["10.1136/annrheumdis-2015-208690"] == "pubmed_esearch"
```

Add to `tests/unit/test_ncbi_discovery_service.py`:

```python
@pytest.mark.asyncio
async def test_ncbi_client_finds_pmid_by_doi_with_article_identifier_search() -> None:
    transport = MockTransport(
        {
            "esearchresult": {
                "idlist": ["26802180"],
            }
        }
    )
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    client = NcbiDiscoveryClient(http_client=http_client)

    pmid = await client.find_pmid_by_doi("10.1136/annrheumdis-2015-208690")

    assert pmid == "26802180"
    assert transport.requests[0].url.path.endswith("/esearch.fcgi")
    assert transport.requests[0].url.params["db"] == "pubmed"
    assert transport.requests[0].url.params["term"] == "10.1136/annrheumdis-2015-208690[AID]"
    await client.close()
```

Add to `tests/unit/test_citation_graph_service.py`:

```python
class EularOpenAlex:
    async def get_work_by_doi(self, doi: str) -> LiteraturePaper:
        return LiteraturePaper(
            pmid="26802180",
            doi=doi,
            title="EULAR recommendations for the management of familial Mediterranean fever",
            availability=LiteratureAvailability(is_open_access=True, oa_status="bronze"),
        )

    async def get_references(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        return []

    async def get_cited_by(self, doi: str, *, limit: int) -> list[LiteraturePaper]:
        return []


class EularMetadata:
    async def get_metadata(self, request):
        from pubtator_link.models.publication_metadata import PublicationMetadata

        return PublicationMetadataResponse(
            metadata=[
                PublicationMetadata(
                    pmid="26802180",
                    doi="10.1136/annrheumdis-2015-208690",
                    title="EULAR recommendations for the management of familial Mediterranean fever",
                    coverage="abstract_only",
                )
            ],
            failed_pmids={},
        )


@pytest.mark.asyncio
async def test_citation_graph_resolves_eular_doi_with_openalex_fallback() -> None:
    service = CitationGraphService(
        openalex=EularOpenAlex(),
        discovery_service=FakeDiscovery(),
        metadata_service=EularMetadata(),
    )

    response = await service.get_citation_graph(
        PublicationCitationGraphRequest(
            doi="10.1136/annrheumdis-2015-208690",
            direction="cited_by",
            response_mode="compact",
        )
    )

    assert response.source.pmid == "26802180"
    assert response.source.doi == "10.1136/annrheumdis-2015-208690"
    assert any(
        status.provider == "openalex"
        and status.operation == "doi_to_pmid"
        and status.status == "success"
        for status in response.identifier_resolution_status
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_identifier_resolution.py \
  tests/unit/test_ncbi_discovery_service.py::test_ncbi_client_finds_pmid_by_doi_with_article_identifier_search \
  tests/unit/test_citation_graph_service.py::test_citation_graph_resolves_eular_doi_with_openalex_fallback \
  -q
```

Expected: FAIL because the DOI resolver only uses the PMC ID Converter and does not expose per-provider resolution sources.

- [ ] **Step 3: Implement DOI fallback cascade**

Update `DoiResolutionResult` in `literature_identifier_resolution.py`:

```python
resolution_sources: dict[str, str] = field(default_factory=dict)
provider_result_counts: dict[str, int] = field(default_factory=dict)
provider_no_match_counts: dict[str, int] = field(default_factory=dict)
```

Update `DoiPmidResolver.__init__()`:

```python
def __init__(
    self,
    *,
    discovery_service: Any | None,
    openalex_service: Any | None = None,
    pubmed_service: Any | None = None,
) -> None:
    self.discovery_service = discovery_service
    self.openalex_service = openalex_service
    self.pubmed_service = pubmed_service
    self._pmid_cache: dict[str, tuple[str, str]] = {}
    self._unresolved_cache: set[str] = set()
```

Within `resolve()`, preserve the existing ID Converter attempt first. For every DOI still missing after ID Converter:

```python
if self.openalex_service is not None:
    paper = await self.openalex_service.get_work_by_doi(doi)
    if getattr(paper, "pmid", None):
        resolved[doi] = str(paper.pmid)
        resolution_sources[doi] = "openalex"
        self._pmid_cache[doi] = (str(paper.pmid), "openalex")
        continue

if self.pubmed_service is not None:
    finder = getattr(self.pubmed_service, "find_pmid_by_doi", None)
    if finder is not None:
        pmid = await finder(doi)
        if pmid:
            resolved[doi] = str(pmid)
            resolution_sources[doi] = "pubmed_esearch"
            self._pmid_cache[doi] = (str(pmid), "pubmed_esearch")
            continue
```

Add `NcbiDiscoveryClient.find_pmid_by_doi()`:

```python
async def find_pmid_by_doi(self, doi: str) -> str | None:
    response = await self._get(
        "esearch.fcgi",
        {
            "db": "pubmed",
            "term": f"{doi}[AID]",
            "retmode": "json",
            "retmax": "1",
            "tool": "pubtator-link",
        },
    )
    payload = response.json()
    esearch_result = payload.get("esearchresult") if isinstance(payload, dict) else None
    idlist = esearch_result.get("idlist", []) if isinstance(esearch_result, dict) else []
    return str(idlist[0]) if idlist else None
```

Expose it on `DiscoveryService`:

```python
async def find_pmid_by_doi(self, doi: str) -> str | None:
    finder = getattr(self.client, "find_pmid_by_doi", None)
    if finder is None:
        return None
    return await finder(doi)
```

Update `CitationGraphService.__init__()`:

```python
self.doi_resolver = DoiPmidResolver(
    discovery_service=discovery_service,
    openalex_service=openalex,
    pubmed_service=discovery_service,
)
```

Update `_pmid_for_doi()` to call `self.doi_resolver.resolve([doi], max_ids=1)` and return the resolved PMID. Add a helper that converts `DoiResolutionResult.provider_result_counts` and `resolution_sources` into `LiteratureProviderStatus` rows with provider names `ncbi_idconv`, `openalex`, and `pubmed_esearch`.

- [ ] **Step 4: Run focused tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_identifier_resolution.py \
  tests/unit/test_ncbi_discovery_service.py \
  tests/unit/test_citation_graph_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  pubtator_link/services/literature_identifier_resolution.py \
  pubtator_link/services/ncbi_discovery.py \
  pubtator_link/services/citation_graph.py \
  tests/unit/test_literature_identifier_resolution.py \
  tests/unit/test_ncbi_discovery_service.py \
  tests/unit/test_citation_graph_service.py
git commit -m "feat: add DOI PMID fallback resolution"
```

---

### Task 3: Compact Graph Contract Cleanup

**Files:**
- Modify: `pubtator_link/models/literature_graph.py`
- Modify: `pubtator_link/services/literature_graph_compact.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/services/citation_graph.py`
- Modify: `pubtator_link/services/related_evidence.py`
- Test: `tests/unit/test_literature_graph_models.py`
- Test: `tests/unit/test_literature_graph_compact.py`
- Test: `tests/unit/test_topic_literature_map_service.py`
- Test: `tests/unit/test_citation_graph_service.py`
- Test: `tests/unit/test_related_evidence_service.py`

- [ ] **Step 1: Write failing tests for compact summaries, machine-readable status, and signals**

Update `tests/unit/test_topic_literature_map_service.py` compact assertions:

```python
@pytest.mark.asyncio
async def test_topic_map_compact_keeps_summary_papers_and_candidate_signals() -> None:
    response = await _service().build_map(
        TopicLiteratureMapRequest(
            query="FMF colchicine guideline child",
            max_seed_papers=2,
            max_neighbors_per_paper=2,
            response_mode="compact",
            max_candidates=3,
            max_demoted=1,
        )
    )

    assert response.meta.response_mode == "compact"
    assert response.nodes == []
    assert response.edges == []
    assert response.summary.central_papers
    assert response.summary.recent_connected_papers
    assert response.summary.bridge_papers
    assert len(response.summary.central_papers) <= 5
    assert len(response.summary.recent_connected_papers) <= 5
    assert len(response.summary.bridge_papers) <= 5
    assert response.top_candidates
    assert response.top_candidates[0].signals
    assert len(response.top_candidates[0].signals) == len(set(response.top_candidates[0].signals))
```

Update `tests/unit/test_citation_graph_service.py` compact test:

```python
assert response.actionable_pmid_count == len(response.candidate_pmids)
assert response.metadata_only_count >= 0
assert response.unresolved_doi_count >= 0
assert response.compact_status["references"] == "candidates_only"
assert response.compact_status["cited_by"] == "candidates_only"
assert response.references == []
assert response.cited_by == []
```

Add to `tests/unit/test_related_evidence_service.py`:

```python
class ScoreRangeDiscovery:
    async def find_related_article_scores(self, pmids: list[str], limit: int):
        return [
            RelatedArticleScoreRecord(source_pmid="123", pmid="111", neighbor_score=10),
            RelatedArticleScoreRecord(source_pmid="123", pmid="222", neighbor_score=30),
        ]


@pytest.mark.asyncio
async def test_related_evidence_adds_normalized_neighbor_score_and_signals() -> None:
    service = RelatedEvidenceService(
        discovery_service=ScoreRangeDiscovery(),
        metadata_service=FakeMetadata(),
        citation_graph_service=FakeCitationGraph(),
    )

    response = await service.find_candidates(
        RelatedEvidenceCandidatesRequest(
            pmid="123",
            include_citation_neighbors=False,
            max_results=2,
        )
    )

    by_pmid = {candidate.paper.pmid: candidate for candidate in response.candidates}
    assert by_pmid["222"].normalized_neighbor_score == 1.0
    assert by_pmid["111"].normalized_neighbor_score == 0.0
    assert by_pmid["222"].signals == by_pmid["222"].match_reasons
```

Add model serialization assertions to `tests/unit/test_literature_graph_models.py`:

```python
def test_literature_candidate_summary_serializes_signals() -> None:
    candidate = LiteratureCandidateSummary(
        pmid="123",
        access="metadata_only",
        signals=["pubmed_neighbor_score", "full_text_available"],
    )

    assert candidate.model_dump()["signals"] == [
        "pubmed_neighbor_score",
        "full_text_available",
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_graph_models.py::test_literature_candidate_summary_serializes_signals \
  tests/unit/test_topic_literature_map_service.py::test_topic_map_compact_keeps_summary_papers_and_candidate_signals \
  tests/unit/test_citation_graph_service.py::test_citation_graph_compact_returns_candidates_status_and_no_metadata_duplicates \
  tests/unit/test_related_evidence_service.py::test_related_evidence_adds_normalized_neighbor_score_and_signals \
  -q
```

Expected: FAIL because the new fields and compact summary behavior are not implemented.

- [ ] **Step 3: Implement compact graph response additions**

Update `LiteratureCandidateSummary`:

```python
signals: list[str] = Field(default_factory=list)
```

Update `RelatedEvidenceCandidate`:

```python
normalized_neighbor_score: float | None = Field(default=None, ge=0.0, le=1.0)
signals: list[str] = Field(default_factory=list)
```

Update `PublicationCitationGraphResponse`:

```python
actionable_pmid_count: int = 0
metadata_only_count: int = 0
unresolved_doi_count: int = 0
compact_status: dict[str, str] = Field(default_factory=dict)
```

Update `candidate_summary()` in `literature_graph_compact.py`:

```python
from pubtator_link.services.literature_paper_resolution import deduped_signals

signals = deduped_signals(
    relevance_to_query.reasons if relevance_to_query is not None else [],
    rank_reasons or [],
    demotion_reasons or [],
)
```

Pass `signals=signals` into `LiteratureCandidateSummary`.

Update `_summary_without_papers()` in `topic_literature_map.py` to preserve bounded summary lists:

```python
def _summary_without_papers(
    summary: TopicLiteratureMapSummary,
    recommended_next_pmids: list[str],
) -> TopicLiteratureMapSummary:
    return TopicLiteratureMapSummary(
        central_papers=summary.central_papers[:5],
        recent_connected_papers=summary.recent_connected_papers[:5],
        bridge_papers=summary.bridge_papers[:5],
        dominant_author_groups=summary.dominant_author_groups,
        accessible_full_text_candidates=[],
        closed_central_sources=summary.closed_central_sources[:5],
        recommended_next_pmids=recommended_next_pmids,
    )
```

Update `CitationGraphService.get_citation_graph()` response construction:

```python
all_neighbors = [*references, *cited_by]
actionable_pmid_count = len(_candidate_pmids(all_neighbors))
metadata_only_count = len(_metadata_only(all_neighbors))
unresolved_doi_count = sum(1 for paper in all_neighbors if paper.doi and not paper.pmid)
compact_status = (
    {"references": "candidates_only", "cited_by": "candidates_only"}
    if request.response_mode == "compact"
    else {}
)
```

Pass those fields into `PublicationCitationGraphResponse`.

Update `RelatedEvidenceService.find_candidates()` after final sorting and slicing:

```python
_attach_normalized_scores(candidates)
```

Add:

```python
def _attach_normalized_scores(candidates: list[RelatedEvidenceCandidate]) -> None:
    raw_scores = [
        candidate.pubmed_neighbor_score
        for candidate in candidates
        if candidate.pubmed_neighbor_score is not None
    ]
    if not raw_scores:
        for candidate in candidates:
            candidate.signals = deduped_signals(candidate.match_reasons)
        return
    low = min(raw_scores)
    high = max(raw_scores)
    span = high - low
    for candidate in candidates:
        raw = candidate.pubmed_neighbor_score
        normalized = 1.0 if span == 0 and raw is not None else (
            (raw - low) / span if raw is not None else None
        )
        candidate.normalized_neighbor_score = normalized
        candidate.signals = deduped_signals(candidate.match_reasons)
```

- [ ] **Step 4: Run focused graph tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_graph_models.py \
  tests/unit/test_literature_graph_compact.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/test_citation_graph_service.py \
  tests/unit/test_related_evidence_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  pubtator_link/models/literature_graph.py \
  pubtator_link/services/literature_graph_compact.py \
  pubtator_link/services/topic_literature_map.py \
  pubtator_link/services/citation_graph.py \
  pubtator_link/services/related_evidence.py \
  tests/unit/test_literature_graph_models.py \
  tests/unit/test_literature_graph_compact.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/test_citation_graph_service.py \
  tests/unit/test_related_evidence_service.py
git commit -m "feat: tighten graph compact responses"
```

---

### Task 4: Review Retrieval Budget Auto-Fit

**Files:**
- Modify: `pubtator_link/models/review_rerag.py`
- Modify: `pubtator_link/mcp/service_adapters.py`
- Modify: `pubtator_link/mcp/tools/review.py`
- Modify: `pubtator_link/services/review_context/batch_budgeting.py`
- Modify: `pubtator_link/services/review_context_service.py`
- Test: `tests/unit/test_review_rerag_models.py`
- Test: `tests/unit/test_review_context_batch_budgeting.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/mcp/test_review_rerag_mcp.py`

- [ ] **Step 1: Write failing tests for omitted-budget auto-fit and recovery advice**

Add to `tests/unit/mcp/test_mcp_service_adapters.py`:

```python
async def test_retrieve_review_context_batch_adapter_auto_fits_omitted_budgets() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl

    class RecordingService:
        def __init__(self) -> None:
            self.request = None

        async def retrieve_context_batch(self, review_id, request):
            from pubtator_link.models.review_rerag import (
                ContextPack,
                PreparationStatus,
                RetrieveReviewContextBatchResponse,
            )

            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=request.budget_source,
            )

    service = RecordingService()

    result = await retrieve_review_context_batch_impl(
        service=service,
        review_id="review-1",
        queries=["guideline", "phenotype"],
        max_total_passages=14,
        max_chars_per_passage=2200,
    )

    assert service.request.max_chars == 30800
    assert service.request.max_response_chars == 61600
    assert service.request.budget_source == "auto_fit"
    assert result["budget_source"] == "auto_fit"


async def test_retrieve_review_context_batch_adapter_preserves_explicit_budgets() -> None:
    from pubtator_link.mcp.service_adapters import retrieve_review_context_batch_impl

    class RecordingService:
        async def retrieve_context_batch(self, review_id, request):
            from pubtator_link.models.review_rerag import (
                ContextPack,
                PreparationStatus,
                RetrieveReviewContextBatchResponse,
            )

            self.request = request
            return RetrieveReviewContextBatchResponse(
                review_id=review_id,
                merged_context_pack=ContextPack(question="q", passages=[], citation_map={}),
                preparation_status=PreparationStatus(),
                budget_source=request.budget_source,
            )

    service = RecordingService()

    await retrieve_review_context_batch_impl(
        service=service,
        review_id="review-1",
        queries=["guideline"],
        max_chars=8000,
        max_response_chars=12000,
    )

    assert service.request.max_chars == 8000
    assert service.request.max_response_chars == 12000
    assert service.request.budget_source == "caller"
```

Add to `tests/unit/test_review_context_batch_budgeting.py`:

```python
def test_budget_advice_reports_tokens_and_dropped_priority_pmids() -> None:
    dropped = [
        ContextDropReason(
            reason="char_budget_exceeded",
            passage_id="p1",
            pmid="40067091",
            section="results",
            char_count=1800,
        ),
        ContextDropReason(
            reason="response_char_budget_exceeded",
            passage_id="p2",
            pmid="39581919",
            section="discussion",
            char_count=1500,
        ),
    ]
    request = RetrieveReviewContextBatchRequest(
        queries=["phenotype"],
        max_chars=1000,
        max_response_chars=2000,
        prioritize_pmids=["39581919"],
    )

    summary = build_dropped_summary(
        dropped=dropped,
        visible_dropped=dropped,
        request=request,
    )

    assert summary.budget_advice is not None
    assert summary.budget_advice.estimated_tokens_to_unlock is not None
    assert summary.budget_advice.dropped_pmid_count == 2
    assert summary.budget_advice.dropped_priority_pmids == ["39581919"]
    assert summary.budget_advice.retry_arguments["prioritize_pmids"] == ["39581919"]
```

Add to `tests/unit/mcp/test_review_rerag_mcp.py`:

```python
def test_retrieve_review_context_batch_schema_uses_auto_fit_budget_defaults() -> None:
    mcp = make_mcp(profile="lean")
    schema = mcp._tool_manager._tools["pubtator.retrieve_review_context_batch"].parameters
    properties = schema["properties"]

    assert properties["max_chars"].get("default") is None
    assert properties["max_response_chars"].get("default") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/mcp/test_mcp_service_adapters.py::test_retrieve_review_context_batch_adapter_auto_fits_omitted_budgets \
  tests/unit/mcp/test_mcp_service_adapters.py::test_retrieve_review_context_batch_adapter_preserves_explicit_budgets \
  tests/unit/test_review_context_batch_budgeting.py::test_budget_advice_reports_tokens_and_dropped_priority_pmids \
  tests/unit/mcp/test_review_rerag_mcp.py::test_retrieve_review_context_batch_schema_uses_auto_fit_budget_defaults \
  -q
```

Expected: FAIL because budget args are always defaulted before the adapter can detect omission, budget source is absent, and recovery advice lacks the new fields.

- [ ] **Step 3: Implement auto-fit budgets and enriched advice**

Update `review_rerag.py`:

```python
BudgetSource = Literal["caller", "auto_fit", "default"]
```

Add fields:

```python
class ContextBudget(BaseModel):
    ...
    budget_source: BudgetSource = "default"


class RecoveryBudgetAdvice(BaseModel):
    ...
    estimated_tokens_to_unlock: int | None = Field(default=None, ge=1)
    dropped_pmid_count: int = Field(default=0, ge=0)
    dropped_priority_pmids: list[str] = Field(default_factory=list)
    retry_arguments: dict[str, Any] = Field(default_factory=dict)


class RetrieveReviewContextBatchRequest(BaseModel):
    ...
    budget_source: BudgetSource = "default"


class RetrieveReviewContextBatchResponse(BaseModel):
    ...
    budget_source: BudgetSource = "default"
```

Update `mcp/tools/review.py` signature:

```python
max_chars: int | None = None
max_response_chars: int | None = None
```

Update `retrieve_review_context_batch_impl()` signature the same way and add:

```python
MCP_BATCH_DEFAULT_MAX_CHARS = 24000
MCP_BATCH_DEFAULT_MAX_RESPONSE_CHARS = 48000
MCP_BATCH_MAX_CHARS = 50000
MCP_BATCH_MAX_RESPONSE_CHARS = 100000


def _auto_fit_batch_budgets(
    *,
    max_total_passages: int,
    max_chars_per_passage: int,
    max_chars: int | None,
    max_response_chars: int | None,
) -> tuple[int, int, str]:
    if max_chars is not None or max_response_chars is not None:
        return (
            max_chars if max_chars is not None else MCP_BATCH_DEFAULT_MAX_CHARS,
            max_response_chars
            if max_response_chars is not None
            else MCP_BATCH_DEFAULT_MAX_RESPONSE_CHARS,
            "caller",
        )
    desired_chars = max_total_passages * max_chars_per_passage
    effective_chars = min(
        MCP_BATCH_MAX_CHARS,
        max(MCP_BATCH_DEFAULT_MAX_CHARS, desired_chars),
    )
    effective_response_chars = min(
        MCP_BATCH_MAX_RESPONSE_CHARS,
        max(MCP_BATCH_DEFAULT_MAX_RESPONSE_CHARS, effective_chars * 2),
    )
    source = "auto_fit" if effective_chars != MCP_BATCH_DEFAULT_MAX_CHARS else "default"
    return effective_chars, effective_response_chars, source
```

Call it after normalization has derived `max_total_passages` and before constructing `RetrieveReviewContextBatchRequest`.

Update `review_context_service.py` budget creation:

```python
budget = context_budget(
    max_chars=request.max_chars,
    text_chars=merged.budget_text_chars,
    dropped_count=len(merged.dropped),
).model_copy(update={"budget_source": request.budget_source})
```

Do the same for dry-run budget and pass `budget_source=request.budget_source` into `RetrieveReviewContextBatchResponse`.

Update `build_dropped_summary()` in `batch_budgeting.py`:

```python
priority_drops = [
    pmid for pmid in request.prioritize_pmids if pmid in pmid_counts
]
retry_arguments = {
    "max_chars": increase_max_chars_to,
    "max_response_chars": increase_max_response_chars_to,
}
if priority_drops:
    retry_arguments["prioritize_pmids"] = priority_drops[:5]
```

Set `estimated_tokens_to_unlock=estimate_tokens_from_chars(sum(item.char_count or 0 for item in dropped))`, `dropped_pmid_count=len(pmid_counts)`, `dropped_priority_pmids=priority_drops[:5]`, and `retry_arguments=retry_arguments`.

- [ ] **Step 4: Run focused retrieval/MCP tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/unit/test_review_rerag_models.py \
  tests/unit/test_review_context_batch_budgeting.py \
  tests/unit/test_review_context_service.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_review_rerag_mcp.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  pubtator_link/models/review_rerag.py \
  pubtator_link/mcp/service_adapters.py \
  pubtator_link/mcp/tools/review.py \
  pubtator_link/services/review_context/batch_budgeting.py \
  pubtator_link/services/review_context_service.py \
  tests/unit/test_review_rerag_models.py \
  tests/unit/test_review_context_batch_budgeting.py \
  tests/unit/test_review_context_service.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_review_rerag_mcp.py
git commit -m "feat: auto-fit review retrieval budgets"
```

---

### Task 5: MCP UX, Workflow Guidance, and Catalog

**Files:**
- Modify: `pubtator_link/services/citation_graph.py`
- Modify: `pubtator_link/services/topic_literature_map.py`
- Modify: `pubtator_link/services/ncbi_discovery.py`
- Modify: `pubtator_link/mcp/resources.py`
- Modify: `pubtator_link/mcp/catalog.py`
- Modify: `pubtator_link/services/workflow_help.py`
- Modify: `docs/mcp-tool-catalog.md`
- Test: `tests/unit/test_workflow_help.py`
- Test: `tests/unit/mcp/test_mcp_facade.py`
- Test: `tests/unit/mcp/test_mcp_tool_catalog.py`
- Test: `tests/unit/mcp/test_mcp_service_adapters.py`
- Test: `tests/unit/test_ncbi_discovery_service.py`

- [ ] **Step 1: Write failing tests for no generated `prepare_mode` and graph workflow bundle**

Add to `tests/unit/test_workflow_help.py`:

```python
def test_workflow_help_mentions_literature_graph_bundle_boundary() -> None:
    payload = WorkflowHelpService().workflow_help(task="graph").model_dump()
    text = str(payload)

    assert "build_topic_literature_map" in text
    assert "get_publication_citation_graph" in text
    assert "find_related_evidence_candidates" in text
    assert "ToolSearch" in text
```

Add to `tests/unit/mcp/test_mcp_facade.py`:

```python
def test_capabilities_expose_literature_graph_workflow_bundle() -> None:
    payload = get_capabilities_resource(profile="full")

    bundle = payload["workflow_bundles"]["literature_graph"]
    assert bundle["tools"] == [
        "pubtator.search_literature",
        "pubtator.build_topic_literature_map",
        "pubtator.get_publication_citation_graph",
        "pubtator.find_related_evidence_candidates",
        "pubtator.index_review_evidence",
        "pubtator.retrieve_review_context_batch",
    ]
    assert "host" in bundle["boundary_note"].casefold()
```

Add to `tests/unit/test_citation_graph_service.py`, `tests/unit/test_topic_literature_map_service.py`, and `tests/unit/test_ncbi_discovery_service.py`:

```python
def assert_no_prepare_mode(payload: object) -> None:
    assert "prepare_mode" not in str(payload)
```

Call that helper against citation graph `_meta.next_commands`, topic map `candidate_retrieval_hints`, and discovery `_meta.next_commands`.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/unit/test_workflow_help.py::test_workflow_help_mentions_literature_graph_bundle_boundary \
  tests/unit/mcp/test_mcp_facade.py::test_capabilities_expose_literature_graph_workflow_bundle \
  tests/unit/test_citation_graph_service.py::test_citation_graph_compact_returns_candidates_status_and_no_metadata_duplicates \
  tests/unit/test_topic_literature_map_service.py::test_topic_map_compact_keeps_summary_papers_and_candidate_signals \
  tests/unit/test_ncbi_discovery_service.py::test_convert_article_ids_adds_candidates_and_next_commands \
  -q
```

Expected: FAIL because the graph workflow bundle is absent and generated graph/discovery next commands still include `prepare_mode`.

- [ ] **Step 3: Implement MCP guidance cleanup**

Remove `prepare_mode` from these generated command dictionaries:

```python
# citation_graph.py
{"tool": "pubtator.index_review_evidence", "arguments": {"pmids": candidate_pmids}}

# topic_literature_map.py
{"tool": "pubtator.index_review_evidence", "arguments": {"pmids": pmids}}

# ncbi_discovery.py
{"tool": "pubtator.index_review_evidence", "arguments": {"pmids": candidate_pmids}}
```

Add a literature graph workflow bundle to `pubtator_link/mcp/resources.py`:

```python
"workflow_bundles": {
    "literature_graph": {
        "tools": [
            "pubtator.search_literature",
            "pubtator.build_topic_literature_map",
            "pubtator.get_publication_citation_graph",
            "pubtator.find_related_evidence_candidates",
            "pubtator.index_review_evidence",
            "pubtator.retrieve_review_context_batch",
        ],
        "compact_mode_contract": (
            "Graph compact mode returns candidate lanes, bounded summary papers, "
            "machine-readable compact_status, omitted_counts, and response_size_class."
        ),
        "boundary_note": (
            "The server advertises this bundle, but host ToolSearch gating controls "
            "which tool schemas are loaded on first use."
        ),
    }
}
```

Update `pubtator_link/mcp/catalog.py` descriptions for the three graph tools:

```python
"compact mode returns candidate lanes and bounded summaries; full mode can be large"
```

Update `WorkflowHelpService` to include a graph-oriented step sequence when `task` contains `graph`, `citation`, `topic map`, or `literature map`.

Regenerate catalog:

```bash
uv run python scripts/generate_mcp_tool_catalog.py
```

- [ ] **Step 4: Run focused MCP/docs tests to verify they pass**

Run:

```bash
uv run pytest \
  tests/unit/test_workflow_help.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_tool_catalog.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_review_rerag_mcp.py \
  tests/unit/test_ncbi_discovery_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add \
  pubtator_link/services/citation_graph.py \
  pubtator_link/services/topic_literature_map.py \
  pubtator_link/services/ncbi_discovery.py \
  pubtator_link/mcp/resources.py \
  pubtator_link/mcp/catalog.py \
  pubtator_link/services/workflow_help.py \
  docs/mcp-tool-catalog.md \
  tests/unit/test_workflow_help.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_tool_catalog.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_review_rerag_mcp.py \
  tests/unit/test_citation_graph_service.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/test_ncbi_discovery_service.py
git commit -m "docs: update graph workflow guidance"
```

---

### Task 6: Final Verification, Push, and Docker Restart

**Files:**
- No source edits unless a verification failure identifies a task-scoped defect.

- [ ] **Step 1: Run the focused graph suite**

Run:

```bash
uv run pytest \
  tests/unit/test_literature_graph_models.py \
  tests/unit/test_literature_graph_compact.py \
  tests/unit/test_literature_providers.py \
  tests/unit/test_literature_identifier_resolution.py \
  tests/unit/test_citation_graph_service.py \
  tests/unit/test_related_evidence_service.py \
  tests/unit/test_topic_literature_map_service.py \
  tests/unit/mcp/test_mcp_service_adapters.py \
  tests/unit/mcp/test_mcp_facade.py \
  tests/unit/mcp/test_mcp_tool_catalog.py \
  tests/unit/test_review_context_batch_budgeting.py \
  tests/unit/test_review_context_service.py \
  tests/unit/test_review_rerag_models.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run local CI**

Run:

```bash
make ci-local
```

Expected: PASS with all formatting, linting, type checking, and tests green.

- [ ] **Step 3: Push the stacked branch**

Run:

```bash
git status --short --branch
git log --oneline origin/codex/llm-first-literature-graph-redesign..HEAD
git push origin codex/llm-first-literature-graph-redesign
```

Expected: only intended tracked changes are committed; `test.md` and `docs/superpowers/plans/2026-05-03-literature-map-epic-implementation.md` remain untracked and untouched; push succeeds.

- [ ] **Step 4: Rebuild and restart Docker from this branch**

Run:

```bash
make docker-build
make docker-up
docker compose -f docker/docker-compose.yml ps
```

Expected: server and postgres containers are running and healthy.

- [ ] **Step 5: Run live smoke checks against the restarted server**

Run:

```bash
curl -s http://localhost:8011/health
```

Expected: JSON contains `"status":"healthy"`.

Run a live citation graph smoke through the MCP endpoint or HTTP route used in the repo's existing smoke pattern for:

```json
{"pmid":"28386255","direction":"both","response_mode":"compact","max_results":10}
```

Expected: source has `pmcid`, `availability.has_pmc_full_text=true`, `cited_by_status` distinguishes provider success/empty/failure, and compact counts are present.

Run the DOI smoke for:

```json
{"doi":"10.1136/annrheumdis-2015-208690","direction":"both","response_mode":"compact","max_results":10}
```

Expected: source or identifier resolution status shows PMID `26802180` when provider data is reachable; provider failures are explicit if a live provider is down.

- [ ] **Step 6: Report completion**

Report:

- each task commit hash and exact commit message;
- focused test command and result after each task;
- final focused graph suite result;
- `make ci-local` result;
- Docker rebuild/restart result;
- live smoke outputs for PMID `28386255` and DOI `10.1136/annrheumdis-2015-208690`;
- any residual gaps, including provider downtime or live-network variability.
