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


PLAYWRIGHT_RECOVERABLE_ERRORS = (PlaywrightError, PlaywrightTimeoutError)
