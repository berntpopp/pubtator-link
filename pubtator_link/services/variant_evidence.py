"""Coordinate source-attributed variant database and literature evidence."""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol

from pubtator_link.models.publication_metadata import PublicationMetadataRequest
from pubtator_link.models.variants import (
    CandidateVariant,
    VariantEvidenceRequest,
    VariantEvidenceResponse,
    VariantLiteratureEvidence,
)
from pubtator_link.services.clinvar import ClinVarRecord, ClinVarService

SOURCE_ATTRIBUTION_WARNING = (
    "Classifications are source-attributed; PubTator-Link does not compute clinical significance."
)
_TRANSCRIPT_PREFIX = re.compile(
    r"^(?:N[MRP]_[0-9]+(?:\.[0-9]+)?|NC_[0-9]+(?:\.[0-9]+)?|"
    r"NG_[0-9]+(?:\.[0-9]+)?|ENST[0-9]+(?:\.[0-9]+)?|LRG_[0-9]+(?:t[0-9]+)?)(?:\([^)]+\))?:",
    flags=re.IGNORECASE,
)


class VariantPubTatorClient(Protocol):
    async def search_publications(
        self,
        text: str,
        page: int = 1,
        sort: str | None = None,
        filters: str | None = None,
        sections: str | None = None,
    ) -> dict[str, Any]:
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

        authoritative_records: list[ClinVarRecord] = []
        normalized_variants = []
        source_classifications = []
        candidate_variants: list[CandidateVariant] = []
        for record in clinvar_records:
            match_confidence = _match_confidence(record, variant_terms)
            if match_confidence is None:
                candidate_variants.append(
                    CandidateVariant(
                        source="clinvar",
                        name=record.preferred_name or record.variation_id,
                        variation_id=record.variation_id,
                        allele_id=record.allele_id,
                        hgvs=record.hgvs,
                        url=record.url,
                        classification=record.classification,
                        review_status=record.review_status,
                        condition=record.condition,
                        last_evaluated=record.last_evaluated,
                    )
                )
                continue
            authoritative_records.append(record)
            normalized_variants.append(
                record.normalized_variant().model_copy(
                    update={"match_confidence": match_confidence}
                )
            )
            source_classifications.append(
                record.source_classification().model_copy(
                    update={"match_confidence": match_confidence}
                )
            )
        if candidate_variants:
            warnings.append(
                "ClinVar records in candidate_variants are broad gene-search candidates, not evidence "
                "for the requested variant."
            )

        literature: list[VariantLiteratureEvidence] = []
        if "pubtator" in request.sources and request.max_literature_pmids > 0:
            literature = await self._lookup_literature(
                request, variant_terms, authoritative_records
            )

        return VariantEvidenceResponse(
            query=request.model_dump(exclude_none=True),
            normalized_variants=normalized_variants,
            source_classifications=source_classifications,
            candidate_variants=candidate_variants,
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
                    *[hgvs for record in clinvar_records for hgvs in record.hgvs],
                    *[record.preferred_name for record in clinvar_records if record.preferred_name],
                ]
            )
        )
        term_query = " OR ".join(f'"{term}"' for term in expanded_terms if term)
        query = f"{request.gene} AND ({term_query})" if term_query else request.gene
        if request.condition:
            query = f'({query}) AND "{request.condition}"'
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


def _normalized_expression(value: str) -> str:
    """Normalize case and whitespace while retaining transcript identity."""

    return "".join(value.casefold().split())


def _canonical_expression(value: str) -> str:
    """Return a transcript-agnostic expression for explicit equivalence checks."""

    normalized = _normalized_expression(value)
    return _TRANSCRIPT_PREFIX.sub("", normalized, count=1)


def _match_confidence(
    record: ClinVarRecord, variant_terms: list[str]
) -> Literal["exact", "equivalent"] | None:
    """Return a safe canonical match for a ClinVar record.

    Exact matches retain the transcript identifier after normalising case and
    whitespace.  Transcript-free canonical equality is labelled ``equivalent``
    rather than ``exact``.  No biological equivalence is inferred: a shared
    prefix such as ``p.Cys61Gly`` and ``p.Cys61GlyfsTer12`` is not a match.
    """

    requested = {_normalized_expression(term) for term in variant_terms}
    record_hgvs = {_normalized_expression(value) for value in record.hgvs}
    if requested & record_hgvs:
        return "exact"
    requested_canonical = {_canonical_expression(term) for term in variant_terms}
    record_canonical = {_canonical_expression(value) for value in record.hgvs}
    if requested_canonical & record_canonical:
        return "equivalent"
    return None
