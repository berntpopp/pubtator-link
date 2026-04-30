from pydantic import ValidationError
import pytest

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    IndexReviewEvidenceRequest,
    PreparationStatus,
    RetrieveReviewContextRequest,
    normalize_section,
    passage_id_for_pmid,
)


def test_index_request_rejects_screened_mode() -> None:
    with pytest.raises(ValidationError):
        IndexReviewEvidenceRequest(pmids=["40234174"], prepare_mode="screened")


def test_context_request_defaults_are_poc_values() -> None:
    request = RetrieveReviewContextRequest(question="Should colchicine treat FMF?")

    assert request.max_passages == 8
    assert request.max_chars == 6000
    assert request.max_passages_per_pmid == 2


def test_passage_id_generation_is_deterministic() -> None:
    assert normalize_section("Methods & Results") == "methods_results"
    assert passage_id_for_pmid("40234174", "Methods & Results", 3) == (
        "PMID:40234174:methods_results:3"
    )


def test_context_pack_citation_map_uses_passage_ids() -> None:
    passage = ContextPassage(
        citation_key="S1",
        passage_id="PMID:40234174:abstract:0",
        pmid="40234174",
        section="abstract",
        text="Colchicine should start after clinical diagnosis.",
    )
    pack = ContextPack(
        question="When should colchicine start?",
        passages=[passage],
        citation_map={"S1": "PMID:40234174:abstract:0"},
    )

    assert pack.citation_map["S1"] == pack.passages[0].passage_id


def test_preparation_status_counts_terms() -> None:
    status = PreparationStatus(queued=1, running=2, complete=3, partial=4, failed=5)

    assert status.running == 2
    assert status.partial == 4
