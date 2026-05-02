from __future__ import annotations

import pytest

from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.models.variants import VariantEvidenceRequest
from pubtator_link.services.clinvar import ClinVarRecord
from pubtator_link.services.variant_evidence import VariantEvidenceService


class FakeClinVarService:
    async def lookup(self, *, gene: str, variant_terms: list[str], condition: str | None = None):
        return [
            ClinVarRecord(
                variation_id="12345",
                allele_id="67890",
                preferred_name="MEFV c.2177T>C",
                hgvs=["NM_000243.3:c.2177T>C"],
                classification="Pathogenic",
                review_status="criteria provided",
                condition="Familial Mediterranean fever",
                url="https://www.ncbi.nlm.nih.gov/clinvar/variation/12345/",
            )
        ]


class FailingClinVarService:
    async def lookup(self, *, gene: str, variant_terms: list[str], condition: str | None = None):
        raise RuntimeError("ClinVar down")


class FakePubTatorClient:
    async def search_publications(self, **kwargs):
        return {
            "results": [
                {
                    "pmid": "12345678",
                    "title": "Variant paper",
                    "text_hl": "MEFV c.2177T>C evidence",
                }
            ]
        }


class FakePublicationMetadataService:
    async def get_metadata(self, request):
        return PublicationMetadataResponse(
            metadata=[PublicationMetadata(pmid="12345678", title="Variant paper")],
            _meta={"next_commands": []},
        )


@pytest.mark.asyncio
async def test_lookup_variant_evidence_combines_clinvar_and_literature() -> None:
    service = VariantEvidenceService(
        clinvar=FakeClinVarService(),
        pubtator_client=FakePubTatorClient(),
        metadata_service=FakePublicationMetadataService(),
    )

    response = await service.lookup(VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C"))

    assert response.normalized_variants[0].source == "clinvar"
    assert response.source_classifications[0].classification == "Pathogenic"
    assert response.literature[0].pmid == "12345678"
    assert response.literature[0].citation_metadata.title == "Variant paper"


@pytest.mark.asyncio
async def test_clinvar_failure_returns_pubtator_partial_success() -> None:
    service = VariantEvidenceService(
        clinvar=FailingClinVarService(),
        pubtator_client=FakePubTatorClient(),
        metadata_service=FakePublicationMetadataService(),
    )

    response = await service.lookup(VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C"))

    assert response.success is True
    assert response.source_classifications == []
    assert response.literature
    assert any("ClinVar unavailable" in warning for warning in response.warnings)
