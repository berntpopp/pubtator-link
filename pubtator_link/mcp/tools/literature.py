from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from pubtator_link.api.client import PubTator3Client
from pubtator_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from pubtator_link.mcp.service_adapters import (
    find_entity_relations_impl,
    search_biomedical_entities_impl,
    search_literature_impl,
)


def register_literature_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pubtator.search_literature",
        title="Search Biomedical Literature",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_literature(
        text: str,
        page: int = 1,
        sort: str | None = None,
        filters: str | None = None,
        publication_types: list[str] | None = None,
        year_min: int | None = None,
        year_max: int | None = None,
        sections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Use this when a user needs PubMed literature search through PubTator3. Use short biomedical queries, optional sort such as 'score desc' or 'date desc', flat publication/year filters, raw filters JSON, and optional section filters. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_literature_impl(
                client=client,
                text=text,
                page=page,
                sort=sort,
                filters=filters,
                publication_types=publication_types,
                year_min=year_min,
                year_max=year_max,
                sections=sections,
            )

    @mcp.tool(
        name="pubtator.search_biomedical_entities",
        title="Search Biomedical Entities",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def search_biomedical_entities(
        query: str,
        concept: Literal["Gene", "Disease", "Chemical", "Species", "Variant", "CellLine"]
        | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Use this when a user needs canonical PubTator biomedical entity IDs for genes, diseases, chemicals, species, variants, or cell lines. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await search_biomedical_entities_impl(
                client=client,
                query=query,
                concept=concept,
                limit=limit,
            )

    @mcp.tool(
        name="pubtator.find_entity_relations",
        title="Find Entity Relations",
        annotations=READ_ONLY_OPEN_WORLD,
    )
    async def find_entity_relations(
        entity_id: Annotated[
            str,
            Field(min_length=1, description="PubTator entity ID such as @CHEMICAL_remdesivir."),
        ],
        relation_type: str | None = None,
        target_entity_type: str | None = None,
    ) -> dict[str, Any]:
        """Use this when a user has a PubTator entity ID and needs literature-derived related entities to expand a corpus after search_biomedical_entities. Research use only; not for diagnosis, treatment, triage, patient management, or clinical decision support."""
        async with PubTator3Client() as client:
            return await find_entity_relations_impl(
                client=client,
                entity_id=entity_id,
                relation_type=relation_type,
                target_entity_type=target_entity_type,
            )
