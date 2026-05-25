import pytest
from pydantic import ValidationError

from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionRequest,
    ArticleIdConversionResponse,
    CitationLookupRecord,
    CitationLookupRequest,
    CitationLookupResponse,
    DiscoveryMeta,
    MeshDescriptor,
    MeshLookupRequest,
    MeshLookupResponse,
    RelatedArticleRecord,
    RelatedArticlesRequest,
    RelatedArticlesResponse,
)


def test_article_id_conversion_response_serializes_meta_alias() -> None:
    response = ArticleIdConversionResponse(
        records=[
            ArticleIdConversionRecord(
                input_id="PMC123",
                input_kind="pmcid",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
                reason=None,
            )
        ],
        candidate_pmids=["123"],
        unresolved=[],
        meta=DiscoveryMeta(
            source_urls=["https://example.test/idconv"],
            next_commands=[
                {
                    "tool": "pubtator_stage_research_session",
                    "arguments": {"pmids": ["123"]},
                }
            ],
        ),
    )

    dumped = response.model_dump(by_alias=True)

    assert dumped["success"] is True
    assert dumped["_meta"]["research_use_only"] is True
    assert dumped["_meta"]["next_commands"] == [
        {
            "tool": "pubtator_stage_research_session",
            "arguments": {"pmids": ["123"]},
        }
    ]
    assert dumped["candidate_pmids"] == ["123"]
    assert dumped["unresolved"] == []
    assert dumped["records"][0]["pmid"] == "123"
    assert dumped["records"][0]["input_kind"] == "pmcid"


def test_article_id_conversion_request_defaults_and_constraints() -> None:
    request = ArticleIdConversionRequest(ids=["PMC123"])

    assert request.source == "auto"
    assert request.target is None

    with pytest.raises(ValidationError):
        ArticleIdConversionRequest(ids=[])

    with pytest.raises(ValidationError):
        ArticleIdConversionRequest(ids=["1"] * 201)

    with pytest.raises(ValidationError):
        ArticleIdConversionRequest(ids=["1"], source="isbn")


def test_mesh_lookup_response_keeps_descriptor_fields() -> None:
    response = MeshLookupResponse(
        query="familial mediterranean fever",
        descriptors=[
            MeshDescriptor(
                ui="D010505",
                name="Familial Mediterranean Fever",
                scope_note="An autosomal recessive autoinflammatory disorder.",
                tree_numbers=["C16.320.565"],
                entry_terms=["Periodic Disease", "Familial Paroxysmal Polyserositis"],
                search_terms=["familial mediterranean fever", "FMF"],
            )
        ],
        candidate_pmids=[],
    )

    descriptor = response.descriptors[0]

    assert descriptor.name == "Familial Mediterranean Fever"
    assert descriptor.ui == "D010505"
    assert descriptor.scope_note == "An autosomal recessive autoinflammatory disorder."
    assert descriptor.entry_terms == [
        "Periodic Disease",
        "Familial Paroxysmal Polyserositis",
    ]
    assert descriptor.search_terms == ["familial mediterranean fever", "FMF"]
    assert response.candidate_pmids == []


def test_mesh_lookup_request_defaults_and_constraints() -> None:
    request = MeshLookupRequest(query="familial mediterranean fever")

    assert request.limit == 10
    assert request.exact is False

    with pytest.raises(ValidationError):
        MeshLookupRequest(query="")

    with pytest.raises(ValidationError):
        MeshLookupRequest(query="x", limit=0)

    with pytest.raises(ValidationError):
        MeshLookupRequest(query="x", limit=51)


def test_citation_lookup_response_tracks_statuses_and_candidates() -> None:
    response = CitationLookupResponse(
        records=[
            CitationLookupRecord(
                citation="Ozen et al. Familial Mediterranean fever.",
                status="matched",
                pmid="123",
                doi="10.1000/example",
                title="Familial Mediterranean fever",
                journal="Example Journal",
                year=2024,
                reason=None,
            ),
            CitationLookupRecord(
                citation="Unknown citation.",
                status="not_found",
                reason="no PubMed match",
            ),
        ],
        candidate_pmids=["123"],
    )

    assert [record.status for record in response.records] == ["matched", "not_found"]
    assert response.records[0].journal == "Example Journal"
    assert response.records[0].year == 2024
    assert response.records[1].reason == "no PubMed match"
    assert response.candidate_pmids == ["123"]


def test_citation_lookup_request_constraints() -> None:
    request = CitationLookupRequest(citations=["Ozen et al."])

    assert request.citations == ["Ozen et al."]

    with pytest.raises(ValidationError):
        CitationLookupRequest(citations=[])

    with pytest.raises(ValidationError):
        CitationLookupRequest(citations=["citation"] * 101)


def test_related_articles_response_deduplicates_candidates_in_caller_order() -> None:
    response = RelatedArticlesResponse(
        source_pmids=["1", "2"],
        mode="similar",
        related_articles=[
            RelatedArticleRecord(source_pmid="1", pmid="10", relation="similar"),
            RelatedArticleRecord(
                source_pmid="1",
                pmid="11",
                relation="similar",
                title="Related article",
                journal="Example Journal",
                year=2022,
            ),
            RelatedArticleRecord(source_pmid="2", pmid="10", relation="similar"),
        ],
        candidate_pmids=["10", "11", "10"],
        unresolved=[],
    )

    assert [record.pmid for record in response.related_articles] == ["10", "11", "10"]
    assert response.source_pmids == ["1", "2"]
    assert response.mode == "similar"
    assert response.candidate_pmids == ["10", "11"]
    assert response.unresolved == []


def test_related_article_record_rejects_invalid_relation() -> None:
    with pytest.raises(ValidationError):
        RelatedArticleRecord(source_pmid="1", pmid="2", relation="nonsense")


def test_related_articles_request_defaults_and_constraints() -> None:
    request = RelatedArticlesRequest(pmids=["1"])

    assert request.mode == "similar"
    assert request.limit == 20

    with pytest.raises(ValidationError):
        RelatedArticlesRequest(pmids=[])

    with pytest.raises(ValidationError):
        RelatedArticlesRequest(pmids=["1"] * 101)

    with pytest.raises(ValidationError):
        RelatedArticlesRequest(pmids=["1"], mode="cites")

    with pytest.raises(ValidationError):
        RelatedArticlesRequest(pmids=["1"], limit=101)
