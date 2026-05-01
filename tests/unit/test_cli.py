from __future__ import annotations

import pytest

from pubtator_link import cli


def test_cli_without_command_prints_help_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["pubtator-link"])

    cli.main()


def test_cli_serve_without_mode_prints_help_and_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve"])

    cli.main()


def test_cli_dispatches_http_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_serve_http(host: str, port: int, reload: bool) -> object:
        calls.append((host, port, reload))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr(
        "sys.argv",
        [
            "pubtator-link",
            "serve",
            "http",
            "--host",
            "0.0.0.0",  # noqa: S104 - CLI smoke test verifies host argument dispatch.
            "--port",
            "9000",
            "--reload",
        ],
    )
    monkeypatch.setattr(cli, "serve_http", fake_serve_http)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("0.0.0.0", 9000, True), sentinel]  # noqa: S104


def test_cli_dispatches_unified_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_serve_unified(host: str, port: int, reload: bool) -> object:
        calls.append((host, port, reload))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve", "unified", "--port", "9100"])
    monkeypatch.setattr(cli, "serve_unified", fake_serve_unified)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("127.0.0.1", 9100, False), sentinel]


def test_cli_dispatches_mcp_server(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("sys.argv", ["pubtator-link", "serve", "mcp"])
    monkeypatch.setattr(cli, "serve_mcp_only", lambda: calls.append("mcp"))

    cli.main()

    assert calls == ["mcp"]


def test_cli_dispatches_entities_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_search_entities(query: str, concept: str | None, limit: int) -> object:
        calls.append((query, concept, limit))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr(
        "sys.argv",
        ["pubtator-link", "entities", "MEFV", "--concept", "Gene", "--limit", "3"],
    )
    monkeypatch.setattr(cli, "search_entities", fake_search_entities)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("MEFV", "Gene", 3), sentinel]


def test_cli_dispatches_search_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_search_publications(query: str, page: int) -> object:
        calls.append((query, page))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr("sys.argv", ["pubtator-link", "search", "colchicine", "--page", "2"])
    monkeypatch.setattr(cli, "search_publications", fake_search_publications)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("colchicine", 2), sentinel]


def test_cli_dispatches_export_command(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []
    sentinel = object()

    def fake_export_publications(pmids: str, format: str, full: bool) -> object:
        calls.append((pmids, format, full))
        return sentinel

    def fake_asyncio_run(coro: object) -> None:
        calls.append(coro)

    monkeypatch.setattr(
        "sys.argv",
        ["pubtator-link", "export", "1,2", "--format", "pubtator", "--full"],
    )
    monkeypatch.setattr(cli, "export_publications", fake_export_publications)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("1,2", "pubtator", True), sentinel]


@pytest.mark.parametrize(("success", "expected_code"), [(True, 0), (False, 1)])
def test_cli_test_command_maps_connection_result_to_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    success: bool,
    expected_code: int,
) -> None:
    sentinel = object()

    def fake_test_connection() -> object:
        return sentinel

    def fake_asyncio_run(coro: object) -> bool:
        assert coro is sentinel
        return success

    monkeypatch.setattr("sys.argv", ["pubtator-link", "test"])
    monkeypatch.setattr(cli, "test_connection", fake_test_connection)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    with pytest.raises(SystemExit) as exc_info:
        cli.main()

    assert exc_info.value.code == expected_code
