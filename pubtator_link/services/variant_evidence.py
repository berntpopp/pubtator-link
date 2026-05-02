"""Coordinate source-attributed variant database and literature evidence."""

from __future__ import annotations

from typing import Any, Protocol

from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.models.variants import (
    VariantEvidenceRequest,
    VariantEvidenceResponse,
    VariantLiteratureEvidence,
)
from pubtator_link.services.clinvar import ClinVarRecord, ClinVarService

SOURCE_ATTRIBUTION_WARNING = (
    "Classifications are source-attributed; PubTator-Link does not compute clinical significance."
)


class VariantPubTatorClient(Protocol):
    async def search_publications(self, **kwargs: Any) -> dict[str, Any]:
        """Search PubTator publications."""


class VariantMetadataService(Protocol):
    async def get_metadata(self, request: PublicationMetadataRequest) -> Any:
        """Return publication metadata."""


class VariantEvidenceService:
    """Lookup source-attributed ClinVar records and PubTator literature evidence."""

    def __init__(
        self,
        *,
        clinvar: ClinVarService,
        pubtator_client: VariantPubTatorClient,
        metadata_service: VariantMetadataService | None = None,
    ) -> None:
        self.clinvar = clinvar
        self.pubtator_client = pubtator_client
        self.metadata_service = metadata_service

    async def lookup(self, request: VariantEvidenceRequest) -> VariantEvidenceResponse:
        warnings = [SOURCE_ATTRIBUTION_WARNING]
        clinvar_records: list[ClinVarRecord] = []
        variant_terms = _variant_terms(request)

        if "clinvar" in request.sources:
            try:
                clinvar_records = await self.clinvar.lookup(
                    gene=request.gene,
                    variant_terms=variant_terms,
                    condition=request.condition,
                )
            except Exception:
                warnings.append("ClinVar unavailable; returning PubTator literature evidence only.")

        normalized_variants = [record.normalized_variant() for record in clinvar_records]
        source_classifications = [
            record.source_classification() for record in clinvar_records
        ]

        literature: list[VariantLiteratureEvidence] = []
        if "pubtator" in request.sources and request.max_literature_pmids > 0:
            literature = await self._lookup_literature(request, variant_terms, clinvar_records)

        return VariantEvidenceResponse(
            query=request.model_dump(exclude_none=True),
            normalized_variants=normalized_variants,
            source_classifications=source_classifications,
            literature=literature,
            warnings=warnings,
        )

    async def _lookup_literature(
        self,
        request: VariantEvidenceRequest,
        variant_terms: list[str],
        clinvar_records: list[ClinVarRecord],
    ) -> list[VariantLiteratureEvidence]:
        expanded_terms = list(
            dict.fromkeys(
                [
                    *variant_terms,
                    *[
                        hgvs
                        for record in clinvar_records
                        for hgvs in record.hgvs
                    ],
                    *[
                        record.preferred_name
                        for record in clinvar_records
                        if record.preferred_name
                    ],
                ]
            )
        )
        term_query = " OR ".join(f'"{term}"' for term in expanded_terms if term)
        query = f"{request.gene} AND ({term_query})" if term_query else request.gene
        if request.condition:
            query = f"({query}) AND \"{request.condition}\""
        raw = await self.pubtator_client.search_publications(
            text=query,
            page=1,
            sort="score desc",
            filters=None,
        )
        items = list(raw.get("results", []))[: request.max_literature_pmids]
        literature = [
            VariantLiteratureEvidence(
                pmid=str(item.get("pmid", "")),
                title=item.get("title"),
                snippet=item.get("text_hl") or item.get("abstract"),
            )
            for item in items
            if item.get("pmid")
        ]
        if request.include_citations and self.metadata_service is not None and literature:
            metadata_response = await self.metadata_service.get_metadata(
                PublicationMetadataRequest(
                    pmids=[item.pmid for item in literature],
                    include_mesh=False,
                    include_publication_types=True,
                    include_citations="none",
                    include_coverage=True,
                )
            )
            metadata_by_pmid = {
                item.pmid: item for item in getattr(metadata_response, "metadata", [])
            }
            for item in literature:
                item.citation_metadata = metadata_by_pmid.get(item.pmid)
        return literature


def _variant_terms(request: VariantEvidenceRequest) -> list[str]:
    return [term for term in (request.variant, request.protein) if term]
