from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

from pubtator_link.api.routes.dependencies import get_discovery_service
from pubtator_link.mcp.input_normalization import InputNormalizationError
from pubtator_link.models.literature_graph import normalize_pmid

logger = logging.getLogger(__name__)

_PMID_REASON = "PMIDs must be ASCII digits 0-9 (optionally 'PMID:'-prefixed)."
_ID_FORM_REASON = "PMIDs only; this is a {}. Convert it with map_article_ids first."
# [0-9], not \d: \d admits non-ASCII digits. One shape contract for schema and runtime.
_PMCID = r"[Pp][Mm][Cc][0-9]{1,12}"
_DOI = r"(?:[Dd][Oo][Ii]:\s*)?(10\.[0-9]{4,9}/[-._;()/:A-Za-z0-9]+)"
_PMCID_PATTERN = re.compile(_PMCID)
_DOI_PATTERN = re.compile(_DOI)
# Advertised by tools that accept a PMCID or DOI in place of a PMID (router #319).
ARTICLE_ID_PATTERN = rf"^\s*(?:(?:[Pp][Mm][Ii][Dd]:\s*)?[0-9]+|{_PMCID}|{_DOI})\s*$"
_CACHE_MAX = 1024
_resolved_pmids: dict[str, str] = {}  # PMCID/DOI -> PMID; ID mappings are stable.


def _id_form(value: str) -> tuple[str, str] | None:
    """Return (form, canonical id) for a strictly shaped PMCID or DOI, else None."""
    stripped = value.strip()
    if _PMCID_PATTERN.fullmatch(stripped):
        return "pmcid", stripped.upper()
    if match := _DOI_PATTERN.fullmatch(stripped):
        return "doi", match.group(1).lower()
    return None


def _pmid_error(field: str, reason: str) -> InputNormalizationError:
    return InputNormalizationError(
        field_errors=[{"field": field, "reason": reason}],
        recovery_hint="Pass numeric PubMed IDs, e.g. '25741868'.",
    )


def coalesce_query(*values: str | None) -> str:
    """Return the first non-empty query-like argument."""
    selected_values: list[str] = []
    for value in values:
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            selected_values.append(stripped)
    if not selected_values:
        raise ValueError("Provide query.")
    if len(set(selected_values)) > 1:
        raise ValueError("Provide only one query-like argument.")
    return selected_values[0]


def merge_pmids(
    pmids: Iterable[str] | None = None,
    pmid: str | None = None,
    *,
    max_items: int | None = None,
    field: str = "pmids",
) -> list[str]:
    """Merge list and scalar PMID arguments, preserving first-seen order."""
    selected_pmids: list[str] = []
    seen_pmids: set[str] = set()

    entries = [*((field, value) for value in pmids or []), ("pmid", pmid)]
    for source, value in entries:
        if value is None or not value.strip():
            continue
        try:
            # One PMID validator for every tool (D4): never pass a non-numeric ID upstream.
            stripped = normalize_pmid(value)
        except ValueError:
            if form := _id_form(value):
                # ponytail: lean profile does not register map_article_ids; pointer dangles there.
                error = _pmid_error(source, _ID_FORM_REASON.format(form[0].upper()))
                # strict pattern above: safe to echo
                error.next_command = {
                    "tool": "map_article_ids",
                    "arguments": {"ids": [form[1]]},
                }
                raise error from None
            raise _pmid_error(source, _PMID_REASON) from None
        if stripped in seen_pmids:
            continue
        selected_pmids.append(stripped)
        seen_pmids.add(stripped)
        if max_items is not None and len(selected_pmids) > max_items:
            raise _pmid_error(field, f"Provide at most {max_items} PMIDs.")
    if not selected_pmids:
        raise _pmid_error(field, "Provide at least one PMID.")
    return selected_pmids


async def resolve_pmids(
    pmids: Iterable[str] | None = None,
    pmid: str | None = None,
    *,
    max_items: int | None = None,
) -> tuple[list[str], Any]:
    """merge_pmids that first converts PMCIDs/DOIs to PMIDs via the NCBI ID converter.

    Returns the PMIDs and the `resolved_from` echo (a list for `pmids`, one dict for a scalar
    `pmid`, None when nothing was converted). An ID that does not convert stays as given, so
    merge_pmids raises the field-named invalid_input pointing at map_article_ids.
    """
    values = [*(pmids or []), *([pmid] if pmid is not None else [])]
    forms = {value: form for value in values if (form := _id_form(value))}
    missing = list(dict.fromkeys(c for _, c in forms.values() if c not in _resolved_pmids))
    if missing:
        try:
            response = await (await get_discovery_service()).map_article_ids(missing)
        except Exception as exc:  # converter down: fall back to the honest invalid_input
            logger.warning("article_id_conversion_failed", extra={"error": type(exc).__name__})
        else:
            for canonical, record in zip(missing, response.records, strict=False):
                if record.status == "resolved" and record.pmid:
                    if len(_resolved_pmids) >= _CACHE_MAX:
                        _resolved_pmids.pop(next(iter(_resolved_pmids)))
                    _resolved_pmids[canonical] = record.pmid
    resolved_from: list[dict[str, str]] = []
    converted: list[str] = []
    for value in values:
        form = forms.get(value)
        target = _resolved_pmids.get(form[1]) if form else None
        if form and target:
            resolved_from.append({"input": form[1], "form": form[0], "resolved_to": target})
        converted.append(target or value)
    scalar = converted.pop() if pmid is not None else None
    selected = merge_pmids(converted if pmids is not None else None, scalar, max_items=max_items)
    if not resolved_from:
        return selected, None
    return selected, resolved_from[0] if pmids is None else resolved_from


def with_resolved_from(result: dict[str, Any], resolved_from: Any) -> dict[str, Any]:
    """Echo the ID conversion on a success payload; omitted when nothing was converted."""
    if resolved_from:
        result["resolved_from"] = resolved_from
    return result
