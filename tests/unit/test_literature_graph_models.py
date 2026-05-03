import pytest
from pydantic import ValidationError

from pubtator_link.models.literature_graph import (
    LiteratureAuthor,
    LiteratureCandidateSummary,
    LiteratureEntity,
    LiteratureGraphEdge,
    LiteratureGraphNode,
    LiteratureGraphProvenance,
    LiteratureGraphResponseMeta,
    LiteraturePaper,
    LiteratureProviderStatus,
    LiteratureQueryRelevance,
    PublicationCitationGraphRequest,
    PublicationCitationGraphResponse,
    RelatedEvidenceCandidatesRequest,
    RelatedEvidenceCandidatesResponse,
    TopicLiteratureMapRequest,
    TopicLiteratureMapResponse,
    dedupe_edges,
    dedupe_papers,
)


def test_citation_graph_request_requires_exactly_one_identifier_and_normalizes_doi() -> None:
    assert PublicationCitationGraphRequest(pmid="40562663").pmid == "40562663"
    assert (
        PublicationCitationGraphRequest(doi=" DOI:10.1016/J.ARD.2025.05.020 ").doi
        == "10.1016/j.ard.2025.05.020"
    )

    for payload in ({}, {"pmid": "40562663", "doi": "10.1016/j.ard.2025.05.020"}):
        with pytest.raises(ValidationError, match="exactly one of pmid or doi is required"):
            PublicationCitationGraphRequest(**payload)


def test_related_evidence_request_normalizes_numeric_pmid_string() -> None:
    request = RelatedEvidenceCandidatesRequest(pmid=" PMID:40562663 ", max_results=25)

    assert request.pmid == "40562663"


def test_request_bounds_are_enforced() -> None:
    with pytest.raises(ValidationError):
        PublicationCitationGraphRequest(pmid="40562663", max_results=0)
    with pytest.raises(ValidationError):
        PublicationCitationGraphRequest(pmid="40562663", max_results=101)
    with pytest.raises(ValidationError):
        RelatedEvidenceCandidatesRequest(pmid="40562663", max_results=0)
    with pytest.raises(ValidationError):
        RelatedEvidenceCandidatesRequest(pmid="40562663", max_results=101)
    with pytest.raises(ValidationError):
        TopicLiteratureMapRequest(pmids=["1"] * 101)
    with pytest.raises(ValidationError):
        TopicLiteratureMapRequest(pmids=["1"], max_seed_papers=0)
    with pytest.raises(ValidationError):
        TopicLiteratureMapRequest(pmids=["1"], max_seed_papers=51)
    with pytest.raises(ValidationError):
        TopicLiteratureMapRequest(pmids=["1"], max_neighbors_per_paper=0)
    with pytest.raises(ValidationError):
        TopicLiteratureMapRequest(pmids=["1"], max_neighbors_per_paper=21)


def test_topic_map_request_requires_query_or_pmids_and_normalizes_pmids() -> None:
    assert (
        TopicLiteratureMapRequest(query="familial mediterranean fever").query
        == "familial mediterranean fever"
    )
    assert TopicLiteratureMapRequest(pmids=[" PMID:40562663 ", "39596913"]).pmids == [
        "40562663",
        "39596913",
    ]

    with pytest.raises(ValidationError, match="at least one of query or pmids is required"):
        TopicLiteratureMapRequest()


def test_dedupe_papers_prefers_pmid_then_doi_then_pmcid_then_openalex_id() -> None:
    papers = [
        LiteraturePaper(pmid="1", doi="10.1/ABC", title="PMID paper"),
        LiteraturePaper(pmid="1", doi="10.1/abc", title="Duplicate PMID paper"),
        LiteraturePaper(doi="10.2/XYZ", title="DOI paper"),
        LiteraturePaper(doi="10.2/xyz", title="Duplicate DOI paper"),
        LiteraturePaper(pmcid="PMC3", title="PMCID paper"),
        LiteraturePaper(pmcid="PMC3", title="Duplicate PMCID paper"),
        LiteraturePaper(openalex_id="https://openalex.org/W4", title="OpenAlex paper"),
        LiteraturePaper(openalex_id="https://openalex.org/W4", title="Duplicate OpenAlex paper"),
    ]

    deduped = dedupe_papers(papers)

    assert [paper.title for paper in deduped] == [
        "PMID paper",
        "DOI paper",
        "PMCID paper",
        "OpenAlex paper",
    ]


def test_dedupe_papers_merges_overlapping_identifiers_across_providers() -> None:
    papers = [
        LiteraturePaper(doi="10.1/shared", title="DOI only"),
        LiteraturePaper(pmid="1", doi="10.1/shared", title="PMID and DOI"),
        LiteraturePaper(pmid="1", title="PMID only"),
        LiteraturePaper(pmid="2", pmcid="PMC2", title="PMID and PMCID"),
        LiteraturePaper(
            pmcid="PMC2", openalex_id="https://openalex.org/W2", title="PMCID and OpenAlex"
        ),
        LiteraturePaper(openalex_id="https://openalex.org/W2", title="OpenAlex only"),
    ]

    deduped = dedupe_papers(papers)

    assert [paper.title for paper in deduped] == ["DOI only", "PMID and PMCID"]


