from __future__ import annotations

try:
    from patchright.async_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
    )
except ImportError:  # pragma: no cover
    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass

    class PlaywrightTimeoutError(PlaywrightError):  # type: ignore[no-redef]
        pass


PLAYWRIGHT_RECOVERABLE_ERRORS: tuple[type[Exception], ...] = (
    PlaywrightError,
    PlaywrightTimeoutError,
)

RECOVERABLE_RUNTIME_ERROR_PATTERNS = (
    "event loop is closed",
    "browser has been closed",
    "target closed",
    "connection closed",
    "session closed",
)


def is_recoverable_playwright_error(exc: Exception) -> bool:
    if isinstance(exc, PLAYWRIGHT_RECOVERABLE_ERRORS):
        return True
    if isinstance(exc, (ConnectionResetError, OSError)):
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        return any(pattern in message for pattern in RECOVERABLE_RUNTIME_ERROR_PATTERNS)
    return False
