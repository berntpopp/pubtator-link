from __future__ import annotations

import pytest

from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataResponse,
)
from pubtator_link.models.variants import VariantEvidenceRequest
from pubtator_link.services.clinvar import ClinVarRecord, parse_clinvar_summary
from pubtator_link.services.variant_evidence import VariantEvidenceService, _match_confidence


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
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def search_publications(self, **kwargs):
        self.queries.append(kwargs["text"])
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


class BroadClinVarService:
    async def lookup(self, *, gene: str, variant_terms: list[str], condition: str | None = None):
        return [
            ClinVarRecord(
                variation_id="17661",
                preferred_name="BRCA1 c.181T>G (p.Cys61Gly)",
                hgvs=["NM_007294.4:c.181T>G", "NP_009225.1:p.Cys61Gly"],
                classification="Pathogenic",
                url="https://www.ncbi.nlm.nih.gov/clinvar/variation/17661/",
            ),
            ClinVarRecord(
                variation_id="37684",
                preferred_name="BRCA1 c.571G>A (p.Val191Ile)",
                hgvs=["NM_007294.4:c.571G>A", "NP_009225.1:p.Val191Ile"],
                classification="Benign",
                url="https://www.ncbi.nlm.nih.gov/clinvar/variation/37684/",
            ),
            ClinVarRecord(
                variation_id="99999",
                preferred_name="BRCA1 c.181del (p.Cys61GlyfsTer12)",
                hgvs=["NM_007294.4:c.181del", "NP_009225.1:p.Cys61GlyfsTer12"],
                classification="Pathogenic",
                url="https://www.ncbi.nlm.nih.gov/clinvar/variation/99999/",
            ),
        ]


class RealShapedClinVarService:
    async def lookup(self, *, gene: str, variant_terms: list[str], condition: str | None = None):
        return [
            parse_clinvar_summary(
                {
                    "uid": "17661",
                    "title": "NM_007294.4(BRCA1):c.181T>G (p.Cys61Gly)",
                    "germline_classification": {"description": "Pathogenic"},
                    "variation_set": [{"variation_name": "NM_007294.4(BRCA1):c.181T>G"}],
                }
            )
        ]


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


@pytest.mark.asyncio
async def test_lookup_keeps_broad_clinvar_hits_out_of_authoritative_evidence() -> None:
    service = VariantEvidenceService(
        clinvar=BroadClinVarService(),
        pubtator_client=FakePubTatorClient(),
    )

    response = await service.lookup(
        VariantEvidenceRequest(
            gene="BRCA1",
            protein="p.Cys61Gly",
            sources=["clinvar"],
            max_literature_pmids=0,
        )
    )

    assert [item.variation_id for item in response.normalized_variants] == ["17661"]
    assert [item.variation_id for item in response.source_classifications] == ["17661"]
    assert response.normalized_variants[0].match_confidence == "equivalent"
    assert response.source_classifications[0].match_confidence == "equivalent"
    assert [item.variation_id for item in response.candidate_variants] == ["37684", "99999"]
    assert response.candidate_variants[0].classification == "Benign"
    assert any("candidate_variants" in warning for warning in response.warnings)


@pytest.mark.asyncio
async def test_lookup_does_not_expand_literature_with_nearby_frameshift_candidate() -> None:
    client = FakePubTatorClient()
    service = VariantEvidenceService(clinvar=BroadClinVarService(), pubtator_client=client)

    response = await service.lookup(
        VariantEvidenceRequest(
            gene="BRCA1",
            protein="p.Cys61Gly",
            sources=["clinvar", "pubtator"],
            max_literature_pmids=1,
        )
    )

    assert [item.variation_id for item in response.normalized_variants] == ["17661"]
    assert [item.variation_id for item in response.candidate_variants] == ["37684", "99999"]
    for candidate in response.candidate_variants:
        assert f'"{candidate.name}"' not in client.queries[0]
        assert all(f'"{hgvs}"' not in client.queries[0] for hgvs in candidate.hgvs)


@pytest.mark.asyncio
async def test_lookup_keeps_real_clinvar_esummary_title_match_authoritative() -> None:
    service = VariantEvidenceService(
        clinvar=RealShapedClinVarService(),
        pubtator_client=FakePubTatorClient(),
    )

    response = await service.lookup(
        VariantEvidenceRequest(
            gene="BRCA1",
            protein="p.Cys61Gly",
            sources=["clinvar"],
            max_literature_pmids=0,
        )
    )

    assert [item.variation_id for item in response.normalized_variants] == ["17661"]
    assert response.normalized_variants[0].match_confidence == "exact"
    assert response.candidate_variants == []


@pytest.mark.parametrize(
    ("request_expression", "expected_confidence"),
    [
        ("NP_009225.1:p.Cys61Gly", "exact"),
        (" np_009225.1: P.cys61gly ", "exact"),
        ("p.Cys61Gly", "equivalent"),
        ("bogus:p.Cys61Gly", None),
    ],
)
def test_match_confidence_requires_a_real_transcript_prefix(
    request_expression: str, expected_confidence: str | None
) -> None:
    record = ClinVarRecord(
        variation_id="17661",
        hgvs=["NP_009225.1:p.Cys61Gly"],
        classification="Pathogenic",
        url="https://www.ncbi.nlm.nih.gov/clinvar/variation/17661/",
    )

    assert _match_confidence(record, [request_expression]) == expected_confidence
