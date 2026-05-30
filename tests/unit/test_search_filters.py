import pytest

from pubtator_link.api.search_filters import (
    merge_search_filters,
    merge_search_filters_lenient,
)


@pytest.mark.parametrize("filters", ["not json", "123"])
def test_lenient_search_filter_merge_ignores_malformed_filters(filters: str) -> None:
    merged, warning = merge_search_filters_lenient(
        filters=filters,
        publication_types=None,
        year_min=None,
        year_max=None,
    )

    assert merged is None
    assert warning is not None
    assert "ignored" in warning.lower()


@pytest.mark.parametrize("filters", ["not json", "123"])
def test_strict_search_filter_merge_still_rejects_malformed_filters(filters: str) -> None:
    with pytest.raises(ValueError):
        merge_search_filters(
            filters=filters,
            publication_types=None,
            year_min=None,
            year_max=None,
        )


def test_lenient_search_filter_merge_keeps_conflicts_as_errors() -> None:
    with pytest.raises(ValueError, match="type"):
        merge_search_filters_lenient(
            filters='{"type":["Review"]}',
            publication_types=["Guideline"],
            year_min=None,
            year_max=None,
        )
