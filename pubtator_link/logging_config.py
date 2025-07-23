"""Logging configuration for PubTator-Link."""

import logging
import sys
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

from .config import settings


def configure_logging() -> FilteringBoundLogger:
    """Configure structured logging for the application."""
    # Configure structlog
    if settings.log_format == "json":
        # JSON logging for production
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
            logger_factory=structlog.WriteLoggerFactory(sys.stdout),
            cache_logger_on_first_use=True,
        )
    else:
        # Console logging for development
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, settings.log_level.upper())
            ),
            logger_factory=structlog.WriteLoggerFactory(sys.stderr),
            cache_logger_on_first_use=True,
        )

    # Configure standard library logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout if settings.log_format == "json" else sys.stderr,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Adjust log levels for noisy libraries
    if settings.transport == "stdio":
        # Reduce noise in STDIO mode
        logging.getLogger("uvicorn").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
    else:
        logging.getLogger("uvicorn.access").setLevel(logging.INFO)
        logging.getLogger("httpx").setLevel(logging.INFO)

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
