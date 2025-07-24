#!/usr/bin/env python3
"""Main server entry point for PubTator-Link."""

import argparse
import asyncio
import signal
import sys
from typing import Any

from pubtator_link.config import settings
from pubtator_link.logging_config import configure_logging
from pubtator_link.server_manager import UnifiedServerManager


async def main() -> None:
    """Start server entry point."""
    parser = argparse.ArgumentParser(description="PubTator-Link Server")
    parser.add_argument(
        "--transport",
        choices=["unified", "http", "stdio"],
        default=settings.transport,
        help="Server transport mode",
    )
    parser.add_argument("--host", default=settings.host, help="Server host")
    parser.add_argument("--port", type=int, default=settings.port, help="Server port")
    parser.add_argument("--log-level", default=settings.log_level, help="Logging level")

    args = parser.parse_args()

    # Override settings with command line arguments
    settings.transport = args.transport
    settings.host = args.host
    settings.port = args.port
    settings.log_level = args.log_level

    # Configure logging
    logger = configure_logging()

    # Create server manager
    server_manager = UnifiedServerManager(logger=logger)

    # Setup signal handlers
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info("Received shutdown signal", signal=signum)
        asyncio.create_task(server_manager.shutdown())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start server based on transport mode
        if args.transport == "unified":
            await server_manager.start_unified_server(host=args.host, port=args.port)
        elif args.transport == "http":
            await server_manager.start_http_only_server(host=args.host, port=args.port)
        elif args.transport == "stdio":
            await server_manager.start_stdio_server()
        else:
            logger.error("Invalid transport mode", transport=args.transport)
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("Server shutdown requested")
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)
    finally:
        await server_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
