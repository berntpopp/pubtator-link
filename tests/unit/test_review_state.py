from pubtator_link.models.review_rerag import PreparationStatus
from pubtator_link.services.review_state import index_snapshot_date, retry_after_ms_for_status


def test_retry_after_ms_is_none_for_terminal_status() -> None:
    status = PreparationStatus(complete=2, failed=1, queued=0, running=0)

    assert retry_after_ms_for_status(status) is None


def test_retry_after_ms_is_short_for_small_active_sets() -> None:
    status = PreparationStatus(complete=1, queued=1, running=1)

    assert retry_after_ms_for_status(status) == 3000


def test_retry_after_ms_is_medium_for_moderate_active_sets() -> None:
    status = PreparationStatus(queued=6, running=2)

    assert retry_after_ms_for_status(status) == 5000


def test_retry_after_ms_scales_large_active_sets() -> None:
    status = PreparationStatus(queued=29, running=1)

    assert retry_after_ms_for_status(status) == 10000


def test_index_snapshot_date_is_iso_date() -> None:
    value = index_snapshot_date()

    assert len(value) == 10
    assert value.count("-") == 2
