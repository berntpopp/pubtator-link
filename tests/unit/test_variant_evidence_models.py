import pytest

from pubtator_link.models.variants import VariantEvidenceRequest, VariantEvidenceResponse


def test_variant_request_requires_gene_and_one_variant_expression() -> None:
    request = VariantEvidenceRequest(gene="MEFV", variant="c.2177T>C")

    assert request.gene == "MEFV"
    assert request.variant == "c.2177T>C"


def test_variant_request_rejects_missing_variant_expression() -> None:
    with pytest.raises(ValueError, match="variant or protein is required"):
        VariantEvidenceRequest(gene="MEFV")


def test_variant_response_has_no_computed_classification_field() -> None:
    response = VariantEvidenceResponse(
        query={"gene": "MEFV", "variant": "c.2177T>C"},
        warnings=[
            "Classifications are source-attributed; PubTator-Link does not compute clinical significance."
        ],
    )

    dumped = response.model_dump()
    assert "computed_classification" not in dumped
    assert response.source_classifications == []
