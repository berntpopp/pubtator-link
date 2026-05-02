from __future__ import annotations

import re


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
