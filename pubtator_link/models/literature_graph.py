"""Shared Pydantic models for literature graph tools."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_serializer,
    model_validator,
)

CitationGraphDirection = Literal["references", "cited_by", "both"]
LiteratureGraphResponseMode = Literal["compact", "nodes_edges", "full"]
LiteratureResponseSizeClass = Literal["small", "medium", "large"]
LiteratureCandidateAccess = Literal["full_text", "open_access", "metadata_only", "unresolved"]
LiteratureSourceTool = Literal[
    "topic_search",
    "citation_graph",
    "related_evidence",
    "doi_resolution",
    "metadata_backfill",
]
LiteratureProviderStatusValue = Literal[
    "not_requested",
    "skipped",
    "success",
    "empty",
    "partial",
    "failed",
    "disabled",
]
LiteratureNodeType = Literal["paper", "author", "entity"]
LiteratureEdgeType = Literal[
    "cites",
    "cited_by",
    "authored_by",
    "mentions_entity",
    "related_by_elink",
    "related_by_pubtator_search",
]
LiteraturePaperStatus = Literal[
    "resolved_full_text_candidate",
    "resolved_metadata_only",
    "unresolved_reference",
    "publisher_entitlement_required",
]


def normalize_pmid(value: str) -> str:
    """Normalize and validate a PubMed PMID string."""
    clean = value.strip()
    if clean.upper().startswith("PMID:"):
        clean = clean[5:].strip()
    if not clean or not clean.isdigit():
        raise ValueError("PMID must be numeric")
    return clean


def normalize_doi(value: str) -> str:
    """Normalize and validate a DOI string."""
    clean = value.strip()
    if clean.lower().startswith("doi:"):
        clean = clean[4:].strip()
    if not clean:
        raise ValueError("DOI is required")
    return clean.lower()


class LiteratureGraphProvenance(BaseModel):
    """Provider provenance for graph records."""

    provider: str
    source_id: str | None = None
    source_url: str | None = None
    raw_status: str | None = None


class LiteratureAvailability(BaseModel):
    """Full-text and access availability signals for a paper."""

    has_pmc_full_text: bool = False
    is_open_access: bool = False
    has_pdf: bool = False
    full_text_url: str | None = None
    oa_status: str | None = None
    license_or_access_hint: str | None = None


class LiteratureAuthor(BaseModel):
    """Author node data for literature graphs."""

    name: str
    orcid: str | None = None
    openalex_id: str | None = None
    affiliations: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        """Stable author key from strongest available identifier."""
        if self.openalex_id:
            return f"author:openalex:{self.openalex_id}"
        if self.orcid:
            return f"author:orcid:{self.orcid}"
        return f"author:name:{self.name.casefold()}"


class LiteratureEntity(BaseModel):
    """PubTator entity node data for literature graphs."""

    entity_id: str
    entity_type: str
    name: str
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        """Stable entity key."""
        return f"entity:{self.entity_id}"


class LiteraturePaper(BaseModel):
    """Paper metadata and graph identity signals."""

    pmid: str | None = None
    doi: str | None = None
    pmcid: str | None = None
    openalex_id: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    authors: list[LiteratureAuthor] = Field(default_factory=list)
    author_summary: str | None = None
    author_count: int = Field(default=0, ge=0)
    availability: LiteratureAvailability = Field(default_factory=LiteratureAvailability)
    status: LiteraturePaperStatus = "resolved_metadata_only"
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)

    @field_validator("pmid")
    @classmethod
    def validate_pmid(cls, value: str | None) -> str | None:
        return normalize_pmid(value) if value is not None else None

    @field_validator("doi")
    @classmethod
    def validate_doi(cls, value: str | None) -> str | None:
        return normalize_doi(value) if value is not None else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        """Stable paper key from strongest available identifier."""
        if self.pmid:
            return f"paper:pmid:{self.pmid}"
        if self.doi:
            return f"paper:doi:{self.doi}"
        if self.pmcid:
            return f"paper:pmcid:{self.pmcid}"
        if self.openalex_id:
            return f"paper:openalex:{self.openalex_id}"
        title = self.title or "unresolved"
        return f"paper:title:{title.casefold()}"


class LiteratureGraphNode(BaseModel):
    """Typed graph node wrapper."""

    node_type: LiteratureNodeType
    paper: LiteraturePaper | None = None
    author: LiteratureAuthor | None = None
    entity: LiteratureEntity | None = None

    @model_validator(mode="after")
    def require_matching_payload(self) -> LiteratureGraphNode:
        payloads = {
            "paper": self.paper,
            "author": self.author,
            "entity": self.entity,
        }
        if (
            payloads[self.node_type] is None
            or sum(value is not None for value in payloads.values()) != 1
        ):
            raise ValueError(f"{self.node_type} nodes require exactly {self.node_type} payload")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def key(self) -> str:
        """Delegate to the typed node payload when present."""
        if self.node_type == "paper" and self.paper is not None:
            return self.paper.key
        if self.node_type == "author" and self.author is not None:
            return self.author.key
        if self.node_type == "entity" and self.entity is not None:
            return self.entity.key
        return f"{self.node_type}:missing"


class LiteratureGraphEdge(BaseModel):
    """Graph edge between literature graph nodes."""

    source: str
    target: str
    edge_type: LiteratureEdgeType
    weight: float = 1.0
    reasons: list[str] = Field(default_factory=list)
    provenance: list[LiteratureGraphProvenance] = Field(default_factory=list)


class ProviderWarning(BaseModel):
    """Recoverable or terminal provider warning for a graph response."""

    provider: str
    status: str
    retryable: bool = False
    message: str


class LiteratureQueryRelevance(BaseModel):
    """Bounded query relevance signals for candidate ranking only."""

    score: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)
    matched_mesh: list[str] = Field(default_factory=list)
    matched_intents: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class LiteratureCandidateSummary(BaseModel):
    """Compact publication summary for LLM candidate triage."""

    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    publication_types: list[str] = Field(default_factory=list)
    author_summary: str | None = None
    author_count: int = Field(default=0, ge=0)
    access: LiteratureCandidateAccess
    access_flags: dict[str, bool] = Field(default_factory=dict)
    score: float | None = None
    relevance_to_query: LiteratureQueryRelevance | None = None
    rank_reasons: list[str] = Field(default_factory=list)
    demotion_reasons: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    source_tools: list[LiteratureSourceTool] = Field(default_factory=list)
    next_actions: list[dict[str, Any]] = Field(default_factory=list)


class LiteratureProviderStatus(BaseModel):
    """Structured provider status for a graph direction or enrichment operation."""

    provider: str
    operation: str
    status: LiteratureProviderStatusValue
    result_count: int = 0
    retryable: bool = False
    message: str | None = None


class LiteratureResponseMeta(BaseModel):
    """Transparent metadata for literature graph responses."""

    research_use_only: bool = True
    limitations: list[str] = Field(
        default_factory=lambda: [
            "Graph relatedness is not evidence quality.",
            "Relatedness does not imply support for a biomedical claim.",
            "Passage-level review is required for claim grounding.",
        ]
    )
    warnings: list[ProviderWarning] = Field(default_factory=list)
    next_commands: list[dict[str, Any]] = Field(default_factory=list)


class LiteratureGraphResponseMeta(LiteratureResponseMeta):
    """Mode, budget, cache, and ranking metadata for graph responses."""

    response_mode: LiteratureGraphResponseMode = "full"
    response_size_class: LiteratureResponseSizeClass = "small"
    truncated: bool = False
    omitted_counts: dict[str, int] = Field(default_factory=dict)
    budget_advice: str | None = None
    cache_key: str | None = None
    snapshot_date: str | None = None
    source_versions: dict[str, str] = Field(default_factory=dict)
    ranking_version: str | None = None
    provider_status: list[LiteratureProviderStatus] = Field(default_factory=list)


def _coerce_graph_response_meta(value: Any) -> Any:
    if isinstance(value, LiteratureResponseMeta) and not isinstance(
        value,
        LiteratureGraphResponseMeta,
    ):
        return LiteratureGraphResponseMeta(**value.model_dump())
    return value


class PublicationCitationGraphRequest(BaseModel):
    """Request citation neighbors for one publication identifier."""

    pmid: str | None = None
    doi: str | None = None
    direction: CitationGraphDirection = "both"
    response_mode: LiteratureGraphResponseMode = "full"
    resolve_metadata: bool = True
    resolve_reference_pmids: bool = True
    max_reference_resolution: int = Field(default=20, ge=0, le=100)
    include_provider_status: bool = True
    include_open_access_status: bool = True
    max_results: int = Field(default=50, ge=1, le=100)

    @field_validator("pmid")
    @classmethod
    def normalize_optional_pmid(cls, value: str | None) -> str | None:
        return normalize_pmid(value) if value is not None else None

    @field_validator("doi")
    @classmethod
    def normalize_optional_doi(cls, value: str | None) -> str | None:
        return normalize_doi(value) if value is not None else None

    @model_validator(mode="after")
    def require_exactly_one_identifier(self) -> PublicationCitationGraphRequest:
        if (self.pmid is None) == (self.doi is None):
            raise ValueError("exactly one of pmid or doi is required")
        return self


class PublicationCitationGraphResponse(BaseModel):
    """Citation graph response for one source paper."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    source: LiteraturePaper
    references: list[LiteraturePaper] = Field(default_factory=list)
    cited_by: list[LiteraturePaper] = Field(default_factory=list)
    nodes: list[LiteratureGraphNode] = Field(default_factory=list)
    edges: list[LiteratureGraphEdge] = Field(default_factory=list)
    response_mode: LiteratureGraphResponseMode = "full"
    reference_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    cited_by_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    candidate_pmids: list[str] = Field(default_factory=list)
    actionable_pmid_count: int = 0
    metadata_only_count: int = 0
    unresolved_doi_count: int = 0
    compact_status: dict[str, str] = Field(default_factory=dict)
    metadata_only: list[LiteraturePaper] = Field(default_factory=list)
    references_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    cited_by_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    identifier_resolution_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    open_access_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    meta: LiteratureGraphResponseMeta = Field(
        default_factory=LiteratureGraphResponseMeta,
        alias="_meta",
    )

    @field_validator("meta", mode="before")
    @classmethod
    def coerce_legacy_meta(cls, value: Any) -> Any:
        return _coerce_graph_response_meta(value)

    @model_serializer(mode="wrap")
    def omit_empty_full_lanes_for_compact(self, handler: Any) -> Any:
        data = handler(self)
        if not isinstance(data, dict) or self.response_mode != "compact":
            return data
        for field in ("references", "cited_by", "metadata_only", "nodes", "edges"):
            if not data.get(field):
                data.pop(field, None)
        return data


