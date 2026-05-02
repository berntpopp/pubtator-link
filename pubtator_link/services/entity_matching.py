from __future__ import annotations

import re
from typing import Any


def matched_terms_from_match_text(value: str | None) -> list[str]:
    """Extract concise matched terms from PubTator autocomplete match metadata."""
    if not value:
        return []
    cleaned = re.sub(r"</?m>", "", value)
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1]
    if "synonyms" in cleaned.lower():
        cleaned = cleaned.split("synonyms", 1)[-1]
    return [term.strip(" .") for term in cleaned.split(",") if term.strip(" .")]


def synonyms_from_entity_item(item: dict[str, Any], *, limit: int = 10) -> list[str]:
    values: list[str] = []
    for synonym in item.get("synonyms") or []:
        if isinstance(synonym, str) and synonym.strip():
            values.append(synonym.strip())
    values.extend(matched_terms_from_match_text(item.get("match")))

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"</?m>", "", value).strip(" .")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            deduped.append(cleaned)
        if len(deduped) >= limit:
            break
    return deduped
