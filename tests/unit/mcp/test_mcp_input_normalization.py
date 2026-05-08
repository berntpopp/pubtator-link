from __future__ import annotations

import pytest

from pubtator_link.mcp.input_normalization import (
    InputNormalizationError,
    normalize_retrieve_review_context_batch_args,
)


def test_normalizes_query_alias_to_queries_list() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "query": "MEFV colchicine"}
    )

    assert args["queries"] == ["MEFV colchicine"]
    assert warnings[0]["field"] == "query"


def test_normalizes_limit_alias_to_max_total_passages() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "queries": ["MEFV"], "limit": 5}
    )

    assert args["max_total_passages"] == 5
    assert warnings[0]["field"] == "limit"


def test_normalizes_enum_casing() -> None:
    args, warnings = normalize_retrieve_review_context_batch_args(
        {"review_id": "r1", "queries": "MEFV", "response_mode": "Quotes"}
    )

    assert args["queries"] == ["MEFV"]
    assert args["response_mode"] == "quotes"
    assert {warning["field"] for warning in warnings} == {"queries", "response_mode"}


def test_retrieve_batch_normalizes_verbosity_casing_and_auto_budget() -> None:
    normalized, warnings = normalize_retrieve_review_context_batch_args(
        {
            "queries": ["MEFV"],
            "verbosity": "Lean",
            "max_response_chars": "Auto",
        }
    )

    assert normalized["verbosity"] == "lean"
    assert normalized["max_response_chars"] == "auto"
    assert any(warning["field"] == "verbosity" for warning in warnings)
    assert any(warning["field"] == "max_response_chars" for warning in warnings)


def test_rejects_ambiguous_query_and_queries() -> None:
    with pytest.raises(InputNormalizationError) as error:
        normalize_retrieve_review_context_batch_args(
            {"review_id": "r1", "query": "a", "queries": ["b"]}
        )

    assert error.value.field_errors[0]["field"] == "queries"


@pytest.mark.parametrize("alias", ["limit", "size"])
def test_rejects_ambiguous_passage_limit_alias(alias: str) -> None:
    with pytest.raises(InputNormalizationError) as error:
        normalize_retrieve_review_context_batch_args(
            {"review_id": "r1", "queries": ["MEFV"], "max_total_passages": 5, alias: 3}
        )

    assert error.value.field_errors[0]["field"] == "max_total_passages"
