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
            "0.0.0.0",
            "--port",
            "9000",
            "--reload",
        ],
    )
    monkeypatch.setattr(cli, "serve_http", fake_serve_http)
    monkeypatch.setattr(cli.asyncio, "run", fake_asyncio_run)

    cli.main()

    assert calls == [("0.0.0.0", 9000, True), sentinel]


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
