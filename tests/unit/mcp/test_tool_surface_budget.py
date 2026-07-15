"""Regression guard for the GeneFoundry Tool-Surface Budget Standard v1.

Measures the ACTUAL advertised tool surface of the deployed (``readonly``) profile the way the
router's survey does (``len(json.dumps(entry)) / 4`` over each ``tools/list`` entry) and pins it,
so the ~73k-token / 87%-outputSchema surface this change removed can never silently creep back.

Two ceilings:

* Per tool: 1,200 tokens (B1). This is a firm rule and is met.
* Whole server: the standard's target is 10,000 tokens (B2). A *fully documented* 35-tool surface
  (every input property carries a description, every required/array property an example, every
  closed vocabulary an enum — Tool-Schema Documentation Standard v1) does not fit under 10,000
  without splitting tools, which is out of scope here (it would force a router drift recapture).
  The Documentation Standard explicitly takes precedence over the budget in that conflict, so this
  test pins the achieved surface below a guard ceiling well under the pre-change 73k. Lowering it
  further is tracked as a follow-up (split the two largest orchestration tools).
"""

from __future__ import annotations

import json

from pubtator_link.mcp.facade import create_pubtator_mcp

MAX_TOOL_TOKENS = 1_200
# Guard ceiling for the readonly surface. NOT the 10k B2 target (see module docstring); it locks in
# the reduction from ~73k and fails loudly on any regression. Achieved surface is ~13.6k.
MAX_SERVER_TOKENS = 14_000


def _tool_entries() -> list[dict[str, object]]:
    mcp = create_pubtator_mcp("readonly")
    tools = mcp._tool_manager._tools.values()
    return [t.to_mcp_tool().model_dump(exclude_none=True, by_alias=True) for t in tools]


def _tokens(obj: object) -> int:
    return len(json.dumps(obj)) // 4


def test_no_tool_exceeds_the_per_tool_budget() -> None:
    over = {
        entry["name"]: _tokens(entry)
        for entry in _tool_entries()
        if _tokens(entry) > MAX_TOOL_TOKENS
    }
    assert not over, f"tools over the {MAX_TOOL_TOKENS}-token B1 budget: {over}"


def test_server_surface_stays_under_the_guard_ceiling() -> None:
    entries = _tool_entries()
    total = _tokens(entries)
    assert total <= MAX_SERVER_TOKENS, (
        f"readonly tool surface is {total} tokens, over the {MAX_SERVER_TOKENS} guard ceiling — "
        "the outputSchema suppression / schema compaction may have regressed"
    )


def test_output_schema_is_suppressed_on_every_tool() -> None:
    # outputSchema is 87% of the pre-change surface and no model reads it; it must stay off.
    with_output_schema = [e["name"] for e in _tool_entries() if e.get("outputSchema")]
    assert not with_output_schema, f"tools still publishing outputSchema: {with_output_schema}"
