from __future__ import annotations


class CrawlerError(RuntimeError):
    """Base class for crawler service errors."""


class CrawlerConfigurationError(CrawlerError, ValueError):
    """Raised when crawler configuration is invalid."""
