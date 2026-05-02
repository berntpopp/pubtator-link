from __future__ import annotations

from pubtator_link.models.review_rerag import PreparationStatus
from pubtator_link.services.provenance import index_snapshot_date as _index_snapshot_date


def index_snapshot_date() -> str:
    """Return the review-index snapshot date label."""
    return _index_snapshot_date()


def retry_after_ms_for_status(status: PreparationStatus) -> int | None:
    """Return a polling hint only while review preparation is active."""
    active = status.queued + status.running
    if active == 0:
        return None
    if active <= 3:
        return 3000
    if active <= 10:
        return 5000
    return 10000
