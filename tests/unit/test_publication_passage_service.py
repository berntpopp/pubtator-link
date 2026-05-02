import pytest
from pydantic import ValidationError

from pubtator_link.models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationPassageRequest,
)
from pubtator_link.models.responses import PublicationExportResponse
from pubtator_link.services.publication_passage_service import PublicationPassageService


class FakePublicationService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "export_data": {
                "documents": [
                    {
                        "id": "111",
                        "infons": {"pmcid": "PMC111"},
                        "passages": [
                            {"infons": {"section_type": "TITLE"}, "text": "Trial title"},
                            {"infons": {"section_type": "ABSTRACT"}, "text": "Abstract text"},
                            {"infons": {"section_type": "METHODS"}, "text": "Methods text"},
                            {"infons": {"section_type": "TABLE"}, "text": "Table text"},
                            {"infons": {"section_type": "REF"}, "text": "Reference text"},
                        ],
                    }
                ]
            }
        }


class AliasPublicationService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "export_data": {
                "documents": [
                    {
                        "id": "222",
                        "passages": [
                            {"infons": {"section_type": "ABSTR"}, "text": "Alias abstract"},
                            {"infons": {"section_type": "DISCUSS"}, "text": "Discussion"},
                            {"infons": {"section_type": "CONCL"}, "text": "Conclusion"},
                            {"infons": {"section_type": "references"}, "text": "Reference"},
                        ],
                    }
                ]
            }
        }


class LongPublicationService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "export_data": {
                "documents": [
                    {
                        "id": "333",
                        "passages": [
                            {"infons": {"section_type": "TITLE"}, "text": "A" * 400},
                            {"infons": {"section_type": "ABSTRACT"}, "text": "B" * 500},
                            {"infons": {"section_type": "METHODS"}, "text": "C" * 300},
                        ],
                    }
                ]
            }
        }


class RaisingPublicationService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        raise RuntimeError("upstream unavailable")


class ModelDumpPublicationService:
    async def export_publications_list(
        self, pmids: list[str], format: str, full: bool
    ) -> PublicationExportResponse:
        return PublicationExportResponse(
            format=format,
            pmids=pmids,
            full_text=full,
            export_data={
                "documents": [
                    {
                        "id": "444",
                        "passages": [
                            {
                                "infons": {"section_type": "ABSTRACT"},
                                "text": "Model response abstract",
                            }
                        ],
                    }
                ]
            },
            count=1,
        )


@pytest.mark.asyncio
async def test_get_publication_passages_filters_sections_and_references() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], sections=["abstract", "table"])
    )

    assert response.success is True
    assert [passage.section for passage in response.passages] == ["abstract", "table"]
    assert [passage.text for passage in response.passages] == ["Abstract text", "Table text"]
    assert response.passages[0].passage_id == "PMID:111:abstract:0"
    assert response.passages[0].source == "pubtator_abstract"
    assert "documents" not in response.model_dump()
    assert {drop.reason for drop in response.dropped} >= {"section_filtered", "reference_excluded"}


@pytest.mark.asyncio
async def test_get_publication_passages_enforces_char_budget_without_truncation() -> None:
    service = PublicationPassageService(LongPublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["333"], max_chars=1000, max_passages_per_pmid=10)
    )

    assert [passage.char_count for passage in response.passages] == [400, 500]
    assert [len(passage.text) for passage in response.passages] == [400, 500]
    assert any(drop.reason == "char_budget_exceeded" for drop in response.dropped)


@pytest.mark.asyncio
async def test_get_publication_passages_excludes_tables_when_requested() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], include_tables=False, max_passages_per_pmid=10)
    )

    assert "table" not in [passage.section for passage in response.passages]
    assert any(drop.reason == "table_excluded" for drop in response.dropped)


@pytest.mark.asyncio
async def test_get_publication_passages_normalizes_aliases_and_section_filters() -> None:
    service = PublicationPassageService(AliasPublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["222"],
            sections=["ABSTRACT", "discussion", "Conclusion", "REFERENCES"],
            include_references=True,
            max_passages_per_pmid=10,
        )
    )

    assert [passage.section for passage in response.passages] == [
        "abstract",
        "discussion",
        "conclusion",
        "references",
    ]
    assert response.passages[0].passage_id == "PMID:222:abstract:0"


