"""Typed operator facts emitted by acquisition work."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from app.core.config.run_events import (
    ACQUISITION_EVENT_REQUIRED_FACTS,
    AcquisitionEventKind,
)

logger = logging.getLogger(__name__)


AcquisitionFactValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class AcquisitionEvent:
    """Closed acquisition fact for an operator timeline callback."""

    kind: AcquisitionEventKind
    facts: Mapping[str, AcquisitionFactValue]
    reason_code: str | None = None

    def __post_init__(self) -> None:
        facts = dict(self.facts)
        required = ACQUISITION_EVENT_REQUIRED_FACTS[self.kind]
        if set(facts) != required:
            raise ValueError(f"Invalid facts for acquisition event kind: {self.kind}")
        if any(
            not isinstance(value, (str, int, float, bool, type(None)))
            for value in facts.values()
        ):
            raise TypeError("Acquisition event facts must be scalar values")
        if self.reason_code is not None and not self.reason_code.strip():
            raise ValueError("Acquisition event reason_code must not be blank")
        object.__setattr__(self, "facts", MappingProxyType(facts))

    @classmethod
    def started(cls, *, url: str) -> "AcquisitionEvent":
        return cls(AcquisitionEventKind.STARTED, {"url": url})

    @classmethod
    def strategy_selected(
        cls,
        *,
        fetch_mode: str,
        browser_first: bool,
        prefer_browser: bool,
        host_preference_enabled: bool,
        http_timeout_seconds: float,
        primary_http_fetcher: str,
        reason_code: str | None,
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.STRATEGY_SELECTED,
            {
                "fetch_mode": fetch_mode,
                "browser_first": browser_first,
                "prefer_browser": prefer_browser,
                "host_preference_enabled": host_preference_enabled,
                "http_timeout_seconds": http_timeout_seconds,
                "primary_http_fetcher": primary_http_fetcher,
            },
            reason_code=reason_code,
        )

    @classmethod
    def http_attempted(
        cls, *, fetcher: str, timeout_seconds: float, proxy_mode: str
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.HTTP_ATTEMPTED,
            {
                "fetcher": fetcher,
                "timeout_seconds": timeout_seconds,
                "proxy_mode": proxy_mode,
            },
        )

    @classmethod
    def http_failed(cls, *, fetcher: str, exception_type: str) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.HTTP_FAILED,
            {"fetcher": fetcher, "exception_type": exception_type},
        )

    @classmethod
    def browser_launched(
        cls,
        *,
        launch_mode: str,
        engine: str,
        profile: str,
        proxy_mode: str,
        binary: str,
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.BROWSER_LAUNCHED,
            {
                "launch_mode": launch_mode,
                "engine": engine,
                "profile": profile,
                "proxy_mode": proxy_mode,
                "binary": binary,
            },
        )

    @classmethod
    def browser_page_loaded(
        cls, *, elapsed_ms: int, page_title: str
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.BROWSER_PAGE_LOADED,
            {"elapsed_ms": elapsed_ms, "page_title": page_title},
        )

    @classmethod
    def browser_first_fallback(cls, *, exception_type: str) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.BROWSER_FIRST_FALLBACK,
            {"exception_type": exception_type},
        )

    @classmethod
    def browser_escalated(
        cls, *, status_code: int, method: str, reason_code: str
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.BROWSER_ESCALATED,
            {"status_code": status_code, "method": method},
            reason_code=reason_code,
        )

    @classmethod
    def protection_detected(cls, *, status_code: int) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.PROTECTION_DETECTED,
            {"status_code": status_code},
        )

    @classmethod
    def popup_closed(cls, *, popup_url: str) -> "AcquisitionEvent":
        return cls(AcquisitionEventKind.POPUP_CLOSED, {"popup_url": popup_url})

    @classmethod
    def browser_interstitial_dismissed(cls, *, selector: str) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.BROWSER_INTERSTITIAL_DISMISSED,
            {"selector": selector},
        )

    @classmethod
    def traversal_detected(
        cls, *, mode: str, safety_cap: int, target_records: int | None
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.TRAVERSAL_DETECTED,
            {
                "mode": mode,
                "safety_cap": safety_cap,
                "target_records": target_records,
            },
        )

    @classmethod
    def traversal_progressed(
        cls,
        *,
        action: str,
        step: int,
        previous_card_count: int,
        current_card_count: int,
        target_records: int | None,
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.TRAVERSAL_PROGRESSED,
            {
                "action": action,
                "step": step,
                "previous_card_count": previous_card_count,
                "current_card_count": current_card_count,
                "target_records": target_records,
            },
        )

    @classmethod
    def traversal_settled(
        cls, *, previous_card_count: int, current_card_count: int
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.TRAVERSAL_SETTLED,
            {
                "previous_card_count": previous_card_count,
                "current_card_count": current_card_count,
            },
        )

    @classmethod
    def traversal_recovery_started(cls, *, action: str) -> "AcquisitionEvent":
        return cls(AcquisitionEventKind.TRAVERSAL_RECOVERY_STARTED, {"action": action})

    @classmethod
    def traversal_completed(
        cls,
        *,
        mode: str,
        card_count: int,
        fragment_count: int,
        progress_event_count: int,
        stop_reason: str,
    ) -> "AcquisitionEvent":
        return cls(
            AcquisitionEventKind.TRAVERSAL_COMPLETED,
            {
                "mode": mode,
                "card_count": card_count,
                "fragment_count": fragment_count,
                "progress_event_count": progress_event_count,
                "stop_reason": stop_reason,
            },
        )


AcquisitionEventHandler = Callable[[AcquisitionEvent], Awaitable[None]]


async def emit_acquisition_event(
    handler: AcquisitionEventHandler | None,
    event: AcquisitionEvent,
) -> None:
    """Deliver an operator fact without letting observability alter acquisition."""
    if handler is None:
        return
    try:
        await handler(event)
    except Exception:
        logger.debug(
            "Acquisition event callback failed",
            exc_info=True,
            extra={"event_kind": event.kind.value},
        )
