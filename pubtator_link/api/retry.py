from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

import httpx


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_ms: int = 500
    max_delay_ms: int = 10_000
    retry_status_codes: set[int] = field(default_factory=lambda: {408, 429, 500, 502, 503, 504})
    respect_retry_after: bool = True


@dataclass(frozen=True)
class RetryAttemptMetadata:
    attempt_count: int
    last_status_code: int | None = None
    retry_after_ms: int | None = None
    backoff_ms: int | None = None
    terminal_reason: str | None = None


def retry_after_ms(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = int(value.strip())
    except ValueError:
        return None
    return max(0, seconds * 1000)


def full_jitter_delay_ms(policy: RetryPolicy, attempt_index: int) -> int:
    cap = min(policy.max_delay_ms, policy.base_delay_ms * (2 ** max(0, attempt_index - 1)))
    return random.randint(0, cap)  # noqa: S311 - retry jitter is not security-sensitive


async def call_with_retries(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    policy: RetryPolicy,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[httpx.Response, RetryAttemptMetadata]:
    attempts = 0
    last_status_code: int | None = None
    last_retry_after_ms: int | None = None
    last_backoff_ms: int | None = None
    while True:
        attempts += 1
        try:
            response = await send()
        except httpx.RequestError:
            if attempts >= policy.max_attempts:
                raise
            last_backoff_ms = full_jitter_delay_ms(policy, attempts)
            await sleep(last_backoff_ms / 1000)
            continue

        last_status_code = response.status_code
        if response.status_code not in policy.retry_status_codes or attempts >= policy.max_attempts:
            return response, RetryAttemptMetadata(
                attempt_count=attempts,
                last_status_code=last_status_code,
                retry_after_ms=last_retry_after_ms,
                backoff_ms=last_backoff_ms,
                terminal_reason=(
                    "retry_exhausted"
                    if response.status_code in policy.retry_status_codes
                    and attempts >= policy.max_attempts
                    else None
                ),
            )

        last_retry_after_ms = retry_after_ms(response) if policy.respect_retry_after else None
        last_backoff_ms = (
            last_retry_after_ms
            if last_retry_after_ms is not None
            else full_jitter_delay_ms(policy, attempts)
        )
        await sleep(last_backoff_ms / 1000)
