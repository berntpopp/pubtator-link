from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.client import PubTator3Client
from pubtator_link.api.routes.dependencies import get_publication_passage_service
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.errors import run_mcp_tool
from pubtator_link.mcp.service_adapters import (
    estimate_publication_context_impl,
    fetch_pmc_annotations_impl,
    fetch_publication_annotations_impl,
    get_publication_passages_impl,
)
from pubtator_link.models.publication_passages import PublicationPassageMode
from pubtator_link.services.publication_service import PublicationService


def register_publication_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.fetch_publication_annotations",
        title="Fetch Publication Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_publication_annotations(
        pmids: Annotated[list[str], Field(min_length=1, max_length=50)],
        format: Literal["pubtator", "biocxml", "biocjson"] = "biocjson",
        full: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user provides PubMed IDs and needs raw PubTator BioC/annotation export; prefer compact passage or review context tools for grounded answers because full BioC can be large. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async def call() -> dict[str, Any]:
            async with PubTator3Client() as client:
                service = PublicationService(client=client)
                return await fetch_publication_annotations_impl(
                    service=service,
                    pmids=pmids,
                    format=format,
                    full=full,
                )

        return await run_mcp_tool("pubtator.fetch_publication_annotations", call, pmids=pmids)

    @mcp.tool(
        name="pubtator.get_publication_passages",
        title="Get Publication Passages",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def get_publication_passages(
        pmids: list[str],
        sections: list[str] | None = None,
        mode: PublicationPassageMode = "compact_passages",
        full: bool = False,
        max_passages_per_pmid: int = 6,
        max_chars: int = 12000,
        include_tables: bool = True,
        include_references: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs compact citable publication passages from PMIDs without raw BioC. Prefer this over raw annotation export for routine grounding. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async def call() -> dict[str, Any]:
            service = await get_publication_passage_service()
            return await get_publication_passages_impl(
                service=service,
                pmids=pmids,
                sections=sections,
                mode=mode,
                full=full,
                max_passages_per_pmid=max_passages_per_pmid,
                max_chars=max_chars,
                include_tables=include_tables,
                include_references=include_references,
            )

        return await run_mcp_tool("pubtator.get_publication_passages", call, pmids=pmids)

    @mcp.tool(
        name="pubtator.estimate_publication_context",
        title="Estimate Publication Context",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def estimate_publication_context(
        pmids: Annotated[list[str], Field(min_length=1, max_length=25)],
        sections: list[str] | None = None,
        mode: PublicationPassageMode = "compact_passages",
        full: bool = False,
        max_passages_per_pmid: Annotated[int, Field(ge=1, le=30)] = 6,
        include_tables: bool = True,
        include_references: bool = False,
    ) -> dict[str, Any]:
        """Use this when a user needs to estimate passage count and context size before fetching publication passages. Inputs mirror get_publication_passages except max_chars; output includes estimated_passages, estimated_chars, sections_by_pmid, recommended_mode, and warning. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async def call() -> dict[str, Any]:
            service = await get_publication_passage_service()
            return await estimate_publication_context_impl(
                service=service,
                pmids=pmids,
                sections=sections,
                mode=mode,
                full=full,
                max_passages_per_pmid=max_passages_per_pmid,
                include_tables=include_tables,
                include_references=include_references,
            )

        return await run_mcp_tool("pubtator.estimate_publication_context", call, pmids=pmids)

    @mcp.tool(
        name="pubtator.fetch_pmc_annotations",
        title="Fetch PMC Annotations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def fetch_pmc_annotations(
        pmcids: Annotated[list[str], Field(min_length=1, max_length=50)],
        format: Literal["biocxml", "biocjson"] = "biocjson",
    ) -> dict[str, Any]:
        """Use this when a user provides PMC IDs and needs raw PubTator full-text BioC/annotation export; prefer compact passage or review context tools for focused grounding because full text can be large. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async def call() -> dict[str, Any]:
            async with PubTator3Client() as client:
                service = PublicationService(client=client)
                return await fetch_pmc_annotations_impl(
                    service=service,
                    pmcids=pmcids,
                    format=format,
                )

        return await run_mcp_tool("pubtator.fetch_pmc_annotations", call)
