from __future__ import annotations

import pytest

from pubtator_link.services.review_context.pagination import (
    InspectReviewIndexCursor,
    decode_get_review_index_status_cursor,
    encode_get_review_index_status_cursor,
    get_review_index_status_scope_hash,
)


def test_get_review_index_status_cursor_round_trips_offsets_and_scope() -> None:
    scope_hash = get_review_index_status_scope_hash(
        review_id="review-1",
        session_id="session-1",
        pmids=["222", "111"],
    )
    token = encode_get_review_index_status_cursor(
        InspectReviewIndexCursor(
            scope_hash=scope_hash,
            source_offset=50,
            failed_source_offset=3,
        )
    )

    decoded = decode_get_review_index_status_cursor(
        token,
        expected_scope_hash=scope_hash,
    )

    assert decoded.source_offset == 50
    assert decoded.failed_source_offset == 3


def test_get_review_index_status_cursor_rejects_wrong_scope() -> None:
    token = encode_get_review_index_status_cursor(
        InspectReviewIndexCursor(
            scope_hash="aaaaaaaaaaaa",
            source_offset=0,
            failed_source_offset=0,
        )
    )

    with pytest.raises(ValueError, match="cursor scope does not match request"):
        decode_get_review_index_status_cursor(
            token,
            expected_scope_hash="bbbbbbbbbbbb",
        )


def test_get_review_index_status_cursor_rejects_invalid_token() -> None:
    with pytest.raises(ValueError, match="invalid get_review_index_status cursor"):
        decode_get_review_index_status_cursor("not-valid", expected_scope_hash="aaaaaaaaaaaa")
