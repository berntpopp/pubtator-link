from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request

from pubtator_link import server_manager
from pubtator_link.api.routes import dependencies


class CloseableClient:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class CloseablePool:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class StoppableQueue:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FailingStartQueue(StoppableQueue):
    async def start(self) -> None:
        self.started = True
        raise RuntimeError("queue startup failed")


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
async def test_create_app_resources_builds_core_services_without_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    logger = object()

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(
        dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger)
    )
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies, "review_rerag_config", SimpleNamespace(database_url=None))

    resources = await dependencies.create_app_resources(logger=logger)

    assert resources.logger is logger
    assert resources.api_client is client
    assert resources.publication_service == ("pub", client, logger)
    assert resources.publication_passage_service == ("passages", ("pub", client, logger))
    assert resources.review_pool is None
    assert resources.review_repository is None
    assert resources.review_queue is None
    assert resources.review_context_service is None


@pytest.mark.asyncio
async def test_create_app_resources_builds_review_resources_with_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    pool = CloseablePool()
    queue = StoppableQueue()
    logger = object()
    captured_pool_kwargs: dict[str, Any] = {}

    async def create_pool(**kwargs: Any) -> CloseablePool:
        captured_pool_kwargs.update(kwargs)
        return pool

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(
        dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger)
    )
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=2,
        ),
    )
    monkeypatch.setattr(dependencies, "PostgresReviewReragRepository", lambda pool: ("repo", pool))
    monkeypatch.setattr(
        dependencies,
        "FullTextPreparationService",
        lambda config, repository, pubtator_client, logger: (
            "prep",
            config,
            repository,
            pubtator_client,
            logger,
        ),
    )
    monkeypatch.setattr(
        dependencies,
        "ReviewPreparationQueue",
        lambda config, repository, preparation, logger: queue,
    )
    monkeypatch.setattr(
        dependencies, "ReviewContextService", lambda repository: ("context", repository)
    )

    resources = await dependencies.create_app_resources(logger=logger)

    assert resources.review_pool is pool
    assert resources.review_repository == ("repo", pool)
    assert resources.review_queue is queue
    assert resources.review_context_service == ("context", ("repo", pool))
    assert captured_pool_kwargs == {
        "dsn": "postgresql://user:pass@localhost:5434/pubtator_link",
        "min_size": 1,
        "max_size": 6,
    }


@pytest.mark.asyncio
async def test_create_app_resources_runs_migrations_before_review_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    client = CloseableClient()
    pool = CloseablePool()
    queue = StoppableQueue()

    async def apply_migrations(database_url: str | None = None) -> list[str]:
        calls.append(f"migrate:{database_url}")
        return ["0002_review_schema_drift_repair"]

    async def inspect_review_schema(database_url: str | None = None) -> object:
        calls.append(f"inspect:{database_url}")
        return SimpleNamespace(
            connected=True,
            current=True,
            missing_tables=[],
            missing_columns=[],
            applied_versions=[
                "0001_review_schema_base",
                "0002_review_schema_drift_repair",
            ],
        )

    async def create_pool(**kwargs: Any) -> CloseablePool:
        calls.append("pool")
        return pool

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(
        dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger)
    )
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies, "apply_migrations", apply_migrations)
    monkeypatch.setattr(dependencies, "inspect_review_schema", inspect_review_schema)
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=2,
            preflight_concurrency=3,
            auto_migrate=True,
            require_schema_current=False,
        ),
    )
    monkeypatch.setattr(dependencies, "PostgresReviewReragRepository", lambda pool: ("repo", pool))
    monkeypatch.setattr(dependencies, "_build_full_text_preparation", lambda **kwargs: object())
    monkeypatch.setattr(
        dependencies,
        "ReviewPreparationQueue",
        lambda config, repository, preparation, logger: queue,
    )
    monkeypatch.setattr(
        dependencies, "ReviewContextService", lambda repository: ("context", repository)
    )

    resources = await dependencies.create_app_resources(logger=object())

    assert calls[:3] == [
        "migrate:postgresql://user:pass@localhost:5434/pubtator_link",
        "inspect:postgresql://user:pass@localhost:5434/pubtator_link",
        "pool",
    ]
    assert resources.review_pool is pool