@pytest.mark.asyncio
async def test_get_publication_passages_enforces_per_pmid_limit() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], max_passages_per_pmid=2)
    )

    assert [passage.text for passage in response.passages] == ["Trial title", "Abstract text"]
    assert any(drop.reason == "max_passages_per_pmid_exceeded" for drop in response.dropped)


@pytest.mark.asyncio
async def test_get_publication_passages_reports_upstream_errors() -> None:
    service = PublicationPassageService(RaisingPublicationService())

    response = await service.get_passages(PublicationPassageRequest(pmids=["111"]))

    assert response.success is False
    assert response.passages == []
    assert [drop.reason for drop in response.dropped] == ["upstream_error"]


@pytest.mark.asyncio
async def test_get_publication_passages_accepts_export_response_models() -> None:
    service = PublicationPassageService(ModelDumpPublicationService())

    response = await service.get_passages(PublicationPassageRequest(pmids=["444"]))

    assert response.success is True
    assert [passage.text for passage in response.passages] == ["Model response abstract"]
    assert response.passages[0].passage_id == "PMID:444:abstract:0"


@pytest.mark.asyncio
async def test_section_text_warns_when_only_abstract_passages_returned() -> None:
    class AbstractOnlyPublicationService:
        async def export_publications_list(self, pmids, format, full):
            return {
                "documents": [
                    {
                        "id": "39540697",
                        "passages": [
                            {"infons": {"section_type": "title"}, "text": "FMF in Childhood"},
                            {"infons": {"section_type": "abstract"}, "text": "FMF is common."},
                        ],
                    }
                ]
            }

    service = PublicationPassageService(AbstractOnlyPublicationService())
    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["39540697"],
            mode="section_text",
            full=True,
            max_passages_per_pmid=5,
        )
    )

    assert response.coverage_by_pmid["39540697"] == "abstract_only"
    assert response.failed_pmids == []
    assert any("No full-text section passages" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_publication_passages_reports_failed_pmids() -> None:
    class EmptyPublicationService:
        async def export_publications_list(self, pmids, format, full):
            return {"documents": []}

    service = PublicationPassageService(EmptyPublicationService())
    response = await service.get_passages(PublicationPassageRequest(pmids=["1"]))

    assert response.coverage_by_pmid["1"] == "unknown"
    assert response.failed_pmids[0].pmid == "1"
    assert response.failed_pmids[0].reason == "No PubTator passages found"


@pytest.mark.asyncio
async def test_abstracts_mode_returns_only_title_and_abstract_passages() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["111"],
            mode="abstracts",
            max_passages_per_pmid=10,
        )
    )

    assert [passage.section for passage in response.passages] == ["title", "abstract"]
    assert any(
        drop.reason == "section_filtered" and drop.section == "methods" for drop in response.dropped
    )
    assert any(
        drop.reason == "section_filtered" and drop.section == "table" for drop in response.dropped
    )


@pytest.mark.asyncio
async def test_abstracts_mode_estimate_counts_only_title_and_abstract() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.estimate_context(
        PublicationContextEstimateRequest(
            pmids=["111"],
            mode="abstracts",
            max_passages_per_pmid=10,
        )
    )

    assert response.estimated_passages == 2
    assert response.sections_by_pmid["111"] == ["title", "abstract"]


@pytest.mark.asyncio
async def test_estimate_publication_context_counts_sections_and_warns_large_output() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.estimate_context(
        PublicationContextEstimateRequest(pmids=["111"], full=True)
    )

    assert response.success is True
    assert response.estimated_passages == 4
    assert response.sections_by_pmid["111"] == ["title", "abstract", "methods", "table"]
    assert response.recommended_mode == "compact_passages"
    assert response.warning is not None


def test_publication_passage_request_constraints() -> None:
    with pytest.raises(ValidationError):
        PublicationPassageRequest(pmids=[])
    with pytest.raises(ValidationError):
        PublicationPassageRequest(pmids=[str(index) for index in range(26)])
    with pytest.raises(ValidationError):
        PublicationPassageRequest(pmids=["111"], max_passages_per_pmid=31)
    with pytest.raises(ValidationError):
        PublicationPassageRequest(pmids=["111"], max_chars=999)

    request = PublicationPassageRequest(pmids=["111"])

    assert request.mode == "compact_passages"
    assert request.full is False
    assert request.include_tables is True
    assert request.include_references is False
