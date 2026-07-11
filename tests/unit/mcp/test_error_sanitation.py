"""Unit contract for the error-message code-point sanitizer.

``sanitize_message`` is the shared primitive routed over every caller-visible
message/error/diagnostics/warning string on the error path. It strips the fence's
forbidden control/zero-width/bidi/NUL code points and length-caps, so a hostile
upstream (or a caller-influenced 4xx/5xx body reflected into ``str(exc)``) cannot
smuggle those code points into a caller-visible field.
"""

from __future__ import annotations

from pubtator_link.mcp.untrusted_content import (
    FORBIDDEN_CODEPOINTS,
    MAX_MESSAGE_CHARS,
    sanitize_message,
)

# NUL, zero-width joiner, byte-order mark, right-to-left override.
_HOSTILE_CODEPOINTS = "\x00‍﻿‮"


def test_sanitize_message_strips_all_forbidden_codepoints() -> None:
    dirty = f"before{_HOSTILE_CODEPOINTS}after"
    clean = sanitize_message(dirty)
    assert clean == "beforeafter"
    assert not any(ord(char) in FORBIDDEN_CODEPOINTS for char in clean)


def test_sanitize_message_removes_each_named_codepoint() -> None:
    for char in _HOSTILE_CODEPOINTS:
        assert char not in sanitize_message(f"x{char}y")


def test_sanitize_message_preserves_ordinary_prose_and_scientific_symbols() -> None:
    # Tabs, newlines and scientific symbols are NOT in the forbidden set.
    prose = "p.Gly12Asp\tΔG = −1.2 kcal/mol\nBRCA1"
    assert sanitize_message(prose) == prose


def test_sanitize_message_length_caps_at_the_fleet_norm() -> None:
    assert MAX_MESSAGE_CHARS == 280
    capped = sanitize_message("A" * 1000)
    assert len(capped) == 280
    assert capped == "A" * 280
