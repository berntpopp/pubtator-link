"""Import-time side-effect guard for pubtator_link.server_manager."""

from __future__ import annotations

import subprocess
import sys
import textwrap


def test_import_has_no_module_level_app_attribute() -> None:
    """The factory migration removes the module-level ASGI app."""
    import importlib

    module = importlib.import_module("pubtator_link.server_manager")
    assert not hasattr(module, "app"), (
        "pubtator_link.server_manager.app must not exist; use create_app() factory."
    )
    assert callable(getattr(module, "create_app", None)), (
        "create_app(...) must be importable as the factory entrypoint."
    )


def test_import_does_not_open_network_or_db_connections() -> None:
    """Importing the module must not trigger socket/DB activity."""
    script = textwrap.dedent(
        """
        import socket

        _original = socket.socket

        class _BlockedSocket(_original):
            def connect(self, *args, **kwargs):
                raise RuntimeError("import-time network access is forbidden")

        socket.socket = _BlockedSocket

        import pubtator_link.server_manager  # noqa: F401
        """
    ).strip()
    result = subprocess.run(  # noqa: S603 - controlled interpreter command for import guard.
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Import opened a socket at module load time.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
