from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from pubtator_link.api.routes.dependencies import get_variant_evidence_service
from pubtator_link.models.variants import (
    SourceClassification,
    VariantEvidenceResponse,
)
from pubtator_link.server_manager import UnifiedServerManager


class FakeVariantEvidenceService:
    async def lookup(self, request):
        return VariantEvidenceResponse(
            query=request.model_dump(exclude_none=True),
            source_classifications=[
                SourceClassification(
                    source="clinvar",
                    classification="Pathogenic",
                    variation_id="12345",
                )
            ],
            warnings=[
                "Classifications are source-attributed; PubTator-Link does not compute clinical significance."
            ],
        )


@pytest.mark.asyncio
async def test_lookup_variant_evidence_route_returns_source_attributed_records() -> None:
    app = UnifiedServerManager().create_app()
    app.dependency_overrides[get_variant_evidence_service] = lambda: FakeVariantEvidenceService()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/variants/evidence",
            json={"gene": "MEFV", "variant": "c.2177T>C", "include_citations": True},
        )

    assert response.status_code == 200
    assert response.json()["source_classifications"][0]["source"] == "clinvar"
