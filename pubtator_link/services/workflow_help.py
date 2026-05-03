from __future__ import annotations

from pubtator_link.mcp.profiles import MCPToolProfile, tool_names_for_profile
from pubtator_link.models.workflow_help import (
    WorkflowFallback,
    WorkflowHelpResponse,
    WorkflowStep,
    WorkflowTask,
)


class WorkflowHelpService:
    """Return compact in-band workflow guidance for LLM consumers."""

    def __init__(self, profile: MCPToolProfile = "full") -> None:
        self.profile = profile
        self._allowed_tools = tool_names_for_profile(profile)

    def get_help(self, task: WorkflowTask = "clinical_genetics_review") -> WorkflowHelpResponse:
        if task == "entity_discovery":
            return self._profile_response(self._entity_discovery())
        if task == "citation_audit":
            return self._profile_response(self._citation_audit())
        return self._profile_response(self._clinical_or_literature_review(task))

    def _profile_response(self, response: WorkflowHelpResponse) -> WorkflowHelpResponse:
        if self.profile == "full":
            return response

        steps = [step for step in response.steps if step.tool_name in self._allowed_tools]
        fallbacks = [
            fallback for fallback in response.fallbacks if fallback.tool_name in self._allowed_tools
        ]
        meta = dict(response.meta)
        next_commands = meta.get("next_commands")
        if isinstance(next_commands, list):
            meta["next_commands"] = [
                command for command in next_commands if command in self._allowed_tools
            ]
        return WorkflowHelpResponse(
            task=response.task,
            steps=steps,
            fallbacks=fallbacks,
            tool_sequence=[step.tool_name for step in steps],
            _meta=meta,
        )

    def _clinical_or_literature_review(self, task: WorkflowTask) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=0,
                tool_name="pubtator.ground_question",
                purpose=(
                    "Use the one-call path for standard grounded research questions when "
                    "the server may index review evidence."
                ),
                required=False,
                key_args={"max_pmids": 8},
            ),
            WorkflowStep(
                order=1,
                tool_name="pubtator.review_quickstart",
                purpose=(
                    "For casual sessions, search, stage/index, inspect coverage, and get a "
                    "review_id/session_id handoff before batch retrieval."
                ),
                required=False,
                key_args={"n_pmids": 8},
            ),
            WorkflowStep(
                order=2,
                tool_name="pubtator.search_biomedical_entities",
                purpose="Resolve canonical entity IDs for genes, diseases, chemicals, and variants.",
            ),
            WorkflowStep(
                order=3,
                tool_name="pubtator.find_entity_relations",
                purpose="Use grounded entity IDs to discover relation evidence and PMID candidates.",
            ),
            WorkflowStep(
                order=4,
                tool_name="pubtator.lookup_variant_evidence",
                purpose="Look up source-attributed variant records and literature evidence without backend classification.",
            ),
            WorkflowStep(
                order=5,
                tool_name="pubtator.search_literature",
                purpose="Find candidate PMIDs with compact results and optional metadata.",
                key_args={"metadata": "basic", "coverage": "preflight"},
            ),
            WorkflowStep(
                order=6,
                tool_name="pubtator.search_guidelines",
                purpose=(
                    "Convenience wrapper for filtered search_literature when guideline, "
                    "recommendation, consensus, or systematic review publication types "
                    "should be boosted."
                ),
                required=False,
            ),
            WorkflowStep(
                order=7,
                tool_name="pubtator.get_publication_metadata",
                purpose="Fetch citation-grade author and journal metadata for selected PMIDs.",
            ),
            WorkflowStep(
                order=8,
                tool_name="pubtator.index_review_evidence",
                purpose="Prepare the selected corpus for review-scoped retrieval.",
            ),
            WorkflowStep(
                order=9,
                tool_name="pubtator.inspect_review_index",
                purpose="Verify indexed coverage, source status, and sample passages.",
            ),
            WorkflowStep(
                order=10,
                tool_name="pubtator.retrieve_review_context_batch",
                purpose="Retrieve citable passages for final claims.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="review indexing is unavailable",
                tool_name="pubtator.get_publication_passages",
                action="Fetch direct passages for the same selected PMIDs.",
            ),
            WorkflowFallback(
                condition="search results lack authors",
                tool_name="pubtator.get_publication_metadata",
                action="Fetch citation metadata before drafting references.",
            ),
            WorkflowFallback(
                condition="GeneReviews/NBK source is an NCBI Bookshelf URL",
                tool_name="pubtator.lookup_citation",
                action=(
                    "GeneReviews/NBK: do not index NCBI Bookshelf URLs directly. "
                    "Call pubtator.lookup_citation with the NBK ID, then index the "
                    "returned PMID when available."
                ),
            ),
        ]
        return _response(task=task, steps=steps, fallbacks=fallbacks)

    def _citation_audit(self) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=1,
                tool_name="pubtator.lookup_citation",
                purpose="Resolve formatted references to candidate PMIDs.",
            ),
            WorkflowStep(
                order=2,
                tool_name="pubtator.get_publication_metadata",
                purpose="Fetch citation fields and identifiers for resolved PMIDs.",
            ),
            WorkflowStep(
                order=3,
                tool_name="pubtator.preflight_review_sources",
                purpose="Check likely source coverage before indexing or retrieval.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="citation lookup is ambiguous",
                tool_name="pubtator.search_literature",
                action="Search by title fragments and journal/year hints.",
            )
        ]
        return _response(task="citation_audit", steps=steps, fallbacks=fallbacks)

    def _entity_discovery(self) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=1,
                tool_name="pubtator.search_biomedical_entities",
                purpose="Find PubTator entity IDs for user-supplied biomedical terms.",
            ),
            WorkflowStep(
                order=2,
                tool_name="pubtator.find_entity_relations",
                purpose="Find PubTator relation evidence for grounded entities before broad search.",
            ),
            WorkflowStep(
                order=3,
                tool_name="pubtator.lookup_mesh",
                purpose="Normalize disease and phenotype vocabulary to MeSH descriptors.",
            ),
            WorkflowStep(
                order=4,
                tool_name="pubtator.search_literature",
                purpose="Use resolved entity IDs and normalized terms to find candidate PMIDs.",
            ),
        ]
        fallbacks = [
            WorkflowFallback(
                condition="entity autocomplete is sparse",
                tool_name="pubtator.lookup_mesh",
                action="Use MeSH entry terms to reformulate the literature search.",
            )
        ]
        return _response(task="entity_discovery", steps=steps, fallbacks=fallbacks)


def _response(
    *,
    task: WorkflowTask,
    steps: list[WorkflowStep],
    fallbacks: list[WorkflowFallback],
) -> WorkflowHelpResponse:
    return WorkflowHelpResponse(
        task=task,
        steps=steps,
        fallbacks=fallbacks,
        tool_sequence=[step.tool_name for step in steps],
        _meta={
            "next_commands": [step.tool_name for step in steps[:3]],
            "review_retrieval_fields": (
                "After retrieval, prefer top-level recovery for empty/high-drop queries, "
                "use passages[].quote for short verbatim snippets, "
                "passages[].confidence_for_grounding for retrieval confidence, and "
                "pubtator.get_review_audit_trail for selected passage audit blocks."
            ),
        },
    )
