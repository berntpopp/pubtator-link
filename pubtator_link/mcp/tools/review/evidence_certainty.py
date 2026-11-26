from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import HTTPException
from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.mcp.annotations import (
    NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    READ_ONLY_OPEN_WORLD,
)
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.mcp.tools import review as review_tools
from pubtator_link.mcp.tools.review._helpers import make_mcp_tool_for
from pubtator_link.models.review_rerag import EvidenceCertaintyLabel


def register_evidence_certainty_tools(mcp: FastMCP, profile: MCPToolProfile) -> None:
    mcp_tool_for = make_mcp_tool_for(mcp, profile)

    @mcp_tool_for(
        "full",
        name="add_evidence_certainty",
        title="Add Evidence Certainty",
        output_schema=None,
        annotations=NON_IDEMPOTENT_REVIEW_WRITE_ANNOTATIONS,
    )
    async def add_evidence_certainty(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review this certainty judgment belongs to.",
                examples=["demo"],
            ),
        ],
        outcome: Annotated[
            str,
            Field(
                min_length=1,
                description="The clinical/research outcome the judgment is about.",
                examples=["overall survival"],
            ),
        ],
        question: Annotated[
            str | None,
            Field(description="Optional PICO-style question the outcome answers."),
        ] = None,
        study_design: Annotated[
            str | None,
            Field(description="Study design of the underlying evidence, e.g. 'RCT'."),
        ] = None,
        risk_of_bias_notes: Annotated[
            str | None, Field(description="GRADE risk-of-bias notes.")
        ] = None,
        inconsistency_notes: Annotated[
            str | None, Field(description="GRADE inconsistency notes.")
        ] = None,
        indirectness_notes: Annotated[
            str | None, Field(description="GRADE indirectness notes.")
        ] = None,
        imprecision_notes: Annotated[
            str | None, Field(description="GRADE imprecision notes.")
        ] = None,
        publication_bias_notes: Annotated[
            str | None, Field(description="GRADE publication-bias notes.")
        ] = None,
        overall_certainty: Annotated[
            EvidenceCertaintyLabel,
            Field(
                description=(
                    "Overall GRADE certainty: 'high', 'moderate', 'low', 'very_low', or "
                    "'not_rated' (default)."
                ),
            ),
        ] = "not_rated",
        certainty_rationale: Annotated[
            str | None, Field(description="Free-text rationale for the overall certainty.")
        ] = None,
        passage_ids: Annotated[
            list[str] | None,
            Field(
                description="Prepared passage IDs this judgment is grounded in.",
                examples=[["p1", "p2"]],
            ),
        ] = None,
        created_by: Annotated[
            str | None, Field(description="Attribution for the curator making the judgment.")
        ] = None,
        validate_passages: Annotated[
            bool,
            Field(description="Verify the passage_ids exist in the review index before storing."),
        ] = False,
    ) -> dict[str, Any]:
        """Use this when a user needs to store a user-supplied GRADE-style evidence certainty judgment linked to prepared passage IDs; returns the stored judgment record. The backend stores the judgment; it does not compute certainty."""

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
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def list_evidence_certainty(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review whose stored certainty judgments to list.",
                examples=["demo"],
            ),
        ],
    ) -> dict[str, Any]:
        """Use this when a user needs user-supplied evidence certainty judgments for a review; returns the stored judgments for that review."""

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
        output_schema=None,
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_evidence_certainty(
        review_id: Annotated[
            str,
            Field(
                min_length=1,
                description="Review the certainty judgment belongs to.",
                examples=["demo"],
            ),
        ],
        certainty_id: Annotated[
            str,
            Field(
                min_length=1,
                description="UUID of the stored certainty judgment.",
                examples=["3f2b8c1e-5d47-4a9b-8c21-6e0f4d2a9b17"],
            ),
        ],
    ) -> dict[str, Any]:
        """Use this when a user needs one user-supplied evidence certainty judgment: returns that judgment with its linked passage IDs."""

        async def call() -> dict[str, Any]:
            # Fixed message only; the caller-supplied id is never echoed back.
            not_found = {
                "success": False,
                "error_code": "not_found",
                "message": "Evidence certainty record not found.",
                "retryable": False,
            }
            try:
                UUID(certainty_id)  # stored ids are UUIDs; any other string cannot exist
            except ValueError:
                return not_found
            service = await review_tools.get_review_evidence_certainty_service()
            try:
                return await review_tools.get_evidence_certainty_impl(
                    service=service,
                    review_id=review_id,
                    certainty_id=certainty_id,
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
                return not_found

        return await run_mcp_tool("get_evidence_certainty", call)
