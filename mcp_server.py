#!/usr/bin/env python
"""
MCP STDIO server for PubTator-Link biomedical literature API.

Backwards-compatible STDIO server for AI assistants like Claude Desktop.
This is a wrapper around the unified server architecture.
"""

import asyncio
import sys

from pubtator_link.logging_config import configure_logging
from pubtator_link.server_manager import UnifiedServerManager


def main() -> None:
    """Start STDIO MCP server for AI assistant integration."""
    logger = configure_logging()

    try:
        # Create server manager
        manager = UnifiedServerManager()

        # Run STDIO server using the unified server manager
        asyncio.run(manager.start_stdio_server())

    except KeyboardInterrupt:
        # Graceful shutdown on interrupt
        sys.exit(0)
    except Exception as e:
        # Log errors to stderr (won't interfere with STDIO protocol)
        logger.error(f"MCP server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
