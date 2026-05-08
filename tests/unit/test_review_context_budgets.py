from __future__ import annotations

import pytest

from pubtator_link.services.review_context.budgets import (
    resolve_batch_budget_args,
    resolve_max_response_chars,
)


def test_resolve_max_response_chars_auto_uses_verbosity_presets() -> None:
    assert resolve_max_response_chars("auto", verbosity="lean") == 12000
    assert resolve_max_response_chars("Auto", verbosity="lean") == 12000
    assert resolve_max_response_chars("auto", verbosity="standard") == 24000
    assert resolve_max_response_chars("auto", verbosity="full") == 60000


def test_resolve_max_response_chars_preserves_numeric_budget() -> None:
    assert resolve_max_response_chars(36000, verbosity="lean") == 36000
    assert resolve_max_response_chars("36000", verbosity="full") == 36000


@pytest.mark.parametrize("value", [1999, 100001, "large"])
def test_resolve_max_response_chars_rejects_invalid_values(value: object) -> None:
    with pytest.raises(ValueError):
        resolve_max_response_chars(value, verbosity="standard")


def test_resolve_batch_budget_args_uses_auto_response_budget() -> None:
    resolved = resolve_batch_budget_args(
        max_total_passages=8,
        max_chars_per_passage=2200,
        max_chars=None,
        max_response_chars="auto",
        verbosity="lean",
    )

    assert resolved.max_chars == 24000
    assert resolved.max_response_chars == 12000
    assert resolved.budget_source == "auto_fit"


def test_resolve_batch_budget_args_preserves_explicit_numeric_budget() -> None:
    resolved = resolve_batch_budget_args(
        max_total_passages=8,
        max_chars_per_passage=2200,
        max_chars=8000,
        max_response_chars=36000,
        verbosity="lean",
    )

    assert resolved.max_chars == 8000
    assert resolved.max_response_chars == 36000
    assert resolved.budget_source == "caller"
