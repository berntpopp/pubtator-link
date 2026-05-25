from __future__ import annotations

import re
from typing import Any, Protocol

from pubtator_link.models.corpus_suggestion import (
    CorpusCandidate,
    CorpusCandidateRole,
    CorpusSearchTrace,
    CorpusSuggestionRequest,
    CorpusSuggestionResponse,
)
from pubtator_link.models.publication_metadata import (
    PublicationMetadata,
    PublicationMetadataRequest,
    PublicationMetadataResponse,
)
from pubtator_link.models.review_rerag import SourceCoverageHint

COMMON_RELEVANCE_STOPWORDS = {
    "and",
    "are",
    "child",
    "children",
    "for",
    "from",
    "the",
    "with",
}
GUIDELINE_INTENT_TERMS = ("guideline", "recommendation", "consensus", "eular", "pres", "share")


class CorpusSearchClient(Protocol):
    async def search(self, query: str, *, limit: int, sort: str | None) -> dict[str, Any]:
        """Search literature and return raw PubTator-style results."""


class CorpusMetadataService(Protocol):
    async def get_metadata(
        self,
        request: PublicationMetadataRequest,
    ) -> PublicationMetadataResponse:
        """Return metadata for selected PMIDs."""


class CorpusPreflightService(Protocol):
    async def preflight_pmids(self, pmids: list[str]) -> list[SourceCoverageHint]:
        """Return source coverage hints for selected PMIDs."""


class CorpusSuggestionService:
    """Suggest a compact, review-feeding PMID corpus for an LLM research question."""

    def __init__(
        self,
        *,
        search_client: CorpusSearchClient,
        metadata_service: CorpusMetadataService,
        source_preflight_service: CorpusPreflightService,
    ) -> None:
        self._search_client = search_client
        self._metadata_service = metadata_service
        self._source_preflight_service = source_preflight_service

    async def suggest(self, request: CorpusSuggestionRequest) -> CorpusSuggestionResponse:
        searches = await self._run_searches(request)
        candidate_pmids = _select_pmids(request, searches)
        metadata_by_pmid = await self._metadata_by_pmid(
            candidate_pmids,
            include_metadata=request.include_metadata,
        )
        coverage_by_pmid = await self._coverage_by_pmid(candidate_pmids)
        candidates: list[CorpusCandidate] = []
        for pmid in candidate_pmids:
            metadata = metadata_by_pmid.get(pmid)
            title = _title_for(pmid, metadata_by_pmid, searches)
            role = _role_for(metadata, title=title)
            matched_terms, matched_intents = _relevance_for(
                request,
                pmid=pmid,
                title=title,
                role=role,
            )
            candidates.append(
                CorpusCandidate(
                    pmid=pmid,
                    role=role,
                    title=title,
                    score=_score_for(pmid, searches),
                    rationale=_rationale_for(role),
                    matched_terms=matched_terms,
                    matched_intents=matched_intents,
                    metadata=metadata if request.include_metadata else None,
                    coverage_hint=coverage_by_pmid.get(pmid),
                )
            )
        return CorpusSuggestionResponse(
            candidate_pmids=candidate_pmids,
            candidates=candidates,
            searches=searches,
            _meta={"next_commands": _next_commands(request, candidate_pmids)},
        )

    async def _run_searches(self, request: CorpusSuggestionRequest) -> list[CorpusSearchTrace]:
        traces: list[CorpusSearchTrace] = []
        seen_queries: set[str] = set()
        for query in _queries_for(request):
            if query in seen_queries:
                continue
            seen_queries.add(query)
            response = await self._search_client.search(query, limit=request.max_pmids, sort=None)
            result_pmids: list[str] = []
            result_titles: dict[str, str] = {}
            for item in response.get("results", []):
                pmid = str(item.get("pmid", ""))
                if not pmid:
                    continue
                result_pmids.append(pmid)
                title = item.get("title")
                if isinstance(title, str) and title and pmid not in result_titles:
                    result_titles[pmid] = title
            traces.append(
                CorpusSearchTrace(
                    query=query,
                    result_pmids=result_pmids,
                    result_titles=result_titles,
                )
            )
        return traces

    async def _metadata_by_pmid(
        self,
        pmids: list[str],
        *,
        include_metadata: bool,
    ) -> dict[str, PublicationMetadata]:
        if not pmids or not include_metadata:
            return {}
        response = await self._metadata_service.get_metadata(
            PublicationMetadataRequest(
                pmids=pmids,
                include_mesh=True,
                include_publication_types=True,
                include_citations="none",
                include_coverage=False,
            )
        )
        return {item.pmid: item for item in response.metadata}

    async def _coverage_by_pmid(self, pmids: list[str]) -> dict[str, SourceCoverageHint]:
        if not pmids:
            return {}
        hints = await self._source_preflight_service.preflight_pmids(pmids)
        return {hint.pmid: hint for hint in hints}


def _queries_for(request: CorpusSuggestionRequest) -> list[str]:
    question = _entity_augmented_question(request)
    queries = [question]
    if request.prefer_guidelines:
        queries.append(f"{question} guideline consensus recommendation")
    queries.append(f"{question} cohort variant outcome")
    if "colchicine" in request.question.lower():
        queries.append(f"{question} colchicine treatment response")
    return queries


def _entity_augmented_question(request: CorpusSuggestionRequest) -> str:
    if not request.entity_ids:
        return request.question
    return " ".join([request.question, *request.entity_ids])