class RelatedEvidenceCandidatesRequest(BaseModel):
    """Request related candidate papers for passage-level evidence review."""

    pmid: str
    max_results: int = Field(default=25, ge=1, le=100)
    response_mode: LiteratureGraphResponseMode = "compact"
    prefer_full_text: bool = True
    include_pubtator_search: bool = True
    include_citation_neighbors: bool = True
    publication_types: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None

    @field_validator("pmid")
    @classmethod
    def normalize_required_pmid(cls, value: str) -> str:
        return normalize_pmid(value)


class RelatedEvidenceCandidate(BaseModel):
    """One related evidence candidate with match metadata."""

    paper: LiteraturePaper
    score: float = 0.0
    match_reasons: list[str] = Field(default_factory=list)
    pubmed_neighbor_score: int | None = None
    normalized_neighbor_score: float | None = Field(default=None, ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)


class RelatedEvidenceCandidatesResponse(BaseModel):
    """Related evidence candidate response."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    source: LiteraturePaper
    candidates: list[RelatedEvidenceCandidate] = Field(default_factory=list)
    candidate_pmids: list[str] = Field(default_factory=list)
    caution: str = (
        "Related candidates are not substitutes and require passage-level review before use as "
        "evidence."
    )
    meta: LiteratureGraphResponseMeta = Field(
        default_factory=LiteratureGraphResponseMeta,
        alias="_meta",
    )

    @field_validator("meta", mode="before")
    @classmethod
    def coerce_legacy_meta(cls, value: Any) -> Any:
        return _coerce_graph_response_meta(value)


class TopicLiteratureMapRequest(BaseModel):
    """Request a bounded topic-level literature map."""

    query: str | None = Field(default=None, min_length=1, max_length=1000)
    pmids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    max_seed_papers: int = Field(default=25, ge=1, le=50)
    max_neighbors_per_paper: int = Field(default=10, ge=1, le=20)
    response_mode: LiteratureGraphResponseMode = "full"
    max_candidates: int = Field(default=12, ge=1, le=50)
    include_demoted: bool = True
    max_demoted: int = Field(default=3, ge=0, le=20)
    bias_toward: (
        list[
            Literal[
                "guideline",
                "cohort",
                "genotype_phenotype",
                "treatment",
                "pediatric",
                "population",
            ]
        ]
        | None
    ) = None
    max_graph_nodes: int = Field(default=30, ge=1, le=200)
    max_graph_edges: int = Field(default=60, ge=1, le=400)
    include_authors: bool = True
    include_citations: bool = True
    include_pubtator_entities: bool = True
    include_related_candidates: bool = True
    year_min: int | None = None
    year_max: int | None = None
    prefer_full_text: bool = True

    @field_validator("pmids")
    @classmethod
    def normalize_optional_pmids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        normalized: list[str] = []
        for pmid in value:
            clean = normalize_pmid(pmid)
            if clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized

    @model_validator(mode="after")
    def require_query_or_pmids(self) -> TopicLiteratureMapRequest:
        if not self.query and not self.pmids:
            raise ValueError("at least one of query or pmids is required")
        return self


class TopicLiteratureMapSummary(BaseModel):
    """Compact summary for a topic literature map."""

    central_papers: list[LiteraturePaper] = Field(default_factory=list)
    recent_connected_papers: list[LiteraturePaper] = Field(default_factory=list)
    bridge_papers: list[LiteraturePaper] = Field(default_factory=list)
    dominant_author_groups: list[str] = Field(default_factory=list)
    accessible_full_text_candidates: list[LiteraturePaper] = Field(default_factory=list)
    closed_central_sources: list[LiteraturePaper] = Field(default_factory=list)
    recommended_next_pmids: list[str] = Field(default_factory=list)


class TopicLiteratureMapResponse(BaseModel):
    """Topic literature graph response."""

    model_config = ConfigDict(serialize_by_alias=True, validate_by_name=True)

    query: str | None = None
    seed_pmids: list[str] = Field(default_factory=list)
    summary: TopicLiteratureMapSummary = Field(default_factory=TopicLiteratureMapSummary)
    nodes: list[LiteratureGraphNode] = Field(default_factory=list)
    edges: list[LiteratureGraphEdge] = Field(default_factory=list)
    response_mode: LiteratureGraphResponseMode = "full"
    top_candidates: list[LiteratureCandidateSummary] = Field(default_factory=list)
    recommended_next_pmids: list[str] = Field(default_factory=list)
    accessible_full_text_pmids: list[str] = Field(default_factory=list)
    closed_central_pmids: list[str] = Field(default_factory=list)
    demoted_candidate_pmids: list[str] = Field(default_factory=list)
    demoted_reasons_by_pmid: dict[str, list[str]] = Field(default_factory=dict)
    provider_status: list[LiteratureProviderStatus] = Field(default_factory=list)
    omitted_counts: dict[str, int] = Field(default_factory=dict)
    candidate_retrieval_hints: list[dict[str, Any]] = Field(default_factory=list)
    meta: LiteratureGraphResponseMeta = Field(
        default_factory=LiteratureGraphResponseMeta,
        alias="_meta",
    )

    @field_validator("meta", mode="before")
    @classmethod
    def coerce_legacy_meta(cls, value: Any) -> Any:
        return _coerce_graph_response_meta(value)


def _paper_dedupe_keys(paper: LiteraturePaper) -> set[str]:
    keys: set[str] = set()
    if paper.pmid:
        keys.add(f"pmid:{paper.pmid}")
    if paper.doi:
        keys.add(f"doi:{paper.doi}")
    if paper.pmcid:
        keys.add(f"pmcid:{paper.pmcid}")
    if paper.openalex_id:
        keys.add(f"openalex:{paper.openalex_id}")
    if not keys:
        keys.add(paper.key)
    return keys


def dedupe_papers(papers: list[LiteraturePaper]) -> list[LiteraturePaper]:
    """Deduplicate papers using identifier priority while preserving first instances."""
    identifier_to_index: dict[str, int] = {}
    deduped: list[LiteraturePaper | None] = []
    for paper in papers:
        keys = _paper_dedupe_keys(paper)
        overlapping_indexes = {
            identifier_to_index[key] for key in keys if key in identifier_to_index
        }
        if overlapping_indexes:
            keep_index = min(overlapping_indexes)
            merged_indexes = overlapping_indexes - {keep_index}
            for identifier, index in list(identifier_to_index.items()):
                if index in merged_indexes:
                    identifier_to_index[identifier] = keep_index
            for index in merged_indexes:
                deduped[index] = None
            for key in keys:
                identifier_to_index[key] = keep_index
            continue
        keep_index = len(deduped)
        for key in keys:
            identifier_to_index[key] = keep_index
        deduped.append(paper)
    return [paper for paper in deduped if paper is not None]


def dedupe_edges(edges: list[LiteratureGraphEdge]) -> list[LiteratureGraphEdge]:
    """Merge duplicate conceptual edges while preserving ordered reasons and provenance."""
    merged: dict[tuple[str, str, str], LiteratureGraphEdge] = {}
    for edge in edges:
        key = (edge.source, edge.target, edge.edge_type)
        if key not in merged:
            merged[key] = edge.model_copy(deep=True)
            continue
        existing = merged[key]
        existing.reasons = list(dict.fromkeys([*existing.reasons, *edge.reasons]))
        existing.provenance = [*existing.provenance, *edge.provenance]
        existing.weight = max(existing.weight, edge.weight)
    return list(merged.values())
