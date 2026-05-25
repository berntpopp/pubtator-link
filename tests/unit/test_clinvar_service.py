from __future__ import annotations

import pytest

from pubtator_link.services.clinvar import ClinVarService, parse_clinvar_summary


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._data


class FakeClinVarHttpClient:
    def __init__(self) -> None:
        self.esearch_terms: list[str] = []

    async def get(self, url: str, *, params: dict[str, str]):
        if url.endswith("esearch.fcgi"):
            self.esearch_terms.append(params["term"])
            return FakeResponse({"esearchresult": {"idlist": ["12345"]}})
        return FakeResponse({"result": {"uids": ["12345"], "12345": _summary_doc()}})


@pytest.mark.asyncio
async def test_clinvar_query_construction_uses_gene_and_variant() -> None:
    client = FakeClinVarHttpClient()
    service = ClinVarService(client)

    await service.lookup(
        gene="MEFV",
        variant_terms=["c.2177T>C"],
        condition="familial Mediterranean fever",
    )

    assert (
        client.esearch_terms[0] == 'MEFV[gene] AND "c.2177T>C" AND "familial Mediterranean fever"'
    )


def test_parse_clinvar_summary_source_attributed_classification() -> None:
    record = parse_clinvar_summary(_summary_doc())

    assert record.source == "clinvar"
    assert record.classification == "Pathogenic"
    assert record.variation_id == "12345"
    assert record.url == "https://www.ncbi.nlm.nih.gov/clinvar/variation/12345/"


def test_parse_clinvar_summary_reads_germline_classification() -> None:
    record = parse_clinvar_summary(
        {
            "uid": "449657",
            "title": "NM_000243.3(MEFV):c.2080_2082delinsGTA (p.Met694Val)",
            "germline_classification": {
                "description": "Pathogenic",
                "review_status": "criteria provided, single submitter",
                "last_evaluated": "2017/10/26 00:00",
                "trait_set": [{"trait_name": "Familial Mediterranean fever"}],
            },
        }
    )

    assert record.classification == "Pathogenic"
    assert record.review_status == "criteria provided, single submitter"
    assert record.last_evaluated == "2017/10/26 00:00"
    assert record.condition == "Familial Mediterranean fever"


def _summary_doc() -> dict[str, object]:
    return {
        "uid": "12345",
        "accession": "VCV000012345",
        "title": "NM_000243.3(MEFV):c.2177T>C (p.Val726Ala)",
        "variation_id": "12345",
        "allele_id": "67890",
        "clinical_significance": {"description": "Pathogenic"},
        "review_status": "criteria provided, multiple submitters, no conflicts",
        "trait_set": [{"trait_name": "Familial Mediterranean fever"}],
        "last_evaluated": "2024-01-01",
        "variation_set": [{"variation_name": "MEFV c.2177T>C"}],
        "hgvs": ["NM_000243.3:c.2177T>C", "NP_000234.1:p.Val726Ala"],
    }
