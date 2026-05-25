from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pubtator_link.models.discovery import (
    CitationLookupRecord,
    DiscoveryMeta,
    RelatedArticleRecord,
    RelatedMetadataStatus,
)
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)


class DiscoveryMetadataLookup(Protocol):
    async def get_metadata(
        self,
        request: PublicationMetadataRequest,
    ) -> PublicationMetadataResponse: ...


async def enrich_citation_records(
    records: Sequence[CitationLookupRecord],
    metadata_service: DiscoveryMetadataLookup | None,
) -> list[CitationLookupRecord]:
    metadata_by_pmid = await _metadata_by_pmid(
        [record.pmid for record in records if record.status == "matched" and record.pmid],
        metadata_service,
    )
    if not metadata_by_pmid:
        return list(records)
    return [
        _enriched_citation_record(record, metadata_by_pmid.get(record.pmid or ""))
        for record in records
    ]


async def enrich_related_article_records(
    records: Sequence[RelatedArticleRecord],
    metadata_service: DiscoveryMetadataLookup | None,
) -> tuple[list[RelatedArticleRecord], RelatedMetadataStatus]:
    if not records:
        return [], "success"
    if metadata_service is None:
        return list(records), "unavailable"
    metadata_by_pmid = await _metadata_by_pmid(
        [record.pmid for record in records],
        metadata_service,
    )
    if not metadata_by_pmid:
        return list(records), "unavailable"
    enriched = [
        _enriched_related_article_record(record, metadata_by_pmid.get(record.pmid))
        for record in records
    ]
    expected_pmids = {record.pmid for record in records}
    status: RelatedMetadataStatus = (
        "success" if expected_pmids.issubset(metadata_by_pmid) else "partial"
    )
    return enriched, status


def add_related_metadata_next_command(
    meta: DiscoveryMeta,
    candidate_pmids: list[str],
    metadata_status: RelatedMetadataStatus,
) -> DiscoveryMeta:
    if candidate_pmids and metadata_status in {"partial", "unavailable"}:
        meta.next_commands.append(
            {
                "tool": "pubtator_get_publication_metadata",
                "arguments": {"pmids": candidate_pmids},
            }
        )
    return meta


async def _metadata_by_pmid(
    pmids: Sequence[str | None],
    metadata_service: DiscoveryMetadataLookup | None,
) -> dict[str, PublicationMetadata]:
    selected_pmids = [pmid for pmid in dict.fromkeys(pmids) if pmid]
    if not selected_pmids or metadata_service is None:
        return {}
    response = await metadata_service.get_metadata(
        PublicationMetadataRequest(
            pmids=selected_pmids,
            include_mesh=False,
            include_publication_types=False,
            include_citations="none",
            include_coverage=False,
        )
    )
    return {item.pmid: item for item in response.metadata}


def _enriched_citation_record(
    record: CitationLookupRecord,
    metadata: PublicationMetadata | None,
) -> CitationLookupRecord:
    if metadata is None:
        return record
    authors = [author.display_name for author in metadata.authors if author.display_name]
    return record.model_copy(
        update={
            "title": metadata.title or record.title,
            "journal": metadata.journal or record.journal,
            "year": metadata.pub_year or record.year,
            "authors": authors or record.authors,
        }
    )


def _enriched_related_article_record(
    record: RelatedArticleRecord,
    metadata: PublicationMetadata | None,
) -> RelatedArticleRecord:
    if metadata is None:
        return record
    return record.model_copy(
        update={
            "title": metadata.title or record.title,
            "journal": metadata.journal or record.journal,
            "year": metadata.pub_year or record.year,
        }
    )
