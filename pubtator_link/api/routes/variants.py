"""Variant evidence lookup routes."""

from fastapi import APIRouter

from pubtator_link.models.variants import VariantEvidenceRequest, VariantEvidenceResponse

from .dependencies import VariantEvidenceServiceDep, handle_api_errors

router = APIRouter(prefix="/api/variants", tags=["variants"])


@router.post(
    "/evidence",
    response_model=VariantEvidenceResponse,
    operation_id="lookup_variant_evidence",
    summary="Look up source-attributed variant evidence",
)
@handle_api_errors
async def lookup_variant_evidence(
    request: VariantEvidenceRequest,
    service: VariantEvidenceServiceDep,
) -> VariantEvidenceResponse:
    return await service.lookup(request)
