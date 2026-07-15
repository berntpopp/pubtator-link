"""Closed vocabularies for PubTator3 search/filter arguments, declared as enums.

These filters are CASE-SENSITIVE upstream: a capitalization miss ('review', 'ABSTRACT') matches
nothing rather than erroring, which is the silent-empty-filter bug the Tool-Schema Documentation
Standard (S4) exists to prevent. Declaring the accepted vocabulary as a ``Literal`` makes pydantic
reject an out-of-set value with ``invalid_input`` instead of returning a confident empty result.

Every member below was verified to return results against the live PubTator3 API, so the schema is
a subset of what the runtime accepts (never a superset — a schema wider than the runtime would
re-introduce exactly the silent-empty it is meant to kill).
"""

from __future__ import annotations

from typing import Literal

# PubTator3 search `sections` filter — lowercase section labels.
SearchSection = Literal["title", "abstract", "introduction", "methods", "results", "discussion"]

# BioC passage section labels get_publication_passages / estimate_publication_context filter on.
# The passage service matches these case-insensitively; the schema declares the canonical uppercase
# BioC labels so an out-of-set value is rejected instead of silently returning zero passages (S4).
PassageSection = Literal[
    "TITLE",
    "ABSTRACT",
    "INTRO",
    "METHODS",
    "RESULTS",
    "DISCUSS",
    "CONCL",
    "FIG",
    "TABLE",
    "REF",
]

# PubMed publication types PubTator3 indexes — Title-Case.
PublicationType = Literal[
    "Review",
    "Journal Article",
    "Meta-Analysis",
    "Systematic Review",
    "Guideline",
    "Practice Guideline",
    "Clinical Trial",
    "Randomized Controlled Trial",
    "Comparative Study",
    "Case Reports",
    "Letter",
    "Editorial",
    "Observational Study",
    "Multicenter Study",
    "Clinical Study",
    "Validation Study",
]
