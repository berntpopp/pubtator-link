"""Every advertised PMID input carries the runtime's PMID pattern (Contract-Truth).

An agent builds calls from the schema: a PMID field advertised as "any string" while the
runtime only accepts numeric PMIDs is a schema more permissive than the runtime.
"""

from __future__ import annotations

import re
from typing import Any, get_args

import pytest
from fastmcp import Client

from pubtator_link.mcp.argument_aliases import ARTICLE_ID_PATTERN, _id_form
from pubtator_link.mcp.facade import create_pubtator_mcp
from pubtator_link.mcp.profiles import MCPToolProfile
from pubtator_link.models.literature_graph import PMID_PATTERN, normalize_pmid

# PMID-count knobs (integers), not PMID values.
_NOT_PMID_VALUES = re.compile(r"^(max_|min_|n_|sample_per_|resolve_)")


def _pmid_value_schemas() -> list[tuple[str, str, str, dict[str, Any]]]:
    cases = []
    for profile in get_args(MCPToolProfile):
        mcp = create_pubtator_mcp(profile=profile)
        for name, tool in sorted(mcp._tool_manager._tools.items()):
            for param, schema in tool.parameters.get("properties", {}).items():
                if "pmid" not in param.lower() or _NOT_PMID_VALUES.match(param):
                    continue
                branches = schema.get("anyOf", [schema])
                value = next(b for b in branches if b.get("type") in ("string", "array"))
                cases.append((profile, name, param, value.get("items", value)))
    return cases


_CASES = _pmid_value_schemas()
# Entry-point tools also take a PMCID/DOI and convert it (router #319).
_ARTICLE_ID_TOOLS = {
    ("generate_topic_literature_map", "pmids"),
    ("compute_publication_context", "pmids"),
    ("find_related_articles", "pmids"),
    ("find_related_evidence_candidates", "pmid"),
    ("get_publication_annotations", "pmids"),
    ("get_publication_citation_graph", "pmid"),
    ("get_publication_metadata", "pmids"),
    ("get_publication_passages", "pmids"),
}


def test_glob_found_every_pmid_parameter() -> None:
    # 20 PMID-valued parameters across 16 tools in the full profile (2026-11-13).
    assert len({(t, p) for _, t, p, _ in _CASES}) >= 20


@pytest.mark.parametrize(("profile", "tool", "param", "schema"), _CASES)
def test_pmid_parameter_advertises_runtime_pattern(
    profile: str, tool: str, param: str, schema: dict[str, Any]
) -> None:
    assert schema.get("type") == "string", f"{profile}:{tool}.{param}"
    expected = ARTICLE_ID_PATTERN if (tool, param) in _ARTICLE_ID_TOOLS else PMID_PATTERN
    assert schema.get("pattern") == expected, f"{profile}:{tool}.{param}"


_PARTITION = [
    ("25741868", True),
    ("0", True),
    ("PMID:123", True),
    ("pmid: 123", True),
    (" 123 ", True),
    ("9" * 40, True),
    ("", False),
    ("   ", False),
    ("abc", False),
    ("123abc", False),
    ("abc123", False),
    ("PMID:", False),
    ("PMID 123", False),
    ("12 34", False),
    ("-1", False),
    ("1.5", False),
    ("\u0661\u0662\u0663", False),  # Arabic-Indic digits: str.isdigit() is True
    ("\u00b2", False),  # superscript two: str.isdigit() is True
    ("\uff11\uff12", False),  # fullwidth digits
]


@pytest.mark.parametrize(("value", "accepted"), _PARTITION)
def test_schema_pattern_and_runtime_partition_agree(value: str, accepted: bool) -> None:
    assert (re.search(PMID_PATTERN, value) is not None) is accepted
    try:
        normalize_pmid(value)
        runtime_accepts = True
    except ValueError:
        runtime_accepts = False
    assert runtime_accepts is accepted


@pytest.mark.parametrize("bad", ["abc", "\u0661\u0662\u0663"])
async def test_schema_rejected_pmid_is_a_named_field_error(bad: str) -> None:
    mcp = create_pubtator_mcp(profile="full")
    async with Client(mcp) as client:
        result = await client.call_tool(
            "get_publication_metadata", {"pmids": [bad]}, raise_on_error=False
        )
    payload = result.structured_content
    assert result.is_error is True
    assert isinstance(payload, dict)
    assert payload["error_code"] == "invalid_input"
    assert "pmids" in {e["field"] for e in payload.get("field_errors") or []}


@pytest.mark.parametrize(
    "tool", ["get_publication_citation_graph", "find_related_evidence_candidates"]
)
async def test_single_pmid_tools_give_the_same_pmid_reason(tool: str) -> None:
    mcp = create_pubtator_mcp(profile="full")
    async with Client(mcp) as client:
        result = await client.call_tool(tool, {"pmid": "abc"}, raise_on_error=False)
    payload = result.structured_content
    assert result.is_error is True
    assert isinstance(payload, dict)
    assert payload["field_errors"] == [
        {"field": "pmid", "reason": "PMIDs must be ASCII digits 0-9 (optionally 'PMID:'-prefixed)."}
    ]


_ARTICLE_PARTITION = [
    *_PARTITION,
    ("PMC3518823", True),
    (" pmc3518823 ", True),
    ("10.1038/ng.2500", True),
    ("doi: 10.1038/NG.2500", True),
    ("PMC", False),
    ("PMC12x", False),
    ("PMC\u0661", False),
    ("PMC" + "9" * 13, False),
    ("10.12/x", False),
    ("10.1038/ ng", False),
    ("https://doi.org/10.1038/ng.2500", False),
]


@pytest.mark.parametrize(("value", "accepted"), _ARTICLE_PARTITION)
def test_article_id_schema_pattern_and_runtime_shape_agree(value: str, accepted: bool) -> None:
    try:
        normalize_pmid(value)
        runtime_accepts = True
    except ValueError:
        runtime_accepts = _id_form(value) is not None
    assert (re.search(ARTICLE_ID_PATTERN, value) is not None) is accepted
    assert runtime_accepts is accepted
