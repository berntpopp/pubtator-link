from pubtator_link.models.discovery import (
    ArticleIdConversionRecord,
    ArticleIdConversionResponse,
    CitationLookupRecord,
    CitationLookupResponse,
    DiscoveryMeta,
    MeshDescriptor,
    MeshLookupResponse,
    RelatedArticleRecord,
    RelatedArticlesResponse,
)


def test_article_id_conversion_response_serializes_meta_alias() -> None:
    response = ArticleIdConversionResponse(
        records=[
            ArticleIdConversionRecord(
                input_id="PMC123",
                status="resolved",
                pmid="123",
                pmcid="PMC123",
            )
        ],
        candidate_pmids=["123"],
        meta=DiscoveryMeta(
            source_urls=["https://example.test/idconv"],
            next_commands=["pubtator.stage_research_session"],
        ),
    )

    dumped = response.model_dump(by_alias=True)

    assert dumped["_meta"]["research_use_only"] is True
    assert dumped["candidate_pmids"] == ["123"]
    assert dumped["records"][0]["pmid"] == "123"


def test_mesh_lookup_response_keeps_descriptor_fields() -> None:
    response = MeshLookupResponse(
        query="familial mediterranean fever",
        descriptors=[
            MeshDescriptor(
                descriptor_ui="D010505",
                name="Familial Mediterranean Fever",
                tree_numbers=["C16.320.565"],
                entry_terms=["Periodic Disease", "Familial Paroxysmal Polyserositis"],
            )
        ],
        candidate_pmids=[],
    )

    descriptor = response.descriptors[0]

    assert descriptor.name == "Familial Mediterranean Fever"
    assert descriptor.entry_terms == [
        "Periodic Disease",
        "Familial Paroxysmal Polyserositis",
    ]
    assert response.candidate_pmids == []


def test_citation_lookup_response_tracks_statuses_and_candidates() -> None:
    response = CitationLookupResponse(
        records=[
            CitationLookupRecord(
                citation="Ozen et al. Familial Mediterranean fever.",
                status="matched",
                pmid="123",
            ),
            CitationLookupRecord(
                citation="Unknown citation.",
                status="not_found",
            ),
        ],
        candidate_pmids=["123"],
    )

    assert [record.status for record in response.records] == ["matched", "not_found"]
    assert response.candidate_pmids == ["123"]


def test_related_articles_response_deduplicates_candidates_in_caller_order() -> None:
    response = RelatedArticlesResponse(
        records=[
            RelatedArticleRecord(source_pmid="1", related_pmid="10", status="found"),
            RelatedArticleRecord(source_pmid="1", related_pmid="11", status="found"),
            RelatedArticleRecord(source_pmid="2", related_pmid="10", status="found"),
        ],
        candidate_pmids=["10", "11", "10"],
    )

    assert [record.related_pmid for record in response.records] == ["10", "11", "10"]
    assert response.candidate_pmids == ["10", "11"]
