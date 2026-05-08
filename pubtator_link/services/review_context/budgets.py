from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pubtator_link.models.review_rerag import (
    BudgetSource,
    MaxResponseChars,
    ReviewResponseVerbosity,
)

REVIEW_BATCH_DEFAULT_MAX_CHARS = 24_000
REVIEW_BATCH_DEFAULT_MAX_RESPONSE_CHARS = 48_000
REVIEW_BATCH_MAX_CHARS_CAP = 50_000
REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP = 100_000
AUTO_RESPONSE_BUDGETS: dict[ReviewResponseVerbosity, int] = {
    "lean": 12_000,
    "standard": 24_000,
    "full": 60_000,
}


@dataclass(frozen=True)
class ResolvedBatchBudgets:
    max_chars: int
    max_response_chars: int
    budget_source: BudgetSource


def resolve_max_response_chars(
    value: Any,
    *,
    verbosity: ReviewResponseVerbosity,
) -> int:
    if value is None:
        return AUTO_RESPONSE_BUDGETS[verbosity]
    if isinstance(value, str):
        if value.strip().lower() == "auto":
            return AUTO_RESPONSE_BUDGETS[verbosity]
        try:
            value = int(value.strip())
        except ValueError as exc:
            raise ValueError("max_response_chars must be an integer or 'auto'") from exc
    if not isinstance(value, int):
        raise ValueError("max_response_chars must be an integer or 'auto'")
    if value < 2_000 or value > REVIEW_BATCH_MAX_RESPONSE_CHARS_CAP:
        raise ValueError("max_response_chars must be between 2000 and 100000")
    return value


def resolve_batch_budget_args(
    *,
    max_total_passages: int,
    max_chars_per_passage: int,
    max_chars: int | str | None,
    max_response_chars: MaxResponseChars | str | None,
    verbosity: ReviewResponseVerbosity,
) -> ResolvedBatchBudgets:
    explicit_chars = max_chars is not None
    explicit_response = max_response_chars is not None and not _is_auto_response_budget(
        max_response_chars
    )
    effective_max_chars = (
        _coerce_max_chars(max_chars)
        if explicit_chars
        else min(
            REVIEW_BATCH_MAX_CHARS_CAP,
            max(
                REVIEW_BATCH_DEFAULT_MAX_CHARS,
                max_total_passages * max_chars_per_passage,
            ),
        )
    )
    effective_max_response_chars = resolve_max_response_chars(
        max_response_chars if max_response_chars is not None else "auto",
        verbosity=verbosity,
    )
    budget_source: BudgetSource = "caller" if explicit_chars or explicit_response else "auto_fit"
    return ResolvedBatchBudgets(
        max_chars=effective_max_chars,
        max_response_chars=effective_max_response_chars,
        budget_source=budget_source,
    )


def _is_auto_response_budget(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def _coerce_max_chars(value: int | str | None) -> int:
    if isinstance(value, int):
        result = value
    elif isinstance(value, str):
        result = int(value.strip())
    else:
        result = REVIEW_BATCH_DEFAULT_MAX_CHARS
    if result < 500 or result > REVIEW_BATCH_MAX_CHARS_CAP:
        raise ValueError("max_chars must be between 500 and 50000")
    return result
