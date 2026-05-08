from __future__ import annotations

from pathlib import Path


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
        assert entry.has_output_schema is True
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
        "- Next tools by profile: lean: `pubtator.index_review_evidence`; "
        "full: `pubtator.index_review_evidence`; readonly: None"
    ) in rendered
    assert (
        "- Next tools by profile: lean: `pubtator.record_review_context`, "
        "`pubtator.get_review_audit_trail`; full: `pubtator.record_review_context`, "
        "`pubtator.get_review_audit_trail`; readonly: `pubtator.get_review_audit_trail`"
    ) in rendered


def test_literature_graph_tools_expose_response_mode_and_size_guidance() -> None:
    from pubtator_link.mcp.catalog import build_tool_catalog
    from pubtator_link.mcp.facade import create_pubtator_mcp

    catalog = build_tool_catalog(create_pubtator_mcp(profile="full"), profile="full")
    for name in (
        "pubtator.get_publication_citation_graph",
        "pubtator.find_related_evidence_candidates",
        "pubtator.build_topic_literature_map",
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
    task_schema = catalog["pubtator.workflow_help"].input_schema["properties"]["task"]

    assert task_schema["type"] == "string"
    assert "enum" not in task_schema
