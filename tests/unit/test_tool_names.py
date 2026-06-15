"""Tool-name compliance with the GeneFoundry Tool-Naming Standard v1.

Every registered tool must be unprefixed, snake_case, <= 50 chars, and (where a
canonical read verb is a faithful fit) start with a canonical verb so it composes
cleanly behind the ``genefoundry-router`` gateway, which mounts this server under
the ``pubtator`` namespace (tools surface as ``pubtator_<tool>``). Guards against
future drift. See issue berntpopp/pubtator-link#57.

Per issue #57, a set of genuinely non-CRUD action / orchestration / meta tools
(``build``/``index``/``submit``/``add``/``record``/``stage``/``preflight``/
``suggest``/``ground``/``export``/``estimate``/``inspect``/``convert`` plus the
help and diagnostics tools) keep their action verbs; the mandatory breaking
change in v2.0.0 is the ``pubtator_`` self-prefix drop, and verb harmonization
for these action tools is deferred to a fleet-level decision. They are recorded
in ``_ACTION_VERB_EXEMPT`` below so the lint can pass while still guarding every
tool against self-prefixing, the charset/length rule, and accidental new
non-canonical verbs.
"""

from __future__ import annotations

import re
from typing import Any

from pubtator_link.mcp.facade import create_pubtator_mcp

_NAME_RE = re.compile(r"^[a-z0-9_]{1,50}$")
_CANONICAL_VERBS = frozenset({"get", "search", "list", "resolve", "find", "compare", "compute"})
_NAMESPACE = "pubtator"

# Issue #57-sanctioned exemptions: genuine non-CRUD action / orchestration / meta
# tools whose verbs are intentionally outside the canonical read-verb set. New
# names must NOT be added here without a corresponding standards decision.
_ACTION_VERB_EXEMPT = frozenset(
    {
        "add_evidence_certainty",
        "build_topic_literature_map",
        "convert_article_ids",
        "diagnostics",
        "estimate_publication_context",
        "export_review_audit_bundle",
        "ground_question",
        "index_review_evidence",
        "inspect_review_index",
        "preflight_review_sources",
        "record_review_context",
        "review_quickstart",
        "stage_research_session",
        "submit_text_annotation",
        "suggest_corpus",
        "workflow_help",
    }
)


async def _facade_tool_names() -> list[str]:
    facade: Any = create_pubtator_mcp(profile="full")
    return sorted(t.name for t in await facade.list_tools())


async def test_tool_names_conform_to_standard_v1() -> None:
    names = await _facade_tool_names()
    assert names, "no tools registered on the facade"
    for name in names:
        assert _NAME_RE.match(name), f"{name!r} must match ^[a-z0-9_]{{1,50}}$"
        assert not name.startswith(f"{_NAMESPACE}_"), (
            f"{name!r} must not self-prefix the '{_NAMESPACE}' namespace "
            "token — the gateway adds it"
        )
        if name in _ACTION_VERB_EXEMPT:
            continue
        assert name.split("_", 1)[0] in _CANONICAL_VERBS, (
            f"{name!r} must start with a canonical verb {sorted(_CANONICAL_VERBS)} "
            f"or be listed in _ACTION_VERB_EXEMPT (see issue #{57})"
        )


async def test_action_verb_exemptions_are_all_registered() -> None:
    """Keep the exemption allowlist honest: no stale entries."""
    names = set(await _facade_tool_names())
    stale = _ACTION_VERB_EXEMPT - names
    assert not stale, f"stale _ACTION_VERB_EXEMPT entries no longer registered: {sorted(stale)}"
