from __future__ import annotations

import httpx
import pytest

from pubtator_link.api.retry import (
    RetryPolicy,
    call_with_retries,
    full_jitter_delay_ms,
    retry_after_ms,
)


def test_retry_after_ms_parses_seconds_header() -> None:
    response = httpx.Response(503, headers={"Retry-After": "2"})

    assert retry_after_ms(response) == 2000


def test_retry_after_ms_ignores_invalid_header() -> None:
    response = httpx.Response(503, headers={"Retry-After": "Fri, 01 May 2026 10:00:00 GMT"})

    assert retry_after_ms(response) is None


def test_full_jitter_delay_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    observed_caps: list[int] = []

    def fake_randint(low: int, high: int) -> int:
        observed_caps.append(high)
        return high

    monkeypatch.setattr("pubtator_link.api.retry.random.randint", fake_randint)

    policy = RetryPolicy(base_delay_ms=500, max_delay_ms=750)

    assert full_jitter_delay_ms(policy, attempt_index=3) == 750
    assert observed_caps == [750]


@pytest.mark.asyncio
async def test_call_with_retries_uses_retry_after_before_success() -> None:
    responses = [
        httpx.Response(503, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"ok": True}),
    ]
    sleeps: list[float] = []

    async def send() -> httpx.Response:
        return responses.pop(0)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    response, metadata = await call_with_retries(
        send,
        policy=RetryPolicy(max_attempts=3),
        sleep=fake_sleep,
    )

    assert response.status_code == 200
    assert sleeps == [1.0]
    assert metadata.attempt_count == 2
    assert metadata.retry_after_ms == 1000
    assert metadata.backoff_ms == 1000


@pytest.mark.asyncio
async def test_call_with_retries_returns_terminal_metadata_when_exhausted() -> None:
    attempts = 0

    async def send() -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503)

    async def fake_sleep(_seconds: float) -> None:
        return None

    response, metadata = await call_with_retries(
        send,
        policy=RetryPolicy(max_attempts=2, base_delay_ms=0),
        sleep=fake_sleep,
    )

    assert response.status_code == 503
    assert attempts == 2
    assert metadata.terminal_reason == "retry_exhausted"
