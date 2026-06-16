"""CLI contract tests for the GeneFoundry Logging & CLI Standard v1 typer app."""

from __future__ import annotations

import tomllib
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

from pubtator_link import __version__, cli

runner = CliRunner()


def _command_option_names(command_name: str) -> set[str]:
    """Return the registered option names for a subcommand.

    Introspecting the click command is width-independent, unlike scraping the
    rich-rendered ``--help`` text (which wraps option tokens on narrow / no-TTY
    terminals such as CI).
    """
    group = typer.main.get_command(cli.app)
    ctx = click.Context(group)
    command = group.get_command(ctx, command_name)
    assert command is not None
    return {opt for param in command.params for opt in param.opts}


def test_app_is_typer_with_standard_name() -> None:
    assert cli.app.info.name == "pubtator-link"


def test_standard_subcommands_are_registered() -> None:
    group = typer.main.get_command(cli.app)
    ctx = click.Context(group)
    assert set(group.list_commands(ctx)) == {"serve", "config", "health", "version"}


def test_no_args_shows_help_without_serving() -> None:
    # ``no_args_is_help=True`` prints help and exits via click's missing-command
    # path (exit code 2); it must never fall through to serving the app.
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 2
    assert "Usage" in result.output
    assert "serve" in result.output


def test_serve_command_exposes_standard_options() -> None:
    options = _command_option_names("serve")
    assert {
        "--transport",
        "--host",
        "--port",
        "--mcp-path",
        "--log-level",
        "--disable-docs",
        "--dev",
    } <= options


def test_config_command_exposes_validate_option() -> None:
    assert "--validate" in _command_option_names("config")


def test_health_command_exposes_url_option() -> None:
    assert "--url" in _command_option_names("health")


def test_version_command_prints_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_validate_succeeds_for_default_config() -> None:
    result = runner.invoke(cli.app, ["config", "--validate"])
    assert result.exit_code == 0
    assert "valid" in result.output.lower()


@pytest.mark.parametrize("transport", ["unified", "http"])
def test_serve_accepts_supported_transports(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    calls: list[tuple[str, str, int, bool]] = []

    def fake_run_server(
        *, transport: str, host: str, port: int, unified: bool, reload: bool
    ) -> None:
        calls.append((transport, host, port, unified))

    monkeypatch.setattr(cli, "_run_server", fake_run_server)

    result = runner.invoke(cli.app, ["serve", "--transport", transport, "--port", "8123"])
    assert result.exit_code == 0
    assert calls == [(transport, "127.0.0.1", 8123, transport == "unified")]


def test_serve_rejects_stdio_transport() -> None:
    result = runner.invoke(cli.app, ["serve", "--transport", "stdio"])
    assert result.exit_code == 2
    assert "stdio" in result.output.lower() or "invalid" in result.output.lower()


def test_serve_rejects_unknown_transport() -> None:
    result = runner.invoke(cli.app, ["serve", "--transport", "carrier-pigeon"])
    assert result.exit_code == 2


def test_health_reports_unreachable_server() -> None:
    result = runner.invoke(cli.app, ["health", "--url", "http://127.0.0.1:1"])
    assert result.exit_code == 1
    assert "Failed to connect" in result.output


def test_console_script_entry_point_resolves() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    scripts = project["scripts"]
    assert scripts == {"pubtator-link": "pubtator_link.cli:app"}


def test_no_stdio_entry_point_remains() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    scripts = project["scripts"]
    assert "pubtator-link-mcp" not in scripts
    assert all("mcp_server" not in target for target in scripts.values())
