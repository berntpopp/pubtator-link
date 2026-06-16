"""Logging configuration for pubtator-link.

GeneFoundry Logging & CLI Standard v1: ``structlog`` on the canonical processor
chain (``merge_contextvars → add_log_level → TimeStamper(iso) →
StackInfoRenderer → set_exc_info → static fields``) rendered as JSON in
production or via ``ConsoleRenderer`` in development (selected by ``LOG_FORMAT``).
The ``asgi-correlation-id`` request id is surfaced onto every log event through
``merge_contextvars`` (the ``CorrelationIdMiddleware`` binds it per request in
``server_manager``). Streamable HTTP only — there is no stdio stream routing.
"""

import logging
import os
import sys
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

from . import __version__
from .config import settings


def _add_static_fields(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Attach ``service`` and ``version`` to every log event."""
    event_dict.setdefault("service", "pubtator-link")
    event_dict.setdefault("version", __version__)
    return event_dict


def configure_logging() -> FilteringBoundLogger:
    """Configure structured logging and return the package logger."""
    use_colors = (
        settings.log_format != "json"
        and sys.stdout.isatty() is not False
        and "NO_COLOR" not in os.environ
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        _add_static_fields,
    ]

    if settings.log_format == "json":
        processors = [*shared_processors, structlog.processors.JSONRenderer()]
    else:
        processors = [*shared_processors, structlog.dev.ConsoleRenderer(colors=use_colors)]

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper())
        ),
        logger_factory=structlog.WriteLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.log_level.upper()),
    )

    # Tame noisy third-party loggers for the HTTP transports.
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
