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
