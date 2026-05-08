from __future__ import annotations

import pytest

from pubtator_link.services.review_context.pagination import (
    InspectReviewIndexCursor,
    decode_inspect_review_index_cursor,
    encode_inspect_review_index_cursor,
    inspect_review_index_scope_hash,
)


def test_inspect_review_index_cursor_round_trips_offsets_and_scope() -> None:
    scope_hash = inspect_review_index_scope_hash(
        review_id="review-1",
        session_id="session-1",
        pmids=["222", "111"],
    )
    token = encode_inspect_review_index_cursor(
        InspectReviewIndexCursor(
            scope_hash=scope_hash,
            source_offset=50,
            failed_source_offset=3,
        )
    )

    decoded = decode_inspect_review_index_cursor(
        token,
        expected_scope_hash=scope_hash,
    )

    assert decoded.source_offset == 50
    assert decoded.failed_source_offset == 3


def test_inspect_review_index_cursor_rejects_wrong_scope() -> None:
    token = encode_inspect_review_index_cursor(
        InspectReviewIndexCursor(
            scope_hash="aaaaaaaaaaaa",
            source_offset=0,
            failed_source_offset=0,
        )
    )

    with pytest.raises(ValueError, match="cursor scope does not match request"):
        decode_inspect_review_index_cursor(
            token,
            expected_scope_hash="bbbbbbbbbbbb",
        )


def test_inspect_review_index_cursor_rejects_invalid_token() -> None:
    with pytest.raises(ValueError, match="invalid inspect_review_index cursor"):
        decode_inspect_review_index_cursor("not-valid", expected_scope_hash="aaaaaaaaaaaa")
