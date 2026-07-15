from __future__ import annotations

from typing import cast

from pubtator_link.mcp.profiles import (
    MCPToolProfile,
    filter_reachable_hints,
    reachable_tools,
    tool_names_for_profile,
)
from pubtator_link.models.workflow_help import (
    WorkflowFallback,
    WorkflowHelpResponse,
    WorkflowStep,
    WorkflowTask,
)

_CITATION_AUDIT_TASKS = {"citation audit", "citation audit workflow"}
_ENTITY_DISCOVERY_TASKS = {"entity discovery"}
_GRAPH_TASKS = {
    "graph",
    "literature graph",
    "topic map",
    "literature map",
    "citation",
    "citation graph",
}
_CLINICAL_REVIEW_TASKS = {"clinical genetics review"}
_LITERATURE_REVIEW_TASKS = {"literature review"}


class WorkflowHelpService:
    """Return compact in-band workflow guidance for LLM consumers."""

    def __init__(self, profile: MCPToolProfile = "full") -> None:
        self.profile = profile

    def get_help(
        self,
        task: WorkflowTask | str = "clinical_genetics_review",
    ) -> WorkflowHelpResponse:
        normalized_task = _normalize_task(task)
        if normalized_task in _ENTITY_DISCOVERY_TASKS:
            return self._profile_response(self._entity_discovery())
        if normalized_task in _CITATION_AUDIT_TASKS:
            return self._profile_response(self._citation_audit())
        if normalized_task in _GRAPH_TASKS:
            return self._profile_response(self._literature_graph())
        review_task = (
            "clinical_genetics_review"
            if normalized_task in _CLINICAL_REVIEW_TASKS
            else "literature_review"
        )
        if normalized_task in _LITERATURE_REVIEW_TASKS:
            review_task = "literature_review"
        return self._profile_response(
            self._clinical_or_literature_review(cast(WorkflowTask, review_task))
        )

    def _profile_response(self, response: WorkflowHelpResponse) -> WorkflowHelpResponse:
        selected = set(
            reachable_tools(self.profile, tuple(step.tool_name for step in response.steps))
        )
        steps = [step for step in response.steps if step.tool_name in selected]
        if self.profile == "readonly":
            steps = [
                step.model_copy(update={"order": order})
                for order, step in enumerate(steps, start=1)
            ]
        allowed_tools = tool_names_for_profile(self.profile)
        fallbacks = [
            fallback for fallback in response.fallbacks if fallback.tool_name in allowed_tools
        ]
        meta = filter_reachable_hints(self.profile, dict(response.meta))
        return WorkflowHelpResponse(
            task=response.task,
            steps=steps,
            fallbacks=fallbacks,
            tool_sequence=[step.tool_name for step in steps],
            _meta=meta,
        )

    def _clinical_or_literature_review(self, task: WorkflowTask) -> WorkflowHelpResponse:
        if self.profile == "readonly":
            steps = [
                WorkflowStep(
                    order=1,
                    tool_name="search_biomedical_entities",
                    purpose="Resolve canonical entity IDs for genes, diseases, chemicals, and variants.",
                ),
                WorkflowStep(
                    order=2,
                    tool_name="find_entity_relations",
                    purpose="Use grounded entity IDs to discover relation evidence and PMID candidates.",
                ),
                WorkflowStep(
                    order=3,
                    tool_name="get_variant_evidence",
                    purpose="Look up source-attributed variant records and literature evidence without backend classification.",
                ),
                WorkflowStep(
                    order=4,
                    tool_name="search_literature",
                    purpose="Find candidate PMIDs with compact results and optional metadata.",
                    key_args={"metadata": "basic", "coverage": "preflight"},
                ),
                WorkflowStep(
                    order=5,
                    tool_name="get_publication_metadata",
                    purpose="Fetch citation-grade author and journal metadata for selected PMIDs.",
                ),
                WorkflowStep(
                    order=6,
                    tool_name="preflight_review_sources",
                    purpose="Check likely source coverage before direct passage retrieval.",
                ),
                WorkflowStep(
                    order=7,
                    tool_name="get_publication_passages",
                    purpose="Fetch direct citable passages for the selected PMIDs.",
                ),
            ]
            fallbacks = [
                WorkflowFallback(
                    condition="selected PMIDs need citation fields",
                    tool_name="get_publication_metadata",
                    action="Fetch citation metadata before drafting references.",
                ),
                WorkflowFallback(
                    condition="GeneReviews/NBK source is an NCBI Bookshelf URL",
                    tool_name="get_citation",
                    action=(
                        "Call get_citation with the NBK ID, then retrieve direct passages for "
                        "the returned PMID when available."
                    ),
                ),
            ]
            return _response(task=task, steps=steps, fallbacks=fallbacks)

        steps = [
            WorkflowStep(
                order=0,
                tool_name="ground_question",
                purpose=(
                    "Use the one-call path for standard grounded research questions when "
                    "the server may index review evidence."
                ),
                required=False,
                key_args={"max_pmids": 8},
            ),
            WorkflowStep(
                order=1,
                tool_name="review_quickstart",
                purpose=(
                    "For casual sessions, search, stage/index, inspect coverage, and get a "
                    "review_id/session_id handoff before batch retrieval."
                ),
                required=False,
                key_args={"n_pmids": 8},
            ),
            WorkflowStep(
                order=2,
                tool_name="search_biomedical_entities",
                purpose="Resolve canonical entity IDs for genes, diseases, chemicals, and variants.",
            ),
            WorkflowStep(
                order=3,
                tool_name="find_entity_relations",
                purpose="Use grounded entity IDs to discover relation evidence and PMID candidates.",
            ),
            WorkflowStep(
                order=4,
                tool_name="get_variant_evidence",
                purpose="Look up source-attributed variant records and literature evidence without backend classification.",
            ),
            WorkflowStep(
                order=5,
                tool_name="search_literature",
                purpose="Find candidate PMIDs with compact results and optional metadata.",
                key_args={"metadata": "basic", "coverage": "preflight"},
            ),
            WorkflowStep(
                order=6,
                tool_name="search_guidelines",
                purpose=(
                    "Convenience wrapper for filtered search_literature when guideline, "
                    "recommendation, consensus, or systematic review publication types "
                    "should be boosted."
                ),
                required=False,
            ),
            WorkflowStep(
                order=7,
                tool_name="get_publication_metadata",
                purpose="Fetch citation-grade author and journal metadata for selected PMIDs.",
            ),
            WorkflowStep(
                order=8,
                tool_name="index_review_evidence",
                purpose="Prepare the selected corpus for review-scoped retrieval.",
            ),
            WorkflowStep(
                order=9,
                tool_name="inspect_review_index",
                purpose="Verify indexed coverage, source status, and sample passages.",
            ),
            WorkflowStep(
                order=10,
                tool_name="get_review_context_batch",
                purpose="Retrieve citable passages for final claims.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="review indexing is unavailable",
                tool_name="get_publication_passages",
                action="Fetch direct passages for the same selected PMIDs.",
            ),
            WorkflowFallback(
                condition="search results lack authors",
                tool_name="get_publication_metadata",
                action="Fetch citation metadata before drafting references.",
            ),
            WorkflowFallback(
                condition="GeneReviews/NBK source is an NCBI Bookshelf URL",
                tool_name="get_citation",
                action=(
                    "GeneReviews/NBK: do not index NCBI Bookshelf URLs directly. "
                    "Call get_citation with the NBK ID, then index the "
                    "returned PMID when available."
                ),
            ),
        ]
        return _response(task=task, steps=steps, fallbacks=fallbacks)

    def _citation_audit(self) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=1,
                tool_name="get_citation",
                purpose="Resolve formatted references to candidate PMIDs.",
            ),
            WorkflowStep(
                order=2,
                tool_name="get_publication_metadata",
                purpose="Fetch citation fields and identifiers for resolved PMIDs.",
            ),
            WorkflowStep(
                order=3,
                tool_name="preflight_review_sources",
                purpose="Check likely source coverage before indexing or retrieval.",
            ),
        ]
        if self.profile == "readonly":
            steps.append(
                WorkflowStep(
                    order=4,
                    tool_name="get_publication_passages",
                    purpose="Fetch direct citable passages for the selected PMIDs.",
                )
            )
        fallbacks = [
            WorkflowFallback(
                condition="citation lookup is ambiguous",
                tool_name="search_literature",
                action="Search by title fragments and journal/year hints.",
            )
        ]
        return _response(task="citation_audit", steps=steps, fallbacks=fallbacks)

    def _literature_graph(self) -> WorkflowHelpResponse:
        if self.profile == "readonly":
            steps = [
                WorkflowStep(
                    order=1,
                    tool_name="search_literature",
                    purpose="Find initial topic PMIDs before building graph neighborhoods.",
                    key_args={"metadata": "basic", "coverage": "preflight"},
                ),
                WorkflowStep(
                    order=2,
                    tool_name="build_topic_literature_map",
                    purpose="Build a compact topic map with bounded candidate signals.",
                    key_args={"response_mode": "compact", "max_candidates": 12},
                ),
                WorkflowStep(
                    order=3,
                    tool_name="get_publication_citation_graph",
                    purpose="Inspect reference and cited-by candidate lanes for selected papers.",
                    key_args={"direction": "both", "response_mode": "compact"},
                ),
                WorkflowStep(
                    order=4,
                    tool_name="find_related_evidence_candidates",
                    purpose="Expand from seed PMIDs using related-evidence scores.",
                    key_args={"response_mode": "compact", "prefer_full_text": True},
                ),
                WorkflowStep(
                    order=5,
                    tool_name="get_publication_passages",
                    purpose="Fetch direct citable passages for the selected candidate PMIDs.",
                ),
            ]
            fallbacks = [
                WorkflowFallback(
                    condition="host ToolSearch has not loaded all graph schemas",
                    tool_name="get_server_capabilities",
                    action="Inspect workflow_bundles.literature_graph before calling the next tool.",
                ),
                WorkflowFallback(
                    condition="graph compact candidates are not enough for claim grounding",
                    tool_name="get_publication_passages",
                    action="Retrieve direct passage-level evidence before drafting claims.",
                ),
            ]
            return _response(
                task="graph",
                steps=steps,
                fallbacks=fallbacks,
                meta={"bundle": "literature_graph"},
            )

        steps = [
            WorkflowStep(
                order=1,
                tool_name="search_literature",
                purpose="Find initial topic PMIDs before building graph neighborhoods.",
                key_args={"metadata": "basic", "coverage": "preflight"},
            ),
            WorkflowStep(
                order=2,
                tool_name="build_topic_literature_map",
                purpose=(
                    "Build a compact topic map with bounded summary papers, candidate "
                    "signals, omitted_counts, and recommended next PMIDs."
                ),
                key_args={"response_mode": "compact", "max_candidates": 12},
            ),
            WorkflowStep(
                order=3,
                tool_name="get_publication_citation_graph",
                purpose=(
                    "Inspect reference and cited-by candidate lanes for selected source "
                    "papers; compact mode reports compact_status and actionable counts."
                ),
                key_args={"direction": "both", "response_mode": "compact"},
            ),
            WorkflowStep(
                order=4,
                tool_name="find_related_evidence_candidates",
                purpose=(
                    "Expand from seed PMIDs using related-evidence scores, normalized "
                    "neighbor scores, and deduped candidate signals."
                ),
                key_args={"response_mode": "compact", "prefer_full_text": True},
            ),
            WorkflowStep(
                order=5,
                tool_name="index_review_evidence",
                purpose="Index the selected graph-derived PMID corpus for review retrieval.",
            ),
            WorkflowStep(
                order=6,
                tool_name="get_review_context_batch",
                purpose="Retrieve citable passages with auto-fit compact retrieval budgets.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="host ToolSearch has not loaded all graph schemas",
                tool_name="get_server_capabilities",
                action=(
                    "Inspect workflow_bundles.literature_graph; ToolSearch gating is "
                    "controlled by the MCP host, not this server."
                ),
            ),
            WorkflowFallback(
                condition="graph compact candidates are not enough for claim grounding",
                tool_name="get_review_context_batch",
                action="Retrieve passage-level evidence before drafting claims.",
            ),
        ]
        return _response(
            task="graph",
            steps=steps,
            fallbacks=fallbacks,
            meta={
                "next_commands": [step.tool_name for step in steps[:4]],
                "bundle": "literature_graph",
                "boundary_note": (
                    "The server advertises this workflow bundle; host ToolSearch gating "
                    "controls which tool schemas are loaded on first use."
                ),
            },
        )

    def _entity_discovery(self) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=1,
                tool_name="search_biomedical_entities",
                purpose="Find PubTator entity IDs for user-supplied biomedical terms.",
            ),
            WorkflowStep(
                order=2,
                tool_name="find_entity_relations",
                purpose="Find PubTator relation evidence for grounded entities before broad search.",
            ),
            WorkflowStep(
                order=3,
                tool_name="get_mesh",
                purpose="Normalize disease and phenotype vocabulary to MeSH descriptors.",
            ),
            WorkflowStep(
                order=4,
                tool_name="search_literature",
                purpose="Use resolved entity IDs and normalized terms to find candidate PMIDs.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="entity autocomplete is sparse",
                tool_name="get_mesh",
                action="Use MeSH entry terms to reformulate the literature search.",
            )
        ]
        return _response(task="entity_discovery", steps=steps, fallbacks=fallbacks)


def _response(
    *,
    task: WorkflowTask,
    steps: list[WorkflowStep],
    fallbacks: list[WorkflowFallback],
    meta: dict[str, object] | None = None,
) -> WorkflowHelpResponse:
    response_meta: dict[str, object] = {
        "next_commands": [step.tool_name for step in steps[:3]],
        "review_retrieval_fields": (
            "After retrieval, prefer top-level recovery for empty/high-drop queries, "
            "use passages[].quote for short verbatim snippets, "
            "passages[].confidence_for_grounding level/basis for retrieval confidence, and "
            "get_review_audit_trail for selected passage audit blocks."
        ),
    }
    if meta:
        response_meta.update(meta)
    return WorkflowHelpResponse(
        task=task,
        steps=steps,
        fallbacks=fallbacks,
        tool_sequence=[step.tool_name for step in steps],
        _meta=response_meta,
    )


def _normalize_task(task: str) -> str:
    return " ".join(task.replace("_", " ").replace("-", " ").casefold().split())
