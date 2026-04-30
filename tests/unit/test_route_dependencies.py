from types import SimpleNamespace
from typing import Any

import pytest

from pubtator_link.api.routes import dependencies


@pytest.mark.asyncio
async def test_get_review_pool_leaves_headroom_for_preparation_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    pool = object()

    async def create_pool(**kwargs: Any) -> object:
        captured_kwargs.update(kwargs)
        return pool

    monkeypatch.setattr(dependencies, "_review_pool", None)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=3,
        ),
    )
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)

    result = await dependencies.get_review_pool()

    assert result is pool
    assert captured_kwargs == {
        "dsn": "postgresql://user:pass@localhost:5434/pubtator_link",
        "min_size": 1,
        "max_size": 8,
    }


@pytest.mark.asyncio
async def test_get_review_pool_keeps_spare_connections_when_concurrency_is_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def create_pool(**kwargs: Any) -> object:
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr(dependencies, "_review_pool", None)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=0,
        ),
    )
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)

    await dependencies.get_review_pool()

    assert captured_kwargs["max_size"] == 2


@pytest.mark.asyncio
async def test_cleanup_dependencies_ignores_stale_closed_loop_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StaleClient:
        async def close(self) -> None:
            raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(dependencies, "_api_client", StaleClient())
    monkeypatch.setattr(dependencies, "_review_queue", None)
    monkeypatch.setattr(dependencies, "_review_pool", None)

    await dependencies.cleanup_dependencies()

    assert dependencies._api_client is None
