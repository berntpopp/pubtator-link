from __future__ import annotations

from pubtator_link.mcp.resources import RESEARCH_USE_NOTICE


def search_biomedical_literature_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Use pubtator.search_literature to find relevant "
        "PubMed literature. Use pubtator.search_biomedical_entities first when the "
        "query needs a canonical PubTator entity identifier. Summarize PMIDs, titles, "
        "entity IDs, and limits of the retrieval."
    )


def annotate_research_text_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Use pubtator.submit_text_annotation for biomedical "
        "named entity recognition in research text, then poll pubtator.get_text_annotation_results "
        "with the returned session_id. Report extracted entities as suggestions, not clinical facts."
    )


def review_pubtator_annotations_prompt() -> str:
    return (
        f"{RESEARCH_USE_NOTICE} Review returned PubTator annotations against the supplied "
        "research text. Flag unsupported, ambiguous, or context-mismatched entity suggestions."
    )
