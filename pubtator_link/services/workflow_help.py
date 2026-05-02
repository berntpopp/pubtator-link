from __future__ import annotations

from pubtator_link.models.workflow_help import (
    WorkflowFallback,
    WorkflowHelpResponse,
    WorkflowStep,
    WorkflowTask,
)


class WorkflowHelpService:
    """Return compact in-band workflow guidance for LLM consumers."""

    def get_help(self, task: WorkflowTask = "clinical_genetics_review") -> WorkflowHelpResponse:
        if task == "entity_discovery":
            return self._entity_discovery()
        if task == "citation_audit":
            return self._citation_audit()
        return self._clinical_or_literature_review(task)

    def _clinical_or_literature_review(self, task: WorkflowTask) -> WorkflowHelpResponse:
        steps = [
            WorkflowStep(
                order=1,
                tool_name="pubtator.search_biomedical_entities",
                purpose="Resolve canonical entity IDs for genes, diseases, chemicals, and variants.",
            ),
            WorkflowStep(
                order=2,
                tool_name="pubtator.search_literature",
                purpose="Find candidate PMIDs with compact results and optional metadata.",
                key_args={"metadata": "basic", "coverage": "preflight"},
            ),
            WorkflowStep(
                order=3,
                tool_name="pubtator.get_publication_metadata",
                purpose="Fetch citation-grade author and journal metadata for selected PMIDs.",
            ),
            WorkflowStep(
                order=4,
                tool_name="pubtator.index_review_evidence",
                purpose="Prepare the selected corpus for review-scoped retrieval.",
            ),
            WorkflowStep(
                order=5,
                tool_name="pubtator.inspect_review_index",
                purpose="Verify indexed coverage, source status, and sample passages.",
            ),
            WorkflowStep(
                order=6,
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
                tool_name="pubtator.lookup_mesh",
                purpose="Normalize disease and phenotype vocabulary to MeSH descriptors.",
            ),
            WorkflowStep(
                order=3,
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
        _meta={"next_commands": [step.tool_name for step in steps[:3]]},
    )
