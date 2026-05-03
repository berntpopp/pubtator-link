from __future__ import annotations

from jsonschema import validate

from pubtator_link.models.review_rerag import (
    ContextPack,
    ContextPassage,
    GroundingConfidence,
    PreparationStatus,
    RetrieveReviewContextBatchResponse,
    ReviewBatchResponseMode,
)


def test_retrieve_review_context_batch_response_modes_match_output_schema() -> None:
    modes: tuple[ReviewBatchResponseMode, ...] = (
        "compact",
        "merged_only",
        "full",
        "diagnostics",
        "quotes",
    )

    for mode in modes:
        response = RetrieveReviewContextBatchResponse(
            review_id="review-1",
            response_mode=mode,
            merged_context_pack=ContextPack(
                question="MEFV colchicine recommendation",
                passages=[
                    ContextPassage(
                        citation_key="S1",
                        passage_id="PMID:1:abstract:0",
                        pmid="1",
                        section="abstract",
                        text="EULAR recommendations state that colchicine should be started after clinical diagnosis.",
                        confidence_for_grounding=GroundingConfidence(
                            level="high",
                            score=0.9,
                            factors={"lexical_match": 1.0},
                            explanation="High lexical match in a recommendation-bearing passage.",
                        ),
                    )
                ],
                citation_map={"S1": "PMID:1:abstract:0"},
            ),
            preparation_status=PreparationStatus(complete=1),
        )

        validate(
            instance=response.model_dump(mode="json"),
            schema=RetrieveReviewContextBatchResponse.model_json_schema(),
        )
