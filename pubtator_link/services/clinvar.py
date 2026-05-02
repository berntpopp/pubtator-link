"""ClinVar E-utilities lookup for source-attributed variant records."""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from pubtator_link.models.variants import NormalizedVariant, SourceClassification

CLINVAR_EUTILS_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class ClinVarHttpClient(Protocol):
    async def get(self, url: str, *, params: dict[str, str]) -> Any:
        """Perform a ClinVar E-utilities GET request."""


class ClinVarRecord(BaseModel):
    """Parsed ClinVar record with source-attributed fields."""

    source: str = "clinvar"
    variation_id: str
    allele_id: str | None = None
    preferred_name: str | None = None
    hgvs: list[str] = Field(default_factory=list)
    classification: str
    review_status: str | None = None
    condition: str | None = None
    last_evaluated: str | None = None
    url: str

    def normalized_variant(self) -> NormalizedVariant:
        return NormalizedVariant(
            source="clinvar",
            name=self.preferred_name or self.variation_id,
            variation_id=self.variation_id,
            allele_id=self.allele_id,
            hgvs=self.hgvs,
            url=self.url,
        )

    def source_classification(self) -> SourceClassification:
        return SourceClassification(
            source="clinvar",
            classification=self.classification,
            review_status=self.review_status,
            condition=self.condition,
            last_evaluated=self.last_evaluated,
            variation_id=self.variation_id,
            allele_id=self.allele_id,
            url=self.url,
        )


class ClinVarService:
    """Lookup ClinVar records through NCBI E-utilities."""

    def __init__(
        self,
        http_client: ClinVarHttpClient | None = None,
        *,
        base_url: str = CLINVAR_EUTILS_BASE_URL,
    ) -> None:
        self.http_client = http_client or httpx.AsyncClient(timeout=20.0)
        self.base_url = base_url.rstrip("/")

    async def lookup(
        self,
        *,
        gene: str,
        variant_terms: list[str],
        condition: str | None = None,
        retmax: int = 10,
    ) -> list[ClinVarRecord]:
        term = _clinvar_term(gene=gene, variant_terms=variant_terms, condition=condition)
        search_response = await self.http_client.get(
            f"{self.base_url}/esearch.fcgi",
            params={
                "db": "clinvar",
                "retmode": "json",
                "retmax": str(retmax),
                "term": term,
            },
        )
        search_response.raise_for_status()
        id_list = [
            str(item) for item in search_response.json().get("esearchresult", {}).get("idlist", [])
        ]
        if not id_list:
            return []

        summary_response = await self.http_client.get(
            f"{self.base_url}/esummary.fcgi",
            params={
                "db": "clinvar",
                "retmode": "json",
                "id": ",".join(id_list),
            },
        )
        summary_response.raise_for_status()
        result = summary_response.json().get("result", {})
        return [
            parse_clinvar_summary(result[uid])
            for uid in result.get("uids", id_list)
            if isinstance(result.get(uid), dict)
        ]


def parse_clinvar_summary(document: dict[str, Any]) -> ClinVarRecord:
    variation_id = str(
        document.get("variation_id")
        or document.get("uid")
        or document.get("accession", "").removeprefix("VCV")
    )
    return ClinVarRecord(
        variation_id=variation_id,
        allele_id=_optional_str(document.get("allele_id")),
        preferred_name=_optional_str(document.get("title"))
        or _optional_str(document.get("variation_name")),
        hgvs=_list_values(document.get("hgvs")),
        classification=_clinical_significance(document),
        review_status=_optional_str(document.get("review_status")),
        condition=_condition(document),
        last_evaluated=_optional_str(document.get("last_evaluated")),
        url=f"https://www.ncbi.nlm.nih.gov/clinvar/variation/{variation_id}/",
    )


def _clinvar_term(
    *,
    gene: str,
    variant_terms: list[str],
    condition: str | None,
) -> str:
    parts = [f"{gene}[gene]"]
    parts.extend(f'"{term}"' for term in variant_terms if term)
    if condition:
        parts.append(f'"{condition}"')
    return " AND ".join(parts)


def _clinical_significance(document: dict[str, Any]) -> str:
    value = document.get("clinical_significance")
    if isinstance(value, dict):
        return str(value.get("description") or value.get("label") or "not provided")
    if value:
        return str(value)
    return "not provided"


def _condition(document: dict[str, Any]) -> str | None:
    trait_set = document.get("trait_set")
    if isinstance(trait_set, list):
        names = [
            str(item.get("trait_name"))
            for item in trait_set
            if isinstance(item, dict) and item.get("trait_name")
        ]
        if names:
            return "; ".join(names)
    return _optional_str(document.get("condition"))


def _list_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
