"""Response-Envelope v1.2: every data tool's REAL payload validates against the schema.

Each tool is called through the MCP egress with its own schema ``examples``. Its body, its
service adapter and the response models run for real; only the services behind them are
replaced: the PubTator3 client answers with the recorded fixtures of
``tests/fixtures/api_responses.py`` and each service returns its own response model. So the
frame rule (``result`` object or ``results`` array, v1 section 1) is checked on the shape each
tool really sends, with ``include_meta`` on and off.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import jsonschema
import pytest

from pubtator_link.api.routes.dependencies.resources import (
    AppResources,
    bind_app_resources,
    reset_app_resources,
)
from pubtator_link.mcp.egress_meta import OPS_TOOLS, PRIMARY_KEYS
from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.models.corpus_suggestion import (
    CorpusCandidate,
    CorpusSearchTrace,
    CorpusSuggestionResponse,
)
from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    CitationLookupRecord,
    CitationLookupResponse,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleRecord,
    RelatedArticlesResponse,
)
from pubtator_link.models.literature_graph import (
    LiteraturePaper,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidate,
    RelatedEvidenceCandidatesResponse,
    TopicLiteratureMapResponse,
)
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.models.publication_passages import (
    PublicationContextEstimate,
    PublicationContextEstimateResponse,
    PublicationPassage,
    PublicationPassageResponse,
)
from pubtator_link.models.research_session_list import (
    ListResearchSessionsResponse,
    ResearchSessionSummary,
)
from pubtator_link.models.responses import (
    DiagnosticsResponse,
    PMCExportResponse,
    PublicationExportResponse,
)
from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    EvidenceCertaintyRecord,
    EvidenceCertaintyResponse,
    InspectReviewIndexResponse,
    ListEvidenceCertaintyResponse,
    ListReviewIndexesResponse,
    PreparationStatus,
    RecordReviewContextResponse,
    ResearchSessionManifest,
    ResearchSessionStatusResponse,
    RetrieveReviewContextBatchResponse,
    RetrieveReviewContextResponse,
    ReviewAuditBundle,
    ReviewAuditTrailItem,
    ReviewAuditTrailResponse,
    ReviewIndexInventoryItem,
    ReviewIndexSummaryResponse,
    ReviewIndexTotals,
    ReviewLlmContext,
    ReviewLlmContextEvent,
    ReviewPassageLookupResponse,
    ReviewSourceSummary,
    SourceCoverageHint,
    StageResearchSessionResponse,
)
from pubtator_link.models.variants import VariantEvidenceResponse
from tests.conformance.test_envelope_schema_v1_2 import (
    REQUIRED_META,
    SCHEMA,
    _call,
    _example_arguments,
)
from tests.fixtures.api_responses import MockPubTatorResponses

PMID = "33454820"
REVIEW = "rev_1"
NOW = "2026-05-02T00:00:00Z"
PASSAGE_FETCHED = {
    "rev:33454820:abstract:0": datetime(2026, 3, 4, 5, 6, 7, tzinfo=UTC),
    "rev:33454820:results:1": datetime(2026, 1, 1, tzinfo=UTC),  # stored, not returned below
}
PASSAGE = ContextPassage(
    citation_key="S1",
    passage_id="rev:33454820:abstract:0",
    section="abstract",
    text="Colchicine reduced attacks.",
    pmid=PMID,
)
PACK = ContextPack(question="colchicine", passages=[PASSAGE], citation_map={"S1": PMID})
STATUS = PreparationStatus(complete=1)
MANIFEST = ResearchSessionManifest(session_id="ses_1", review_id=REVIEW, query="colchicine")
CERTAINTY = EvidenceCertaintyRecord(
    certainty_id="cer_1", review_id=REVIEW, outcome="attack rate", created_at=NOW, updated_at=NOW
)
PAPER = LiteraturePaper(pmid=PMID, title="Colchicine response in FMF")


class _Connection:
    """The one query the egress sends to date review-index evidence."""

    async def fetchval(self, _sql: str, _review_id: str, *passage_ids: list[str]) -> Any:
        wanted = passage_ids[0] if passage_ids else list(PASSAGE_FETCHED)
        return min((PASSAGE_FETCHED[p] for p in wanted if p in PASSAGE_FETCHED), default=None)

    async def __aenter__(self) -> _Connection:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


class _Upstream:
    """Every service behind the tools; each answer is the service's own response model."""

    def _acquire(self) -> _Connection:
        return _Connection()

    # PubTator3 client: recorded upstream responses.
    async def search_publications(self, **_: Any) -> dict[str, Any]:
        return MockPubTatorResponses.search_publications_response()

    async def autocomplete_entity(self, **_: Any) -> Any:
        return MockPubTatorResponses.entity_autocomplete_response()

    async def find_relations(self, **_: Any) -> Any:
        return MockPubTatorResponses.entity_relations_response()

    async def submit_text_annotation(self, **_: Any) -> str:
        return MockPubTatorResponses.text_annotation_submit_response()

    async def retrieve_text_annotation(self, **_: Any) -> dict[str, Any]:
        return MockPubTatorResponses.text_annotation_results_completed()

    async def retrieve_text_annotation_until_ready(self, **_: Any) -> dict[str, Any]:
        return MockPubTatorResponses.text_annotation_results_completed()

    # Publications.
    async def export_publications_list(self, *_: Any, **__: Any) -> PublicationExportResponse:
        export = MockPubTatorResponses.publication_export_biocjson()
        return PublicationExportResponse(format="biocjson", export_data=export, count=1)

    async def export_pmc_publications_list(
        self, *, pmcids: list[str], **_: Any
    ) -> PMCExportResponse:
        document = MockPubTatorResponses.pmc_export_response()["PubTator3"][0] | {"id": pmcids[0]}
        return PMCExportResponse(
            format="biocjson", pmcids=pmcids, total_documents=1, documents=[document]
        )

    async def get_passages(self, *_: Any, **__: Any) -> PublicationPassageResponse:
        passage = PublicationPassage(
            passage_id=f"{PMID}:abstract:0",
            pmid=PMID,
            section="abstract",
            text="Colchicine reduced attacks.",
            char_count=27,
            source="pubtator_abstract",
        )
        estimate = PublicationContextEstimate(
            estimated_passages=1,
            estimated_chars=27,
            sections_by_pmid={PMID: ["abstract"]},
            recommended_mode="abstracts",
        )
        return PublicationPassageResponse(
            pmids=[PMID], mode="abstracts", passages=[passage], context_estimate=estimate
        )

    async def estimate_context(self, *_: Any, **__: Any) -> PublicationContextEstimateResponse:
        return PublicationContextEstimateResponse(
            estimated_passages=1,
            estimated_chars=27,
            sections_by_pmid={PMID: ["abstract"]},
            recommended_mode="abstracts",
            pmids=[PMID],
            mode="abstracts",
        )

    async def get_metadata(self, *_: Any, **__: Any) -> PublicationMetadataResponse:
        return PublicationMetadataResponse(metadata=[PublicationMetadata(pmid=PMID, title="T")])

    # NCBI discovery.
    async def map_article_ids(self, **_: Any) -> ArticleIdConversionResponse:
        record = ArticleIdConversionRecord(
            input_id=PMID, input_kind="pmid", status="resolved", pmid=PMID
        )
        return ArticleIdConversionResponse(records=[record], candidate_pmids=[PMID])

    async def lookup_mesh(self, **_: Any) -> MeshLookupResponse:
        descriptor = MeshDescriptor(ui="D010505", name="Familial Mediterranean Fever")
        return MeshLookupResponse(query="FMF", descriptors=[descriptor])

    async def lookup_citation(self, **_: Any) -> CitationLookupResponse:
        record = CitationLookupRecord(citation="Colchicine in FMF", status="matched", pmid=PMID)
        return CitationLookupResponse(records=[record], candidate_pmids=[PMID])

    async def find_related_articles(self, **_: Any) -> RelatedArticlesResponse:
        return RelatedArticlesResponse(
            source_pmids=[PMID],
            mode="similar",
            related_articles=[
                RelatedArticleRecord(source_pmid=PMID, pmid="33454821", relation="similar")
            ],
            candidate_pmids=["33454821"],
        )

    # Literature graph.
    async def get_citation_graph(self, *_: Any, **__: Any) -> PublicationCitationGraphResponse:
        return PublicationCitationGraphResponse(source=PAPER, candidate_pmids=[PMID])

    async def find_candidates(self, *_: Any, **__: Any) -> RelatedEvidenceCandidatesResponse:
        candidate = RelatedEvidenceCandidate(paper=PAPER, score=0.9)
        return RelatedEvidenceCandidatesResponse(
            source=PAPER, candidates=[candidate], candidate_pmids=[PMID]
        )

    async def build_map(self, *_: Any, **__: Any) -> TopicLiteratureMapResponse:
        return TopicLiteratureMapResponse(query="colchicine", seed_pmids=[PMID])

    async def suggest(self, *_: Any, **__: Any) -> CorpusSuggestionResponse:
        candidate = CorpusCandidate(pmid=PMID, role="guideline", rationale="guideline hit")
        trace = CorpusSearchTrace(query="colchicine", result_pmids=[PMID])
        return CorpusSuggestionResponse(
            candidate_pmids=[PMID], candidates=[candidate], searches=[trace]
        )

    async def lookup(self, *_: Any, **__: Any) -> VariantEvidenceResponse:
        return VariantEvidenceResponse(query={"gene": "BRAF", "protein_change": "V600E"})

    async def get_diagnostics(self) -> DiagnosticsResponse:
        return DiagnosticsResponse(status="ready")

    # Review index.
    # The review indexing service runs for real over this repository and queue.
    @property
    def repository(self) -> _Upstream:
        return self

    async def research_session_exists(self, *_: Any) -> bool:
        return True

    async def preparation_job_statuses(self, *_: Any) -> dict[str, str]:
        return {}

    async def preparation_status(self, *_: Any, **__: Any) -> PreparationStatus:
        return STATUS

    async def link_review_session_source(self, *_: Any) -> None:
        return None

    async def enqueue_pmid(self, *_: Any) -> str:
        return "newly_queued"

    async def preflight_pmids(self, *_: Any, **__: Any) -> list[SourceCoverageHint]:
        return [SourceCoverageHint(pmid=PMID)]

    async def stage(self, *_: Any, **__: Any) -> StageResearchSessionResponse:
        return StageResearchSessionResponse(manifest=MANIFEST)

    async def get_status(self, *_: Any, **__: Any) -> ResearchSessionStatusResponse:
        return ResearchSessionStatusResponse(manifest=MANIFEST)

    get_status_by_session_id = get_status

    async def list_sessions(self, *_: Any, **__: Any) -> ListResearchSessionsResponse:
        session = ResearchSessionSummary(session_id="ses_1", review_id=REVIEW)
        return ListResearchSessionsResponse(sessions=[session], total_returned=1)

    async def get_review_index_status(self, *_: Any, **__: Any) -> InspectReviewIndexResponse:
        source = ReviewSourceSummary(
            source_id=f"pmid:{PMID}", source_kind="pubtator_abstract", job_status="complete"
        )
        return InspectReviewIndexResponse(
            review_id=REVIEW,
            preparation_status=STATUS,
            sources=[source],
            totals=ReviewIndexTotals(pmid_count=1, source_count=1, passage_count=1),
            failed_sources=[],
        )

    async def retrieve_context(self, *_: Any, **__: Any) -> RetrieveReviewContextResponse:
        return RetrieveReviewContextResponse(
            review_id=REVIEW, context_pack=PACK, preparation_status=STATUS
        )

    async def retrieve_context_batch(
        self, *_: Any, **__: Any
    ) -> RetrieveReviewContextBatchResponse:
        return RetrieveReviewContextBatchResponse(
            review_id=REVIEW, merged_context_pack=PACK, preparation_status=STATUS
        )

    async def get_passages_by_id(self, *_: Any, **__: Any) -> ReviewPassageLookupResponse:
        return ReviewPassageLookupResponse(review_id=REVIEW, passages=[PASSAGE])

    get_neighboring_passages = get_passages_by_id

    async def get_audit_trail(self, *_: Any, **__: Any) -> ReviewAuditTrailResponse:
        item = ReviewAuditTrailItem(
            pmid=PMID,
            passage_id=PASSAGE.passage_id,
            stable_citation_key="c_1",
            section="abstract",
            quote="Colchicine reduced attacks.",
            char_count=27,
        )
        return ReviewAuditTrailResponse(review_id=REVIEW, items=[item])

    async def export_bundle(self, *_: Any, **__: Any) -> ReviewAuditBundle:
        return ReviewAuditBundle(
            review_id=REVIEW,
            generated_at=NOW,
            preparation_status=STATUS,
            totals=ReviewIndexTotals(),
            sources=[],
            failed_sources=[],
            coverage_distribution={},
            resolver_attempts=[],
            passage_ids=[],
            stable_citation_keys={},
        )

    async def record_context(self, *_: Any, **__: Any) -> RecordReviewContextResponse:
        context = ReviewLlmContext(
            context_id="ctx_1", review_id=REVIEW, created_at=NOW, updated_at=NOW
        )
        event = ReviewLlmContextEvent(
            event_id="evt_1", review_id=REVIEW, event_type="note", created_at=NOW
        )
        return RecordReviewContextResponse(context=context, event=event)

    async def list_indexes(self, **_: Any) -> ListReviewIndexesResponse:
        return ListReviewIndexesResponse(indexes=[_index_summary()])

    async def get_summary(self, *_: Any, **__: Any) -> ReviewIndexSummaryResponse:
        return ReviewIndexSummaryResponse(index=_index_summary())

    async def upsert(self, *_: Any, **__: Any) -> EvidenceCertaintyResponse:
        return EvidenceCertaintyResponse(record=CERTAINTY)

    get = upsert

    async def list(self, *_: Any, **__: Any) -> ListEvidenceCertaintyResponse:
        return ListEvidenceCertaintyResponse(records=[CERTAINTY])


