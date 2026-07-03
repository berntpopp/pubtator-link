"""Tool-name compliance with the GeneFoundry Tool-Naming Standard v1.1.

Every registered tool must be unprefixed, snake_case, <= 50 chars, and (where a
canonical read verb is a faithful fit) start with a canonical verb so it composes
cleanly behind the ``genefoundry-router`` gateway, which mounts this server under
the ``pubtator`` namespace (tools surface as ``pubtator_<tool>``). Guards against
future drift. See issue berntpopp/pubtator-link#57.

**Ratified verb canon (v1.1):**

  Tier-1 (universal read/query): get, search, list, resolve, find, compare,
  compute, map
  Tier-2 (sanctioned action/compute): predict, annotate, recode, liftover,
  analyze, score, submit, export, generate, download

**Ops/meta carve-out (Standard v1.1 §ops/meta):** tools tagged ``ops`` or
``meta`` at source skip the verb rule (charset/length/no-self-prefix still
apply). ``_META_TOOL_NAMES`` below is only a stale-guard list used to assert
that the known operational/help tools are registered *and* actually carry
the carve-out tag — the exemption itself is tag-based, not name-based.

**Per-tool orchestration allowlist (``_ACTION_VERB_EXEMPT``):** a documented
set of genuine orchestration / workflow tools whose verbs (build/index/stage/
ground/preflight/record/estimate/inspect/convert/suggest/add) are intentionally
outside both the Tier-1 and Tier-2 canon. Per issue #57, a fleet-level rename
decision is deferred; no new entries may be added without a standards decision.
``submit`` and ``export`` moved from this list to Tier-2 (v1.1).
``diagnostics``, ``workflow_help``, and ``review_quickstart`` are tagged
``meta`` at source and exempted via the tag-based ops/meta carve-out (v1.1).
"""

from __future__ import annotations

import re
from typing import Any

from pubtator_link.mcp.facade import create_pubtator_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
# Tier-1: universal read/query canon (Tool-Naming Standard v1.1, ratified 2026-06-30)
_CANONICAL_VERBS = frozenset(
    {"get", "search", "list", "resolve", "find", "compare", "compute", "map"}
)
# Tier-2: sanctioned domain action/compute verbs (v1.1)
_TIER2_VERBS = frozenset(
    {
        "predict",
        "annotate",
        "recode",
        "liftover",
        "analyze",
        "score",
        "submit",
        "export",
        "generate",
        "download",
    }
)
_NAMESPACE = "pubtator"

# Ops/meta carve-out (Standard v1.1 §ops/meta tag carve-out): tools whose MCP
# ``tags`` intersect this set are exempt from the verb rule.
_META_TAGS = frozenset({"ops", "meta"})

# Stale-guard only: the operational, help, and onboarding tools that are
# expected to carry the ``meta`` tag at source. Used by
# ``test_action_verb_exemptions_are_all_registered`` to assert they are both
# registered and actually tagged — the exemption check itself is tag-based.
_META_TOOL_NAMES = frozenset(
    {
        "diagnostics",  # meta: subsystem status and recovery
        "review_quickstart",  # meta: onboarding / quickstart workflow
        "workflow_help",  # meta: canonical task-specific workflow guidance
    }
)

# Issue #57-sanctioned per-tool orchestration exemptions: genuine non-CRUD
# action / orchestration tools whose verbs are intentionally outside both
# Tier-1 and Tier-2 of the canonical read-verb set. New names must NOT be
# added here without a corresponding standards decision.
# ``submit`` (→ Tier-2) and ``export`` (→ Tier-2) were removed in v1.1.
# ``diagnostics``, ``workflow_help``, ``review_quickstart`` moved to
# ``_META_TOOL_NAMES`` above (v1.1 ops/meta carve-out).
_ACTION_VERB_EXEMPT = frozenset(
    {
        "add_evidence_certainty",  # verb 'add'      — evidence management
        "build_topic_literature_map",  # verb 'build'    — corpus orchestration
        "convert_article_ids",  # verb 'convert'  — ID translation
        "estimate_publication_context",  # verb 'estimate' — context sizing
        "ground_question",  # verb 'ground'   — RAG grounding
        "index_review_evidence",  # verb 'index'    — indexing operation
        "inspect_review_index",  # verb 'inspect'  — index introspection
        "preflight_review_sources",  # verb 'preflight'— pre-flight check
        "record_review_context",  # verb 'record'   — context recording
        "stage_research_session",  # verb 'stage'    — session staging
        "suggest_corpus",  # verb 'suggest'  — corpus suggestion
    }
)


async def _facade_tools() -> list[Any]:
    facade: Any = create_pubtator_mcp(profile="full")
    return sorted(await facade.list_tools(), key=lambda t: t.name)


async def test_tool_names_conform_to_standard_v1() -> None:
    tools = await _facade_tools()
    assert tools, "no tools registered on the facade"
    _all_verbs = _CANONICAL_VERBS | _TIER2_VERBS
    for tool in tools:
        name = tool.name
        assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
        assert not name.startswith(f"{_NAMESPACE}_"), (
            f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace "
            "token — the gateway adds it"
        )
        tool_tags = set(getattr(tool, "tags", set()) or set())
        if tool_tags & _META_TAGS or name in _ACTION_VERB_EXEMPT:
            continue
        assert name.split("_", 1)[0] in _all_verbs, (
            f"{name!r} must start with a Tier-1 or Tier-2 canonical verb "
            f"{sorted(_all_verbs)}, carry an 'ops'/'meta' tag, "
            f"or be listed in _ACTION_VERB_EXEMPT (see issue #57)"
        )


async def test_action_verb_exemptions_are_all_registered() -> None:
    """Keep the exemption allowlists honest: no stale entries."""
    tools = await _facade_tools()
    names = {t.name for t in tools}
    stale = _ACTION_VERB_EXEMPT - names
    assert not stale, f"stale _ACTION_VERB_EXEMPT entries no longer registered: {sorted(stale)}"
    stale_meta = _META_TOOL_NAMES - names
    assert not stale_meta, (
        f"stale _META_TOOL_NAMES entries no longer registered: {sorted(stale_meta)}"
    )

    tools_by_name = {t.name: t for t in tools}
    for meta_name in sorted(_META_TOOL_NAMES):
        tool_tags = set(getattr(tools_by_name[meta_name], "tags", set()) or set())
        assert tool_tags & _META_TAGS, (
            f"{meta_name!r} is a designated ops/meta tool but carries no "
            f"'ops'/'meta' tag (tags={sorted(tool_tags)}); tag it at source"
        )
