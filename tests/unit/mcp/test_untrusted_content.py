"""Structural untrusted-text fencing contracts."""

from __future__ import annotations

import hashlib

from pubtator_link.mcp.untrusted_content import fence_untrusted_text


def test_fence_normalizes_and_removes_forbidden_controls() -> None:
    raw = "Cafe\u0301\x00\u200b\u202e\nBRCA1"
    fenced = fence_untrusted_text(raw, source="pubtator", record_id="PMID:1")

    assert fenced.kind == "untrusted_text"
    assert fenced.text == "Caf\u00e9\nBRCA1"
    assert fenced.raw_sha256 == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert fenced.provenance.source == "pubtator"
    assert fenced.provenance.record_id == "PMID:1"


def test_fence_preserves_tabs_newlines_and_scientific_symbols() -> None:
    raw = "p.Gly12Asp\t\u0394G = \u22121.2 kcal/mol\r\n"
    assert fence_untrusted_text(raw, source="pubtator", record_id="PMID:2").text == raw


def test_export_documents_fence_upstream_prose_in_every_serialization() -> None:
    import json
    from pathlib import Path

    import jsonschema

    from pubtator_link.mcp.untrusted_content import fence_export_documents

    passage = {
        "offset": 7,
        "text": "Body​ text.",
        "infons": {"type": "abstract", "license": "CC BY 4.0 terms.", "xml": "<table> a </table>"},
        "annotations": [{"text": "BRCA1"}],
    }
    dumped = {
        "format": "biocjson",
        "export_data": {
            "documents": [
                {"id": "123", "text": None, "passages": [passage]},
                {"id": "biocxml_document", "content": "<collection> x </collection>"},
                {"pmid": "9", "sections": {"t": "A title", "a": "An abstract"}, "annotations": []},
            ]
        },
    }

    bioc, xml, tab = fence_export_documents(dumped, source="pubtator_export")["export_data"][
        "documents"
    ]

    fenced = [
        bioc["passages"][0]["text"],
        bioc["passages"][0]["infons"]["license"],
        bioc["passages"][0]["infons"]["xml"],
        xml["content"],
        tab["sections"]["t"],
        tab["sections"]["a"],
    ]
    schema = json.loads(
        (Path(__file__).parents[2] / "conformance/envelope-v1.2.schema.json").read_text()
    )
    fence_schema = {"$ref": "#/$defs/untrusted_text", "$defs": schema["$defs"]}
    for item in fenced:
        jsonschema.validate(
            json.loads(json.dumps(item, default=lambda v: v.isoformat())), fence_schema
        )
    assert bioc["passages"][0]["text"]["text"] == "Body text."
    assert bioc["passages"][0]["text"]["provenance"]["record_id"] == "123#7"
    assert tab["sections"]["a"]["provenance"]["record_id"] == "9#a"
    # Structured data stays as it was.
    assert bioc["text"] is None
    assert bioc["passages"][0]["infons"]["type"] == "abstract"
    assert bioc["passages"][0]["annotations"] == [{"text": "BRCA1"}]


async def test_variant_evidence_snippet_is_fenced() -> None:
    from pubtator_link.mcp.service_adapters import lookup_variant_evidence_impl
    from pubtator_link.models.variants import VariantEvidenceResponse, VariantLiteratureEvidence

    class Service:
        async def lookup(self, request: object) -> VariantEvidenceResponse:
            hits = [
                VariantLiteratureEvidence(pmid="1", title="T", snippet="A\x00 highlight."),
                VariantLiteratureEvidence(pmid="2"),
            ]
            return VariantEvidenceResponse(query={"gene": "MEFV"}, literature=hits)

    first, second = (
        await lookup_variant_evidence_impl(service=Service(), gene="MEFV", variant="c.1A>G")
    )["literature"]

    assert first["snippet"]["kind"] == "untrusted_text"
    assert first["snippet"]["text"] == "A highlight."
    assert first["snippet"]["provenance"]["record_id"] == "PMID:1"
    assert second["snippet"] is None
