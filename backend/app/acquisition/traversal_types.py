from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TraversalResult:
    requested_mode: str | None
    selected_mode: str | None = None
    activated: bool = False
    stop_reason: str = "not_requested"
    iterations: int = 0
    scroll_iterations: int = 0
    load_more_clicks: int = 0
    pages_advanced: int = 0
    progress_events: int = 0
    card_count: int = 0
    overlays_dismissed: bool = False
    click_retries: int = 0
    html_fragments: list[tuple[str | None, bool]] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)
    _seen_card_fragments: set[str] = field(default_factory=set, repr=False)
    _seen_structured_fragments: set[str] = field(default_factory=set, repr=False)

    def html_bytes(self) -> int:
        return sum(
            len(fragment.encode("utf-8"))
            for fragment, _is_fallback in self.html_fragments
            if fragment
        )

    def compose_html(self) -> str:
        texts = [
            str(fragment or "").strip()
            for fragment, _is_fallback in self.html_fragments
            if str(fragment or "").strip()
        ]
        if not texts:
            return ""
        if not self.activated:
            return "\n".join(texts)
        sections = [
            (
                f'<section data-traversal-fragment="{index}">\n'
                f"{text}\n"
                "</section>"
            )
            for index, text in enumerate(texts, start=1)
        ]
        return "<html><body>\n" + "\n".join(sections) + "\n</body></html>"

    def diagnostics(self) -> dict[str, object]:
        return {
            "requested_traversal_mode": self.requested_mode,
            "selected_traversal_mode": self.selected_mode,
            "traversal_activated": self.activated,
            "traversal_stop_reason": self.stop_reason,
            "traversal_iterations": self.iterations,
            "scroll_iterations": self.scroll_iterations,
            "load_more_clicks": self.load_more_clicks,
            "pages_advanced": self.pages_advanced,
            "traversal_progress_events": self.progress_events,
            "listing_card_count": self.card_count,
            "traversal_fragment_count": len(self.html_fragments),
            "traversal_html_bytes": self.html_bytes(),
            "overlays_dismissed": self.overlays_dismissed,
            "click_retries": self.click_retries,
            "traversal_events": self.events,
        }


__all__ = ["TraversalResult"]
