from __future__ import annotations

import re
from pathlib import Path

# ponytail: copy of genefoundry-router scripts/surface.py lead_states_return (D1,
# Tool-Schema Documentation v1.1); re-vendor if the router rule changes.
_LEAD_VERBS = (  # noqa: SIM905 - kept identical to the router source
    "get fetch retrieve list look lookup search find resolve report read predict annotate "
    "compute calculate count summarize summarise map translate convert describe show check "
    "validate classify score rank query browse discover explain compare diff normalize normalise "
    "expand evaluate assess enumerate identify locate export download match suggest recommend "
    "inspect generate render estimate"
).split()
_VERB_LEAD = re.compile(
    rf"^(?:use this (?:tool )?to )?(?:{'|'.join(_LEAD_VERBS)})(?:s|es|ies)?\b", re.IGNORECASE
)
_RETURNS = re.compile(
    r"(?<!not )(?<!n't )(?<!n\u2019t )(?<!never )\breturn(?:s|ed|ing)?\b(?!\s*[~<\d])|\u2192|->",
    re.IGNORECASE,
)
_FIELD_LIST = re.compile(r"\w+\W+\w+[^:]*:\s+[^.;:]+,")
_SENTENCE_END = re.compile(r"(?<!e\.g\.)(?<!i\.e\.)(?<=[.!?])\s+")


def _lead_states_return(description: str) -> bool:
    lead = _SENTENCE_END.split(" ".join(description.split()), maxsplit=1)[0][:300]
    return bool(_VERB_LEAD.match(lead) or _RETURNS.search(lead) or _FIELD_LIST.search(lead))


def test_build_tool_catalog_covers_exact_full_runtime_tools() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="full")
    runtime_tools = set(mcp._tool_manager._tools)
    catalog = build_tool_catalog(mcp, profile="full")

    assert set(catalog) == runtime_tools


def test_tool_catalog_entries_are_llm_usable() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")

    for key, entry in catalog.items():
        assert entry.name == key
        assert entry.description.startswith("Use this when ")
        assert entry.category
        assert entry.profiles
        assert entry.example
        # Tool-Surface Budget Standard v1: outputSchema is suppressed on every tool
        # (output_schema=None), so no catalog entry advertises one.
        assert entry.has_output_schema is False
        assert len(entry.description) <= 420


def test_profile_catalog_next_tools_are_registered_in_profile() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    for profile in ("lean", "full", "readonly"):
        catalog = build_tool_catalog(create_pubtator_mcp(profile=profile), profile=profile)
        names = set(catalog)

        for entry in catalog.values():
            assert set(entry.next_tools) <= names


def test_mcp_tool_catalog_docs_are_generated_from_runtime_catalog() -> None:
    from pubtator_link.mcp.catalog_docs import render_tool_catalog_markdown

    docs_path = Path("docs/mcp-tool-catalog.md")

    assert docs_path.read_text() == render_tool_catalog_markdown()


def test_rendered_catalog_shows_profile_specific_next_tools() -> None:
    from pubtator_link.mcp.catalog_docs import render_tool_catalog_markdown

    rendered = render_tool_catalog_markdown()

    assert (
        "- Next tools by profile: lean: `index_review_evidence`; "
        "full: `index_review_evidence`; readonly: None"
    ) in rendered
    assert (
        "- Next tools by profile: lean: `record_review_context`, "
        "`get_review_audit_trail`; full: `record_review_context`, "
        "`get_review_audit_trail`; readonly: `get_review_audit_trail`"
    ) in rendered


def test_literature_graph_tools_expose_response_mode_and_size_guidance() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    for name in (
        "get_publication_citation_graph",
        "find_related_evidence_candidates",
        "build_topic_literature_map",
    ):
        tool = catalog[name]
        assert "response_mode" in tool.input_schema["properties"]
        assert "response_mode='compact'" in tool.description
        assert "response_size_class" in tool.description
        assert "full can be large" in tool.description


def test_workflow_help_task_schema_accepts_free_form_aliases() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    task_schema = catalog["workflow_help"].input_schema["properties"]["task"]

    assert task_schema["type"] == "string"
    assert "enum" not in task_schema


def test_lead_states_what_is_returned_within_reranker_window() -> None:
    """Rerankers see ~300 description chars; the lead must name what comes back."""
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    leads = {
        "get_publication_passages": ("returns", "full text", "figure", "table"),
        "search_literature": ("returns", "PMID", "title"),
    }
    for name, words in leads.items():
        head = catalog[name].description[:300]
        for word in words:
            assert word in head, (name, word)


def test_every_tool_lead_states_what_is_returned() -> None:
    """D1: every runtime and catalog description's first sentence says what comes back."""
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    mcp = create_pubtator_mcp(profile="full")
    catalog = build_tool_catalog(mcp, profile="full")
    runtime = {name: tool.description or "" for name, tool in mcp._tool_manager._tools.items()}
    failing = [
        name
        for name in sorted(catalog)
        if not (
            _lead_states_return(runtime[name]) and _lead_states_return(catalog[name].description)
        )
    ]
    assert failing == []
    assert all(len(d) <= 420 and d.startswith("Use this when ") for d in runtime.values())
