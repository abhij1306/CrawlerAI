"""Sentinel challenger comparison for known-template extraction."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Literal, Mapping

from app.core.config import extraction_memory as memory_config
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    ExecutionManifestContext,
    PublicRecord,
    SentinelDriftState,
    SentinelObservation,
)

ChallengerKind = Literal["deterministic", "ml"]

CRITICAL_FIELDS = ("title", "price", "currency", "sku", "gtin", "url")
BENIGN_FIELDS = ("description", "image_url", "additional_images", "features")


def sentinel_sample_rate(snapshot: Mapping[str, Any]) -> float:
    config = snapshot.get("sentinel")
    if not isinstance(config, Mapping):
        return memory_config.SENTINEL_DEFAULT_SAMPLE_RATE
    return _clamped_rate(config.get("sample_rate"))


def sentinel_enabled(snapshot: Mapping[str, Any], key: str) -> bool:
    config = snapshot.get("sentinel")
    if not isinstance(config, Mapping):
        if key != "deterministic_challenger_enabled":
            return False
        return memory_config.SENTINEL_DETERMINISTIC_CHALLENGER_ENABLED
    raw = config.get(key)
    return bool(raw) if raw is not None else sentinel_enabled({}, key)


def should_sample_sentinel(
    *,
    bundle_id: str,
    template_id: str | None,
    sample_rate: float,
) -> bool:
    if sample_rate <= 0:
        return False
    if sample_rate >= 1:
        return True
    token = stable_id("sentinel", bundle_id, template_id or "")
    bucket = int(token[-8:], 16) / 0xFFFFFFFF
    return bucket < sample_rate


def compare_challenger(
    *,
    challenger: ChallengerKind,
    manifest_context: ExecutionManifestContext,
    sample_rate: float,
    recipe_verdict: str,
    challenger_verdict: str,
    recipe_records: tuple[PublicRecord, ...],
    challenger_records: tuple[PublicRecord, ...],
    evidence_ids: Iterable[str],
    suspended: bool = False,
) -> SentinelObservation:
    classes = _disagreement_classes(recipe_records, challenger_records)
    state = _state(classes, recipe_verdict, challenger_verdict)
    diagnostic = _diagnostic(
        state=state,
        challenger=challenger,
        template_id=manifest_context.template_id,
        release_snapshot_id=manifest_context.release_snapshot_id,
        recipe_record_count=len(recipe_records),
        challenger_record_count=len(challenger_records),
        classes=classes,
        suspended=suspended,
    )
    return SentinelObservation(
        challenger=challenger,
        state=state,
        template_id=manifest_context.template_id,
        release_snapshot_id=manifest_context.release_snapshot_id,
        sample_rate=sample_rate,
        recipe_verdict=recipe_verdict,
        challenger_verdict=challenger_verdict,
        recipe_record_count=len(recipe_records),
        challenger_record_count=len(challenger_records),
        disagreement_classes=classes,
        evidence_ids=tuple(dict.fromkeys(evidence_ids)),
        diagnostic=diagnostic,
        next_action=_next_action(state, suspended=suspended),
        suspended=suspended,
    )


def _disagreement_classes(
    recipe_records: tuple[PublicRecord, ...],
    challenger_records: tuple[PublicRecord, ...],
) -> tuple[str, ...]:
    classes: list[str] = []
    if len(recipe_records) != len(challenger_records):
        classes.append("record_count")
    for index, recipe_record in enumerate(recipe_records):
        challenger_record = (
            challenger_records[index] if index < len(challenger_records) else None
        )
        if challenger_record is None:
            continue
        recipe_identity = _identity(recipe_record)
        challenger_identity = _identity(challenger_record)
        if (
            recipe_identity
            and challenger_identity
            and recipe_identity != challenger_identity
        ):
            classes.append("identity")
        for field in CRITICAL_FIELDS:
            if _normalized(recipe_record.get(field)) != _normalized(
                challenger_record.get(field)
            ):
                classes.append(f"critical_field:{field}")
        for field in ("variants", "variant_count"):
            if _normalized(recipe_record.get(field)) != _normalized(
                challenger_record.get(field)
            ):
                classes.append("variant_binding")
        for field in BENIGN_FIELDS:
            if _normalized(recipe_record.get(field)) != _normalized(
                challenger_record.get(field)
            ):
                classes.append(f"benign_field:{field}")
    return tuple(sorted(set(classes)))


def _state(
    classes: tuple[str, ...], recipe_verdict: str, challenger_verdict: str
) -> SentinelDriftState:
    if not classes and recipe_verdict == challenger_verdict:
        return "concordant"
    if any(row in classes for row in ("record_count", "identity", "variant_binding")):
        return "critical_drift"
    if any(row.startswith("critical_field:") for row in classes):
        return "suspected_drift"
    if recipe_verdict != challenger_verdict:
        return "needs_review"
    if classes:
        return "benign_difference"
    return "needs_review"


def _diagnostic(
    *,
    state: SentinelDriftState,
    challenger: ChallengerKind,
    template_id: str | None,
    release_snapshot_id: str | None,
    recipe_record_count: int,
    challenger_record_count: int,
    classes: tuple[str, ...],
    suspended: bool,
) -> str:
    action = _next_action(state, suspended=suspended)
    return (
        f"Sentinel {challenger} challenger is {state} for template "
        f"{template_id or 'unknown'} in release {release_snapshot_id or 'none'}; "
        f"recipe records={recipe_record_count}, challenger records={challenger_record_count}; "
        f"disagreements={', '.join(classes) if classes else 'none'}; next={action}."
    )


def _next_action(state: SentinelDriftState, *, suspended: bool) -> str:
    if suspended:
        return "route_future_traffic_to_generic_until_recipe_is_restored"
    if state == "critical_drift":
        return "confirm_drift_before_suspending_template"
    if state in {"suspected_drift", "needs_review"}:
        return "queue_for_operator_review"
    return "continue_recipe"


def _identity(record: PublicRecord) -> tuple[str, ...]:
    return tuple(
        str(record.get(field) or "").strip().casefold()
        for field in ("sku", "gtin", "url", "title")
        if str(record.get(field) or "").strip()
    )


def _normalized(value: object) -> object:
    if value in (None, "", [], {}, ()):
        return None
    if isinstance(value, str):
        text = value.strip()
        try:
            return str(Decimal(text))
        except (InvalidOperation, ValueError):
            return text.casefold()
    if isinstance(value, float):
        return str(Decimal(str(value)))
    if isinstance(value, list):
        return tuple(_normalized(row) for row in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _normalized(val)) for key, val in value.items()))
    return value


def _clamped_rate(raw: object) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return memory_config.SENTINEL_DEFAULT_SAMPLE_RATE
    return max(0.0, min(1.0, value))
