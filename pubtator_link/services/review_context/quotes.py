from collections.abc import Sequence

from pubtator_link.models.review_rerag import (
    ContextPassage,
    ReviewQuote,
    SourceCoverage,
    stable_citation_key_for_passage,
)


def quotes_from_passages(passages: Sequence[ContextPassage]) -> list[ReviewQuote]:
    return [
        ReviewQuote(
            stable_citation_key=passage.stable_citation_key
            or stable_citation_key_for_passage(passage.passage_id),
            pmid=passage.pmid,
            passage_id=passage.passage_id,
            section=passage.section,
            quote=_quote_text_for_passage(passage),
            matched_queries=passage.matched_queries,
            coverage_status=_coverage_status_for_passage(passage),
        )
        for passage in passages
    ]


def _quote_text_for_passage(passage: ContextPassage) -> str:
    if passage.quote is not None and passage.quote.text.strip():
        return passage.quote.text.strip()[:350]

    text = " ".join(passage.text.split())
    if len(text) <= 350:
        return text
    sentence_end = next(
        (index + 1 for index, char in enumerate(text[:350]) if char in {".", "!", "?"}),
        None,
    )
    if sentence_end is not None:
        return text[:sentence_end].strip()
    return text[:350].strip()


def _coverage_status_for_passage(passage: ContextPassage) -> SourceCoverage:
    if passage.source_kind in {"pubtator_full_bioc", "pmc_bioc", "europe_pmc_jats"}:
        return "full_text"
    if passage.source_kind == "pubtator_abstract":
        return "abstract_only"
    if passage.source_kind in {"curated_pdf", "curated_html", "docling_pdf"}:
        return "curated_url"
    return "unknown"
