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