def _index_summary() -> ReviewIndexInventoryItem:
    return ReviewIndexInventoryItem(
        review_id=REVIEW, created_at=NOW, updated_at=NOW, preparation_status=STATUS
    )


@pytest.fixture
def upstream() -> Any:
    fake: Any = _Upstream()
    services = {
        name: fake for name in AppResources.__dataclass_fields__ if name != "schema_diagnostics"
    }
    token = bind_app_resources(AppResources(**services))
    yield fake
    reset_app_resources(token)


# Arguments the schema examples leave out although the tool needs one of them.
EXTRA_ARGUMENTS = {
    "stage_research_session": {"query": "colchicine FMF"},
    "review_quickstart": {"query": "colchicine FMF"},
}
NESTED = {  # no single primary payload: the whole payload is the ``result`` object
    "get_variant_evidence",
    "generate_topic_literature_map",
    "get_publication_citation_graph",
    "compute_publication_context",
    "submit_text_annotation",
    "get_text_annotation_results",
    "index_review_evidence",
    "get_review_index_status",
    "ground_question",
    "review_quickstart",
    "export_review_audit_bundle",
    "record_review_context",
}
ALREADY_RESULTS = {"search_literature", "search_guidelines"}


async def _run(mcp: Any, tool: Any, **extra: Any) -> dict[str, Any]:
    arguments = _example_arguments(tool, **extra) | EXTRA_ARGUMENTS.get(tool.name, {})
    result = await _call(mcp, tool.name, arguments)
    envelope: dict[str, Any] = result.structured_content
    assert envelope["success"] is True, (tool.name, envelope)
    assert json.loads(result.content[0].text) == envelope, tool.name  # the text mirror
    return envelope


