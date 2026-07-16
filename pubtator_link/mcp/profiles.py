from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

MCPToolProfile = Literal["lean", "full", "readonly"]

DEFAULT_MCP_PROFILE: MCPToolProfile = "readonly"

LEAN_TOOLS: tuple[str, ...] = (
    "workflow_help",
    "get_server_capabilities",
    "diagnostics",
    "search_literature",
    "search_guidelines",
    "search_biomedical_entities",
    "get_variant_evidence",
    "get_publication_metadata",
    "get_publication_passages",
    "get_publication_citation_graph",
    "find_related_evidence_candidates",
    "preflight_review_sources",
    "index_review_evidence",
    "inspect_review_index",
    "ground_question",
    "get_review_context_batch",
    "get_review_audit_trail",
    "record_review_context",
)

FULL_ONLY_TOOLS: tuple[str, ...] = (
    "review_quickstart",
    "convert_article_ids",
    "get_mesh",
    "get_citation",
    "find_related_articles",
    "suggest_corpus",
    "build_topic_literature_map",
    "get_publication_annotations",
    "estimate_publication_context",
    "get_pmc_annotations",
    "find_entity_relations",
    "submit_text_annotation",
    "get_text_annotation_results",
    "get_review_context",
    "get_review_passages_by_id",
    "get_neighboring_review_passages",
    "export_review_audit_bundle",
    "list_review_indexes",
    "get_review_index_summary",
    "add_evidence_certainty",
    "list_evidence_certainty",
    "get_evidence_certainty",
    "stage_research_session",
    "get_research_session_status",
    "list_research_sessions",
)

WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "index_review_evidence",
        "ground_question",
        "record_review_context",
        "submit_text_annotation",
        "export_review_audit_bundle",
        "add_evidence_certainty",
        "stage_research_session",
        "review_quickstart",
    }
)

READONLY_TOOLS: tuple[str, ...] = tuple(
    name for name in (*LEAN_TOOLS, *FULL_ONLY_TOOLS) if name not in WRITE_TOOLS
)

_PROFILE_SAFE_LLM_CONTEXT_FIELDS = frozenset(
    {
        "context_id",
        "review_id",
        "session_id",
        "kind",
        "question_hash",
        "selected_pmids",
        "rejected_pmids",
        "preferred_entity_ids",
        "selected_passage_ids",
        "audit_passage_ids",
        "last_next_commands",
        "stable_citation_keys",
        "cache_key",
        "token_estimate",
        "created_at",
        "updated_at",
    }
)


def normalize_mcp_profile(value: str | None) -> MCPToolProfile:
    if value is None or value == "":
        return DEFAULT_MCP_PROFILE
    if value in ("lean", "full", "readonly"):
        return cast(MCPToolProfile, value)
    raise ValueError("mcp_profile must be one of: lean, full, readonly")


def tool_names_for_profile(profile: MCPToolProfile) -> set[str]:
    if profile == "lean":
        return set(LEAN_TOOLS)
    if profile == "readonly":
        return set(READONLY_TOOLS)
    return {*LEAN_TOOLS, *FULL_ONLY_TOOLS}


def reachable_tools(profile: MCPToolProfile, preferred: Sequence[str]) -> list[str]:
    """Keep preferred tool order while removing tools absent from a profile.

    This is intentionally based on the profile inventory instead of a second,
    hand-maintained list of writes. Callers use it while constructing a
    workflow or a follow-up hint, before exposing the hint to an MCP client.
    """
    available = tool_names_for_profile(profile)
    return [tool for tool in preferred if tool in available]


def filter_reachable_hints[T](
    profile: MCPToolProfile,
    payload: T,
    *,
    scope: Literal["hints", "llm_context"] = "hints",
) -> T:
    """Remove unavailable MCP tool references from structured follow-up hints.

    Workflows must be built from :func:`reachable_tools` before their steps are
    numbered. This helper only filters typed ``next_tools``/``next_commands``
    fields, never arbitrary user or retrieved evidence text. The LLM-context
    scope projects persisted free-form fields away for non-full profiles before
    applying the same typed hint filter.
    """
    available = tool_names_for_profile(profile)
    known_tools = tool_names_for_profile("full")

    if scope == "llm_context" and profile != "full" and isinstance(payload, Mapping):
        payload = cast(
            T,
            {
                key: value
                for key, value in payload.items()
                if key in _PROFILE_SAFE_LLM_CONTEXT_FIELDS
            },
        )

    def command_tool_name(value: str) -> str | None:
        candidate = value.partition("(")[0]
        return candidate if candidate in known_tools else None

    def visit(value: Any) -> Any:
        if isinstance(value, Mapping):
            filtered = dict(value)
            for key, item in value.items():
                if key in {
                    "last_next_commands",
                    "next_tools",
                    "next_commands",
                    "next_steps",
                } and isinstance(item, list):
                    filtered[key] = filter_hints(item)
                    continue
                filtered[key] = visit(item)
            return filtered
        if isinstance(value, list):
            return [visit(item) for item in value]
        return value

    def filter_hints(values: list[Any]) -> list[Any]:
        filtered: list[Any] = []
        for value in values:
            if isinstance(value, str):
                tool = command_tool_name(value)
                if tool is not None and tool not in available:
                    continue
                if value in known_tools and value not in available:
                    continue
                if any(tool not in available and tool in value for tool in known_tools):
                    continue
                filtered.append(value)
                continue
            if isinstance(value, Mapping):
                tool = value.get("tool")
                if isinstance(tool, str) and tool in known_tools and tool not in available:
                    continue
            filtered.append(visit(value))
        return filtered

    return cast(T, visit(payload))
