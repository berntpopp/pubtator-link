#!/usr/bin/env python3
"""MCP Server Entry Point with Maximum Stdout Protection.

This is the main entry point for STDIO MCP mode with aggressive stdout protection
to prevent any non-JSON output from contaminating the MCP protocol.
"""

import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


def setup_ultra_clean_environment() -> None:
    """Set up the cleanest possible environment for MCP protocol."""
    # Critical: Force all output to stderr in STDIO mode
    os.environ["PYTHONUNBUFFERED"] = "1"
    os.environ["PUBTATOR_LINK_TRANSPORT"] = "stdio"

    # Aggressive FastMCP banner suppression
    os.environ["FASTMCP_DISABLE_BANNER"] = "1"
    os.environ["FASTMCP_NO_BANNER"] = "1"
    os.environ["FASTMCP_QUIET"] = "1"

    # Disable all color output and formatting
    os.environ["NO_COLOR"] = "1"
    os.environ["FORCE_COLOR"] = "0"
    os.environ["TERM"] = "dumb"

    # Suppress Python warnings
    os.environ["PYTHONWARNINGS"] = "ignore"

    # Disable import time logging
    os.environ["PYTHONVERBOSE"] = ""


def silence_all_logging() -> None:
    """Aggressively silence all logging that could contaminate stdout."""
    # Create a stderr-only handler
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)

    # Redirect the root logger to stderr
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(stderr_handler)
    root_logger.setLevel(logging.ERROR)

    # Silence specific loggers that might output to stdout
    problematic_loggers = [
        "fastmcp",
        "mcp",
        "uvicorn",
        "fastapi",
        "httpx",
        "httpcore",
        "asyncio",
        "pubtator_link",
        "rich",
        "console",
    ]

    for logger_name in problematic_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)
        logger.handlers.clear()
        logger.addHandler(stderr_handler)
        logger.propagate = False

    # Special handling for Rich console output that might go to stdout
    try:
        # Monkey patch rich console to use stderr
        import rich.console

        original_console_init = rich.console.Console.__init__

        def patched_console_init(self: object, *args: object, **kwargs: object) -> None:
            # Force all Rich console output to stderr in STDIO mode
            if isinstance(kwargs, dict):
                kwargs["file"] = sys.stderr
            original_console_init(self, *args, **kwargs)  # type: ignore[arg-type]

        rich.console.Console.__init__ = patched_console_init  # type: ignore[method-assign]
    except ImportError:
        pass  # Rich not available


def main() -> None:
    """Ultra-clean MCP server main entry point."""
    try:
        # Set up clean environment FIRST
        setup_ultra_clean_environment()

        # Add project to Python path
        project_root = Path(__file__).parent.absolute()
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        # Silence logging BEFORE any imports
        silence_all_logging()

        # Capture any import-time output
        import_buffer = StringIO()

        with redirect_stdout(import_buffer), redirect_stderr(sys.stderr):
            # Import after environment setup
            import asyncio

            from pubtator_link.mcp.facade import create_pubtator_mcp

            # CRITICAL: Patch FastMCP banner display after import
            try:
                from fastmcp.server import server as fastmcp_server

                # Monkey patch the banner display function to be a no-op
                def silent_banner(*args: object, **kwargs: object) -> None:
                    pass

                # Use dynamic attribute assignment to avoid MyPy error
                fastmcp_server._display_banner = silent_banner  # type: ignore[attr-defined]
            except (ImportError, AttributeError):
                pass

        # If there was any import output, send it to stderr (not stdout)
        import_output = import_buffer.getvalue()
        if import_output.strip():
            # Use sys.stderr.write instead of print to avoid T201 linting error
            sys.stderr.write(f"Import output: {import_output}\n")

        mcp = create_pubtator_mcp()
        asyncio.run(mcp.run_async(transport="stdio"))

    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - no output to stdout
        sys.exit(0)
    except Exception as e:
        # Error output goes to stderr only
        sys.stderr.write(f"CRITICAL MCP server error: {e}\n")
        import traceback

        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
