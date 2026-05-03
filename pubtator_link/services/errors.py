from __future__ import annotations


class PubTatorLinkError(RuntimeError):
    """Base class for PubTator-Link service errors with stable MCP mapping."""


class ReviewSchemaStaleError(PubTatorLinkError):
    """Review database schema is missing required tables or columns."""


class ReviewIndexUnavailableError(PubTatorLinkError):
    """Review database or index storage is unavailable."""


class UpstreamUnavailableError(PubTatorLinkError):
    """External upstream service timed out or is unavailable."""


class ValidationFailureError(PubTatorLinkError):
    """User-correctable validation failure."""