@pytest.mark.asyncio
async def test_create_app_resources_closes_partial_resources_when_review_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    pool = CloseablePool()
    logger = object()

    async def create_pool(**kwargs: Any) -> CloseablePool:
        return pool

    def raise_repository_error(pool: CloseablePool) -> object:
        raise RuntimeError("repository setup failed")

    monkeypatch.setattr(dependencies, "PubTator3Client", lambda logger=None: client)
    monkeypatch.setattr(
        dependencies, "PublicationService", lambda client, logger=None: ("pub", client, logger)
    )
    monkeypatch.setattr(
        dependencies,
        "PublicationPassageService",
        lambda publication_service: ("passages", publication_service),
    )
    monkeypatch.setattr(dependencies.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(
        dependencies,
        "review_rerag_config",
        SimpleNamespace(
            database_url="postgresql://user:pass@localhost:5434/pubtator_link",
            prep_concurrency=2,
        ),
    )
    monkeypatch.setattr(dependencies, "PostgresReviewReragRepository", raise_repository_error)

    with pytest.raises(RuntimeError, match="repository setup failed"):
        await dependencies.create_app_resources(logger=logger)

    assert pool.closed is True
    assert client.closed is True


@pytest.mark.asyncio
async def test_close_app_resources_closes_only_owned_resources() -> None:
    client = CloseableClient()
    metadata_client = CloseableClient()
    pool = CloseablePool()
    queue = StoppableQueue()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=client,
        publication_service=object(),
        publication_passage_service=object(),
        ncbi_publication_metadata_client=metadata_client,
        review_pool=pool,
        review_queue=queue,
    )

    await dependencies.close_app_resources(resources)

    assert queue.stopped is True
    assert pool.closed is True
    assert metadata_client.closed is True
    assert client.closed is True


def test_resources_from_request_returns_app_state_resources() -> None:
    app = FastAPI()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=CloseableClient(),
        publication_service=object(),
        publication_passage_service=object(),
    )
    app.state.pubtator_resources = resources
    request = Request({"type": "http", "app": app})

    assert dependencies.resources_from_request(request) is resources


@pytest.mark.asyncio
async def test_context_bound_resources_are_available_to_existing_dependency_names() -> None:
    client = CloseableClient()
    publication_service = object()
    passage_service = object()
    metadata_service = object()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=client,
        publication_service=publication_service,
        publication_passage_service=passage_service,
        publication_metadata_service=metadata_service,
    )

    token = dependencies.bind_app_resources(resources)
    try:
        assert dependencies.current_app_resources() is resources
        assert await dependencies.get_api_client() is client
        assert await dependencies.get_publication_service() is publication_service
        assert await dependencies.get_publication_passage_service() is passage_service
        assert await dependencies.get_publication_metadata_service() is metadata_service
    finally:
        dependencies.reset_app_resources(token)

    assert dependencies.current_app_resources() is None


@pytest.mark.asyncio
async def test_shutdown_requests_server_exit_without_closing_active_resources() -> None:
    manager = server_manager.UnifiedServerManager()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=CloseableClient(),
        publication_service=object(),
        publication_passage_service=object(),
    )
    server = SimpleNamespace(should_exit=False)
    manager.resources = resources
    manager.server = server

    await manager.shutdown()

    assert server.should_exit is True
    assert resources.api_client.closed is False
    assert manager.resources is resources


@pytest.mark.asyncio
async def test_lifespan_startup_failure_closes_resources_and_clears_app_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = server_manager.UnifiedServerManager()
    app = FastAPI()
    queue = FailingStartQueue()
    resources = dependencies.AppResources(
        logger=object(),
        api_client=CloseableClient(),
        publication_service=object(),
        publication_passage_service=object(),
        review_queue=queue,
    )

    async def create_resources(logger: object) -> dependencies.AppResources:
        return resources

    monkeypatch.setattr(server_manager, "create_app_resources", create_resources)

    with pytest.raises(RuntimeError, match="queue startup failed"):
        async with manager.lifespan(app):
            pass

    assert queue.stopped is True
    assert resources.api_client.closed is True
    assert not hasattr(app.state, "pubtator_resources")
    assert manager.resources is None


@pytest.mark.asyncio
async def test_cleanup_dependencies_clears_fallback_globals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = CloseableClient()
    monkeypatch.setattr(dependencies, "_api_client", client)
    monkeypatch.setattr(dependencies, "_review_queue", None)
    monkeypatch.setattr(dependencies, "_review_pool", None)

    await dependencies.cleanup_dependencies()

    assert client.closed is True
    assert dependencies._api_client is None
