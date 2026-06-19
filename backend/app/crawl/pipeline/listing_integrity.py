from __future__ import annotations


def propagate_listing_integrity_to_diagnostics(
    artifacts: dict[str, object] | None,
    browser_diagnostics: dict[str, object] | None,
) -> None:
    """Thread the IntegrityDecision from artifacts onto browser diagnostics."""
    if browser_diagnostics is None or artifacts is None:
        return
    decision_payload = artifacts.get("listing_integrity")
    if not isinstance(decision_payload, dict):
        return

    decision_copy = dict(decision_payload)
    existing = browser_diagnostics.get("listing_integrity")
    if isinstance(existing, dict):
        decision_copy["previous"] = existing

    browser_diagnostics["listing_integrity"] = decision_copy