def _select_pmids(
    request: CorpusSuggestionRequest,
    searches: list[CorpusSearchTrace],
) -> list[str]:
    selected: list[str] = []
    for pmid in request.must_include_pmids:
        if len(selected) >= request.max_pmids:
            return selected
        if pmid not in selected:
            selected.append(pmid)
    for trace in searches:
        for pmid in trace.result_pmids:
            title = trace.result_titles.get(pmid)
            if pmid not in request.must_include_pmids and not _has_relevance(request, title):
                continue
            if pmid not in selected:
                selected.append(pmid)
            if len(selected) >= request.max_pmids:
                return selected
    return selected[: request.max_pmids]


def _has_relevance(request: CorpusSuggestionRequest, title: str | None) -> bool:
    role = _role_for(None, title=title)
    matched_terms, _matched_intents = _relevance_for(
        request,
        pmid="",
        title=title,
        role=role,
    )
    return bool(matched_terms)


def _role_for(
    metadata: PublicationMetadata | None,
    *,
    title: str | None,
) -> CorpusCandidateRole:
    candidate_title = (metadata.title if metadata else None) or title or ""
    title_lower = candidate_title.lower()
    publication_types = {
        item.lower() for item in (metadata.publication_types if metadata is not None else [])
    }
    if (
        publication_types
        & {
            "practice guideline",
            "guideline",
            "consensus development conference",
        }
        or "recommendation" in title_lower
    ):
        return "guideline"
    if "systematic review" in publication_types or "systematic review" in title_lower:
        return "systematic_review"
    if (
        "observational study" in publication_types
        or "cohort" in title_lower
        or "registry" in title_lower
        or "series" in title_lower
    ):
        return "cohort"
    if any(term in title_lower for term in ("colchicine", "treatment", "therapy")):
        return "treatment"
    if any(term in title_lower for term in ("variant", "mutation", "mechanism")):
        return "mechanism"
    return "other"


def _title_for(
    pmid: str,
    metadata_by_pmid: dict[str, PublicationMetadata],
    searches: list[CorpusSearchTrace],
) -> str | None:
    metadata = metadata_by_pmid.get(pmid)
    if metadata is not None and metadata.title:
        return metadata.title
    for trace in searches:
        title = trace.result_titles.get(pmid)
        if title:
            return title
    return None


def _score_for(pmid: str, searches: list[CorpusSearchTrace]) -> float:
    score = 0.0
    for trace_index, trace in enumerate(searches):
        if pmid in trace.result_pmids:
            score += max(1.0, 10.0 - trace_index)
    return score


def _relevance_for(
    request: CorpusSuggestionRequest,
    *,
    pmid: str,
    title: str | None,
    role: CorpusCandidateRole,
) -> tuple[list[str], list[str]]:
    title_lower = (title or "").lower()
    matched_terms = _matched_question_terms(request, title_lower)
    matched_intents: list[str] = []
    if pmid in request.must_include_pmids:
        matched_intents.append("must_include")
    if role != "other":
        matched_intents.append(role)
    return list(dict.fromkeys(matched_terms)), list(dict.fromkeys(matched_intents))


def _matched_question_terms(request: CorpusSuggestionRequest, title_lower: str) -> list[str]:
    if not title_lower:
        return []
    terms: list[str] = []
    question_terms = [
        token
        for token in (
            "".join(character for character in word.lower() if character.isalnum())
            for word in request.question.split()
        )
        if len(token) >= 3 and token not in COMMON_RELEVANCE_STOPWORDS
    ]
    entity_terms = [
        token.lower().removeprefix("@gene_")
        for token in request.entity_ids
        if token.lower().startswith("@gene_")
    ]
    for term in [*question_terms, *entity_terms]:
        if term == "fmf" and "familial mediterranean fever" in title_lower:
            terms.append("familial mediterranean fever")
        elif _contains_term(title_lower, term):
            terms.append(term)
    if (
        terms
        and _request_has_guideline_intent(request)
        and any(term in title_lower for term in GUIDELINE_INTENT_TERMS)
    ):
        terms.append("guideline")
    return terms


def _contains_term(text: str, term: str) -> bool:
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _request_has_guideline_intent(request: CorpusSuggestionRequest) -> bool:
    request_text = " ".join([request.question, *request.entity_ids]).lower()
    return any(term in request_text for term in GUIDELINE_INTENT_TERMS)


def _rationale_for(role: CorpusCandidateRole) -> str:
    if role == "guideline":
        return "Selected as a guideline or recommendation anchor."
    if role == "cohort":
        return "Selected as cohort or observational evidence."
    if role == "systematic_review":
        return "Selected as synthesis evidence."
    if role == "treatment":
        return "Selected for treatment-response context."
    if role == "mechanism":
        return "Selected for mechanism or variant context."
    return "Selected from ranked literature search results."


def _next_commands(request: CorpusSuggestionRequest, pmids: list[str]) -> list[str]:
    review_id = _review_id_for(request.question)
    return [
        f"pubtator_get_publication_metadata(pmids={pmids!r})",
        f"pubtator_index_review_evidence(review_id='{review_id}', pmids={pmids!r})",
        f"pubtator_inspect_review_index(review_id='{review_id}')",
        f"pubtator_retrieve_review_context_batch(review_id='{review_id}', queries={[request.question]!r})",
    ]


def _review_id_for(question: str) -> str:
    tokens = [
        "".join(character for character in token.lower() if character.isalnum())
        for token in question.split()
    ]
    tokens = [token for token in tokens if token]
    return "-".join(tokens[:6]) or "suggested-corpus"
