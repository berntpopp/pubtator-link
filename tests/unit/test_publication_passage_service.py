import pytest
from pydantic import ValidationError

from pubtator_link.models.publication_passages import (
    PublicationContextEstimateRequest,
    PublicationPassageRequest,
)
from pubtator_link.models.responses import PublicationExportResponse
from pubtator_link.services.degradation import degraded_mode_from_coverage
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


class LongStructuredAbstractService:
    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        return {
            "documents": [
                {
                    "id": "15053041",
                    "passages": [
                        {"infons": {"section_type": "TITLE"}, "text": "Aortic stiffness title"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Background"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Methods"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Results"},
                        {"infons": {"section_type": "ABSTRACT"}, "text": "Conclusion"},
                        {"infons": {"section_type": "METHODS"}, "text": "Full text methods"},
                    ],
                }
            ]
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


def test_degraded_mode_from_coverage_prefers_most_severe_mode() -> None:
    assert degraded_mode_from_coverage({"1": "full_text", "2": "abstract_only"}) == "abstract_only"
    assert degraded_mode_from_coverage({"1": "title_only", "2": "abstract_only"}) == "metadata_only"
    assert degraded_mode_from_coverage({"1": "full_text"}) is None
    assert degraded_mode_from_coverage({}) is None


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

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], mode="abstracts")
    )

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
async def test_publication_passages_unescapes_html_entities() -> None:
    class HtmlEntityPublicationService:
        async def export_publications_list(self, pmids: list[str], format: str, full: bool):
            return {
                "documents": [
                    {
                        "id": "11978239",
                        "passages": [
                            {
                                "infons": {"section_type": "ABSTRACT"},
                                "text": "p &lt; 0.05 and CRP &amp; fibrinogen improved.",
                            }
                        ],
                    }
                ]
            }

    service = PublicationPassageService(HtmlEntityPublicationService())
    response = await service.get_passages(PublicationPassageRequest(pmids=["11978239"]))

    assert response.passages[0].text == "p < 0.05 and CRP & fibrinogen improved."


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
async def test_get_passages_sets_degraded_mode_for_abstract_only_response() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], mode="abstracts")
    )

    assert response.coverage_by_pmid == {"111": "abstract_only"}
    assert response.degraded_mode == "abstract_only"


@pytest.mark.asyncio
async def test_get_passages_dry_run_returns_estimate_without_text() -> None:
    service = PublicationPassageService(FakePublicationService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=["111"], dry_run=True, full=True)
    )

    assert response.dry_run is True
    assert response.passages == []
    assert response.context_estimate.estimated_passages > 0
    assert response.context_estimate.estimated_chars > 0


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
async def test_full_abstract_mode_returns_all_title_and_abstract_passages() -> None:
    service = PublicationPassageService(LongStructuredAbstractService())

    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["15053041"],
            mode="full_abstract",
            max_passages_per_pmid=2,
        )
    )

    assert [passage.text for passage in response.passages] == [
        "Aortic stiffness title",
        "Background",
        "Methods",
        "Results",
        "Conclusion",
    ]
    assert all(passage.section in {"title", "abstract"} for passage in response.passages)
    assert not any(drop.reason == "max_passages_per_pmid_exceeded" for drop in response.dropped)
    assert any(
        drop.reason == "section_filtered" and drop.section == "methods" for drop in response.dropped
    )
    assert response.context_estimate.recommended_mode == "full_abstract"


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


class BiocjsonGapService:
    """PubTator3 biocjson 400s (single) or silently drops (batch) PMID 39156164 (#247)."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str]] = []

    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        from pubtator_link.api.client import PubTatorAPIError

        self.calls.append((pmids, format))
        if format == "pubtator":
            docs = []
            for pmid in pmids:
                if pmid == "39156164":
                    docs.append({"pmid": pmid, "sections": {"t": "HNF1B title"}})
                    docs.append({"pmid": pmid, "sections": {"a": "HNF1B abstract"}})
            return {"export_data": {"documents": docs}}
        if pmids == ["39156164"]:
            raise PubTatorAPIError("PubTator3 API returned HTTP 400.", status_code=400)
        return {
            "documents": [
                {
                    "id": "42739594",
                    "passages": [{"infons": {"type": "abstract"}, "text": "Greek cohort"}],
                }
            ]
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("pmids", [["39156164"], ["39156164", "42739594"]])
async def test_biocjson_gap_falls_back_to_pubtator_abstract(pmids: list[str]) -> None:
    service = PublicationPassageService(BiocjsonGapService())

    response = await service.get_passages(
        PublicationPassageRequest(pmids=pmids, mode="full_abstract")
    )

    assert response.success is True
    fallback = [p for p in response.passages if p.pmid == "39156164"]
    assert [p.text for p in fallback] == ["HNF1B title", "HNF1B abstract"]
    assert {p.source for p in fallback} == {"pubtator_abstract"}
    assert response.coverage_by_pmid["39156164"] == "abstract_only"
    assert response.coverage_reason_by_pmid["39156164"] == "biocjson_unavailable_pubtator_fallback"


@pytest.mark.asyncio
async def test_pmid_missing_from_both_exports_is_not_retrievable() -> None:
    class EmptyService:
        async def export_publications_list(self, pmids, format, full):
            return {"documents": []}

    response = await PublicationPassageService(EmptyService()).get_passages(
        PublicationPassageRequest(pmids=["1"])
    )

    assert response.coverage_by_pmid["1"] == "unknown"
    assert response.coverage_reason_by_pmid["1"] == "not_retrievable"


class ResultsAndTablesService:
    """Full text where RESULTS precede TABLE passages (#244)."""

    async def export_publications_list(self, pmids: list[str], format: str, full: bool):
        passages = [{"infons": {"section_type": "RESULTS"}, "text": f"R{i}"} for i in range(8)]
        passages += [{"infons": {"section_type": "TABLE"}, "text": f"T{i}"} for i in range(4)]
        passages += [{"infons": {"section_type": "REF"}, "text": f"ref{i}"} for i in range(5)]
        return {"documents": [{"id": "34622103", "passages": passages}]}


@pytest.mark.asyncio
async def test_explicit_sections_cap_per_section_so_tables_are_not_starved() -> None:
    service = PublicationPassageService(ResultsAndTablesService())

    response = await service.get_passages(
        PublicationPassageRequest(
            pmids=["34622103"], full=True, sections=["RESULTS", "TABLE"], max_passages_per_pmid=3
        )
    )

    texts = [p.text for p in response.passages]
    assert texts == ["R0", "R1", "R2", "T0", "T1", "T2"]
    assert response.truncated_sections == ["results", "table"]
    assert response.dropped_summary == {
        "max_passages_per_pmid_exceeded": {"results": 5, "table": 1},
        "reference_excluded": {"references": 5},
    }


@pytest.mark.asyncio
async def test_mcp_dump_lists_individual_drops_only_at_full_verbosity() -> None:
    service = PublicationPassageService(ResultsAndTablesService())
    request = PublicationPassageRequest(pmids=["34622103"], full=True, max_passages_per_pmid=2)

    standard = (await service.get_passages(request)).model_dump_mcp()
    full = (await service.get_passages(request)).model_dump_mcp(verbosity="full")

    assert standard["dropped"] == []
    assert standard["dropped_summary"]["max_passages_per_pmid_exceeded"] == {
        "results": 6,
        "table": 4,
    }
    assert len(full["dropped"]) == 15