@pytest.mark.parametrize("include_meta", [True, False])
async def test_every_data_tool_real_payload_validates(upstream: Any, include_meta: bool) -> None:
    mcp = create_pubtator_mcp(profile="full")
    tools = [tool for tool in await mcp.list_tools() if tool.name not in OPS_TOOLS]
    # Every data tool has a decided frame; a new tool must be added to one of the three sets.
    assert {tool.name for tool in tools} == set(PRIMARY_KEYS) | NESTED | ALREADY_RESULTS
    for tool in tools:
        envelope = await _run(mcp, tool, include_meta=include_meta)
        jsonschema.validate(envelope, SCHEMA)
        assert all(envelope["_meta"][key] for key in REQUIRED_META - {"elapsed_ms"}), tool.name
        # The retired domain alias is gone, and the primary payload is not empty.
        assert PRIMARY_KEYS.get(tool.name) not in envelope, tool.name
        assert envelope.get("results") or envelope.get("result"), tool.name
        if tool.name in NESTED:
            assert set(envelope) == {"success", "result", "_meta"}, tool.name


async def test_review_result_is_dated_by_the_passages_it_returns(upstream: Any) -> None:
    mcp = create_pubtator_mcp(profile="full")
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    async def retrieved_at(tool: str) -> str:
        return str((await _run(mcp, tools[tool]))["_meta"]["retrieved_at"])

    # The index also holds an older passage (2026-01-01) that these results do not return.
    assert await retrieved_at("get_review_context") == "2026-03-04T05:06:07Z"
    assert await retrieved_at("get_review_passages_by_id") == "2026-03-04T05:06:07Z"
    # A result without passages describes the whole index: its oldest passage.
    assert await retrieved_at("get_review_index_summary") == "2026-01-01T00:00:00Z"


async def test_doi_cache_hit_keeps_the_original_fetch_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pubtator_link.services import literature_identifier_resolution as resolution
    from pubtator_link.services.provenance import start_fetch_log

    class _Discovery:
        calls = 0

        async def map_article_ids(self, dois: list[str], **_: Any) -> Any:
            self.calls += 1
            record = ArticleIdConversionRecord(
                input_id=dois[0], input_kind="doi", status="resolved", pmid=PMID
            )
            return ArticleIdConversionResponse(records=[record])

    discovery = _Discovery()
    resolver = resolution.DoiPmidResolver(discovery_service=discovery)
    monkeypatch.setattr(resolution, "utc_now", lambda: "2026-01-01T00:00:00Z")
    first = start_fetch_log()
    assert (await resolver.resolve(["10.1/x"], max_ids=5)).resolved == {"10.1/x": PMID}
    assert first == []  # a live lookup is dated by the call itself
    monkeypatch.setattr(resolution, "utc_now", lambda: "2026-02-02T00:00:00Z")
    second = start_fetch_log()
    assert (await resolver.resolve(["10.1/x"], max_ids=5)).cached_count == 1
    assert second == ["2026-01-01T00:00:00Z"]
    assert discovery.calls == 1
