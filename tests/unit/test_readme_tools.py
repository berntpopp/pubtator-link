"""The README ``## Tools`` table must match the registered tool surface exactly.

GeneFoundry README Standard v1, Rule 6: the table is machine-verified, not
hand-maintained. Adding, renaming, or dropping a tool without updating the README
fails here rather than silently shipping a README that lies about the server.

The live tool list is obtained the same way ``test_tool_names.py`` obtains it —
``create_pubtator_mcp(...).list_tools()`` — so there is no second, hand-copied
source of truth to drift.

Profile: ``readonly`` is pinned deliberately. It is the default
(``DEFAULT_MCP_PROFILE``) and the surface the hosted deployment and the
``genefoundry-router`` fleet baseline harvest, so it is what the README documents.
Pinning it also keeps the assertion deterministic regardless of any
``PUBTATOR_LINK_MCP_PROFILE`` value in the developer's environment or ``.env``.
The write tools that ``lean``/``full`` add are described in prose beneath the
table, not enumerated in it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.mcp.profiles import DEFAULT_MCP_PROFILE

README = Path("README.md")

_TOOLS_HEADING = "## Tools"
_NEXT_HEADING = re.compile(r"^## ", re.M)
# A table row whose first cell is a single backticked tool name: `| `name` | ... |`
_TOOL_ROW = re.compile(r"^\|\s*`([a-z0-9_]+)`\s*\|", re.M)


def _readme_tool_names() -> set[str]:
    text = README.read_text(encoding="utf-8")

    start = text.index(_TOOLS_HEADING) + len(_TOOLS_HEADING)
    rest = text[start:]
    end = _NEXT_HEADING.search(rest)
    section = rest[: end.start()] if end else rest

    return {m.group(1) for m in _TOOL_ROW.finditer(section)}


async def _registered_tool_names() -> set[str]:
    facade: Any = create_pubtator_mcp(profile="readonly")
    return {tool.name for tool in await facade.list_tools()}


async def test_readme_tools_table_matches_registered_tools() -> None:
    documented = _readme_tool_names()
    registered = await _registered_tool_names()

    assert documented, "no tool rows parsed from the README '## Tools' table"

    missing = registered - documented
    extra = documented - registered
    assert not missing, f"tools registered but absent from the README table: {sorted(missing)}"
    assert not extra, f"tools in the README table but not registered: {sorted(extra)}"
    assert documented == registered


async def test_readme_documents_the_default_profile() -> None:
    """The table's profile pin must track the server's actual default."""
    assert DEFAULT_MCP_PROFILE == "readonly"


def test_readme_documents_the_safe_readonly_evidence_contract() -> None:
    """The public README must not reintroduce an unreachable write workflow."""
    text = " ".join(README.read_text(encoding="utf-8").split())

    expected = (
        "`search_literature` → `preflight_review_sources` → `get_publication_passages`",
        "`index_review_evidence` is available only to configured, authenticated "
        "non-readonly profiles.",
        "Candidate variants are not classifications for the query.",
        "compact, cursor-paginated summaries; use "
        "`get_research_session_status` for one session's details.",
    )

    for requirement in expected:
        assert requirement in text