def test_dedupe_papers_coalesces_late_bridge_identifiers() -> None:
    papers = [
        LiteraturePaper(pmid="1", title="PMID first"),
        LiteraturePaper(doi="10.x/shared", title="DOI second"),
        LiteraturePaper(pmid="1", doi="10.x/shared", title="Bridge later"),
        LiteraturePaper(doi="10.x/shared", title="DOI after bridge"),
    ]

    deduped = dedupe_papers(papers)

    assert [paper.title for paper in deduped] == ["PMID first"]


def test_dedupe_edges_merges_reasons_and_provider_provenance_on_conceptual_edge() -> None:
    first = LiteratureGraphEdge(
        source="paper:1",
        target="paper:2",
        edge_type="cites",
        weight=0.5,
        reasons=["crossref_reference"],
        provenance=[LiteratureGraphProvenance(provider="crossref", source_id="10.1/source")],
    )
    second = LiteratureGraphEdge(
        source="paper:1",
        target="paper:2",
        edge_type="cites",
        weight=0.9,
        reasons=["crossref_reference", "openalex_referenced_work"],
        provenance=[LiteratureGraphProvenance(provider="openalex", source_id="W1")],
    )

    deduped = dedupe_edges([first, second])

    assert len(deduped) == 1
    assert deduped[0].reasons == ["crossref_reference", "openalex_referenced_work"]
    assert [item.provider for item in deduped[0].provenance] == ["crossref", "openalex"]
    assert deduped[0].weight == 0.9


def test_graph_node_keys_are_stable() -> None:
    node = LiteratureGraphNode(node_type="paper", paper=LiteraturePaper(pmid="40562663"))

    assert node.key == "paper:pmid:40562663"


def test_computed_keys_use_strongest_available_identifier() -> None:
    assert LiteraturePaper(doi="10.1/ABC").key == "paper:doi:10.1/abc"
    assert LiteraturePaper(pmcid="PMC1").key == "paper:pmcid:PMC1"
    assert LiteraturePaper(openalex_id="https://openalex.org/W1").key == (
        "paper:openalex:https://openalex.org/W1"
    )
    assert LiteraturePaper(title="Unresolved Reference").key == "paper:title:unresolved reference"
    assert LiteratureAuthor(name="Ada Example", openalex_id="A1").key == "author:openalex:A1"
    assert LiteratureAuthor(name="Ada Example", orcid="0000-0001").key == "author:orcid:0000-0001"
    assert LiteratureAuthor(name="Ada Example").key == "author:name:ada example"
    assert LiteratureEntity(entity_id="MESH:D0001", entity_type="disease", name="Disease").key == (
        "entity:MESH:D0001"
    )


def test_graph_node_rejects_missing_or_mismatched_payload() -> None:
    with pytest.raises(ValidationError, match="paper nodes require exactly paper payload"):
        LiteratureGraphNode(node_type="paper")

    with pytest.raises(ValidationError, match="author nodes require exactly author payload"):
        LiteratureGraphNode(node_type="author", paper=LiteraturePaper(pmid="40562663"))


def test_response_meta_serializes_with_alias_and_validates_by_name() -> None:
    citation = PublicationCitationGraphResponse(source=LiteraturePaper(pmid="40562663"))
    related = RelatedEvidenceCandidatesResponse(source=LiteraturePaper(pmid="40562663"))
    topic = TopicLiteratureMapResponse(meta={"research_use_only": False})

    assert "_meta" in citation.model_dump()
    assert "meta" not in citation.model_dump()
    assert "_meta" in related.model_dump()
    assert "meta" not in related.model_dump()
    assert topic.meta.research_use_only is False


def test_candidate_summary_access_flags_and_source_tool_vocab() -> None:
    candidate = LiteratureCandidateSummary(
        pmid="28386255",
        title="EULAR recommendations for familial Mediterranean fever",
        access="full_text",
        access_flags={
            "has_pmc_full_text": True,
            "is_open_access": True,
            "has_pdf": False,
        },
        relevance_to_query=LiteratureQueryRelevance(
            score=0.9,
            matched_terms=["familial mediterranean fever", "colchicine"],
            matched_intents=["guideline_intent", "treatment_intent"],
            reasons=["title_query_overlap", "guideline_or_consensus_match"],
        ),
        source_tools=["topic_search", "citation_graph"],
    )

    dumped = candidate.model_dump()
    assert dumped["access"] == "full_text"
    assert dumped["access_flags"]["has_pmc_full_text"] is True
    assert dumped["relevance_to_query"]["matched_intents"] == [
        "guideline_intent",
        "treatment_intent",
    ]
    assert dumped["source_tools"] == ["topic_search", "citation_graph"]


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


def test_provider_status_result_count_defaults_to_zero() -> None:
    status = LiteratureProviderStatus(
        provider="unpaywall",
        operation="open_access",
        status="disabled",
        message="UNPAYWALL_EMAIL is not configured.",
    )

    assert status.result_count == 0


def test_graph_response_meta_tracks_budget_cache_and_ranking() -> None:
    meta = LiteratureGraphResponseMeta(
        response_mode="compact",
        response_size_class="medium",
        truncated=True,
        omitted_counts={"reference_candidates": 3},
        budget_advice="Reduce max_results or request response_mode='full'.",
        cache_key="citation:40562663:compact",
        snapshot_date="2026-05-03",
        source_versions={"ranker": "topic_map_ranker_v1"},
        ranking_version="topic_map_ranker_v1",
    )

    assert meta.response_mode == "compact"
    assert meta.response_size_class == "medium"
    assert meta.omitted_counts == {"reference_candidates": 3}
