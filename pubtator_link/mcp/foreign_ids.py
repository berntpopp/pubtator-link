"""Reject a gene given as an identifier from a namespace this server cannot convert.

PubTator-Link holds no gene cross-reference table, so `HGNC:1100`, `ENSG00000012048` or an NCBI
Gene id would be searched as literal text and answered with an unrelated or empty result. That
reads as an absence when the input was simply not understood, so it is `invalid_input` naming the
field, the accepted form and a ready-to-send converter call (sibling HGNC tools; the router
passes the names through). Every pattern is a strict full match, which is what makes echoing
the value into `next_commands` safe.
"""

from __future__ import annotations

import re

from pubtator_link.mcp.input_normalization import InputNormalizationError

_GENE_FORMS = ["HGNC gene symbol (e.g. BRCA1)"]
_VIA_SYMBOL_RESOLVER = re.compile(r"HGNC:\d+|ENSG\d{11}(\.\d+)?", re.IGNORECASE | re.ASCII)
_NCBI_GENE = re.compile(
    r"(?:(?:NCBIGene|NCBI_Gene|Entrez|GeneID):)?(\d+)", re.IGNORECASE | re.ASCII
)


def reject_foreign_gene(value: str, field: str) -> None:
    """Raise `invalid_input` when `value` is an HGNC, Ensembl or NCBI Gene id, not a symbol."""
    value = value.strip()
    ncbi = _NCBI_GENE.fullmatch(value)
    if _VIA_SYMBOL_RESOLVER.fullmatch(value):
        tool, arguments = "hgnc_resolve_symbol", {"query": value}
    elif ncbi:
        tool = "hgnc_resolve_gene_by_xref"
        arguments = {"source": "entrez_id", "value": ncbi.group(1).lstrip("0") or "0"}
    else:
        return
    raise InputNormalizationError(
        field_errors=[
            {"field": field, "message": "A gene identifier is not accepted; pass the symbol."}
        ],
        recovery_hint=f"Convert it to the approved HGNC symbol with {tool}, then re-call.",
        next_command={"tool": tool, "arguments": arguments},
        extra={"field": field, "allowed_values": _GENE_FORMS},
    )
