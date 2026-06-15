from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from pubtator_link.mcp.annotations import (
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import (
    EvidenceCertaintyLabel,
    EvidenceCertaintyResponse,
    ListEvidenceCertaintyResponse,
)


def register_evidence_certainty_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        name="add_evidence_certainty",
        title="Add Evidence Certainty",
        output_schema=EvidenceCertaintyResponse.model_json_schema(),
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def add_evidence_certainty(
        review_id: str,
        outcome: str,
        question: str | None = None,
        study_design: str | None = None,
        risk_of_bias_notes: str | None = None,
        inconsistency_notes: str | None = None,
        indirectness_notes: str | None = None,
        imprecision_notes: str | None = None,
        publication_bias_notes: str | None = None,
        overall_certainty: EvidenceCertaintyLabel = "not_rated",
        certainty_rationale: str | None = None,
        passage_ids: list[str] | None = None,
        created_by: str | None = None,
        validate_passages: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs to store a user-supplied GRADE-style evidence certainty judgment linked to prepared passage IDs. The backend stores the judgment; it does not compute certainty."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_evidence_certainty_service()
            return await review_tools.add_evidence_certainty_impl(
                service=service,
                review_id=review_id,
                outcome=outcome,
                question=question,
                study_design=study_design,
                risk_of_bias_notes=risk_of_bias_notes,
                inconsistency_notes=inconsistency_notes,
                indirectness_notes=indirectness_notes,
                imprecision_notes=imprecision_notes,
                publication_bias_notes=publication_bias_notes,
                overall_certainty=overall_certainty,
                certainty_rationale=certainty_rationale,
                passage_ids=passage_ids,
                created_by=created_by,
                validate_passages=validate_passages,
            )

        return await run_mcp_tool("add_evidence_certainty", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="list_evidence_certainty",
        title="List Evidence Certainty",
        output_schema=ListEvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_evidence_certainty(review_id: str) -> dict[str, Any]:
        """Use this when a user needs user-supplied evidence certainty judgments for a review."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_evidence_certainty_service()
            return await review_tools.list_evidence_certainty_impl(
                service=service, review_id=review_id
            )

        return await run_mcp_tool("list_evidence_certainty", call)

    @mcp_tool_for(
        "full",
        "readonly",
        name="get_evidence_certainty",
        title="Get Evidence Certainty",
        output_schema=EvidenceCertaintyResponse.model_json_schema(),
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_evidence_certainty(review_id: str, certainty_id: str) -> dict[str, Any]:
        """Use this when a user needs one user-supplied evidence certainty judgment."""

        async def call() -> dict[str, Any]:
            service = await review_tools.get_review_evidence_certainty_service()
            return await review_tools.get_evidence_certainty_impl(
                service=service,
                review_id=review_id,
                certainty_id=certainty_id,
            )

        return await run_mcp_tool("get_evidence_certainty", call)
