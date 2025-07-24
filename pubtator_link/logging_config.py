"""Logging configuration for PubTator-Link."""

import logging
import os
import sys
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

from .config import settings


def configure_logging() -> FilteringBoundLogger:
    """Configure structured logging for the application with transport-aware stream routing."""
    # Determine output stream based on transport mode
    # CRITICAL: STDIO mode MUST use stderr to avoid contaminating JSON protocol on stdout
    log_stream = sys.stderr if settings.transport == "stdio" else sys.stdout

    # Configure color support based on transport and environment
    use_colors = (
        settings.transport != "stdio"
        and not settings.log_format == "json"
        and sys.stdout.isatty() is not False
        and "NO_COLOR" not in os.environ
    )

    # Configure structlog
    if settings.log_format == "json":
        # JSON logging for production - always use specified stream
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, settings.log_level.upper())
            ),
            logger_factory=structlog.WriteLoggerFactory(log_stream),
            cache_logger_on_first_use=True,
        )
    else:
        # Console logging for development with transport-aware coloring
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.dev.ConsoleRenderer(colors=use_colors),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, settings.log_level.upper())
            ),
            logger_factory=structlog.WriteLoggerFactory(log_stream),
            cache_logger_on_first_use=True,
        )

    # Configure standard library logging with transport-aware stream routing
    logging.basicConfig(
        format="%(message)s",
        stream=log_stream,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Transport-specific library log level adjustments
    if settings.transport == "stdio":
        # Aggressively reduce noise in STDIO mode to protect MCP protocol
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.access").setLevel(logging.ERROR)
        logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("fastapi").setLevel(logging.WARNING)
        # Suppress FastMCP internal logging in STDIO mode
        logging.getLogger("fastmcp").setLevel(logging.WARNING)
        logging.getLogger("mcp").setLevel(logging.WARNING)
    else:
        # Normal log levels for HTTP modes
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.INFO)
        logging.getLogger("httpcore").setLevel(logging.INFO)

    return structlog.get_logger("pubtator_link")  # type: ignore[no-any-return]


def log_api_request(
    logger: FilteringBoundLogger,
    method: str,
    url: str,
    response_time: float,
    status_code: int,
    **kwargs: Any,
) -> None:
    """Log API request with structured data."""
    logger.info(
        "API request completed",
        method=method,
        url=url,
        response_time_ms=round(response_time * 1000, 2),
        status_code=status_code,
        **kwargs,
    )


def log_cache_event(
    logger: FilteringBoundLogger,
    event: str,
    cache_key: str,
    hit: bool = False,
    **kwargs: Any,
) -> None:
    """Log cache events with structured data."""
    logger.debug(f"Cache {event}", cache_key=cache_key, cache_hit=hit, **kwargs)


def log_rate_limit_event(
    logger: FilteringBoundLogger, endpoint: str, wait_time: float, **kwargs: Any
) -> None:
    """Log rate limiting events."""
    logger.debug(
        "Rate limit applied",
        endpoint=endpoint,
        wait_time_ms=round(wait_time * 1000, 2),
        **kwargs,
    )
