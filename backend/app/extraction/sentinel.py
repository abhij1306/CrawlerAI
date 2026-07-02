"""Sentinel challenger comparison for known-template extraction."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, cast

from app.core.config import extraction_memory as memory_config
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    ChallengerKind,
    ExecutionManifestContext,
    PublicRecord,
    SentinelDriftState,
    SentinelObservation,
    Verdict,
)

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
    recipe_verdict: Verdict,
    challenger_verdict: Verdict,
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
    pairs, unmatched_recipe, unmatched_challenger = _matched_records(
        recipe_records, challenger_records
    )
    identified_recipe = [
        row for row in unmatched_recipe if _has_identity(_identity(row))
    ]
    identified_challenger = [
        row for row in unmatched_challenger if _has_identity(_identity(row))
    ]
    if identified_recipe and identified_challenger:
        classes.append("identity")
    unidentified_recipe = [
        row for row in unmatched_recipe if not _has_identity(_identity(row))
    ]
    unidentified_challenger = [
        row for row in unmatched_challenger if not _has_identity(_identity(row))
    ]
    if len(unidentified_recipe) != len(unidentified_challenger):
        classes.append("record_count")
    if not pairs and bool(recipe_records) != bool(challenger_records):
        classes.append("record_count")
    for recipe_record, challenger_record in pairs:
        classes.extend(_record_disagreements(recipe_record, challenger_record))
    return tuple(sorted(set(classes)))


def _record_disagreements(
    recipe_record: PublicRecord, challenger_record: PublicRecord
) -> list[str]:
    classes: list[str] = []
    for label, fields in (
        ("critical_field", CRITICAL_FIELDS),
        ("benign_field", BENIGN_FIELDS),
    ):
        classes.extend(
            f"{label}:{field}"
            for field in fields
            if _normalized(recipe_record.get(field))
            != _normalized(challenger_record.get(field))
        )
    if any(
        _normalized(recipe_record.get(field))
        != _normalized(challenger_record.get(field))
        for field in ("variants", "variant_count")
    ):
        classes.append("variant_binding")
    return classes


def _state(
    classes: tuple[str, ...], recipe_verdict: Verdict, challenger_verdict: Verdict
) -> SentinelDriftState:
    if not classes:
        return "concordant" if recipe_verdict == challenger_verdict else "needs_review"
    if any(row in classes for row in ("record_count", "identity", "variant_binding")):
        return "critical_drift"
    if any(row.startswith("critical_field:") for row in classes):
        return "suspected_drift"
    return (
        "needs_review" if recipe_verdict != challenger_verdict else "benign_difference"
    )


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


def _identity(record: PublicRecord) -> tuple[str, str, str, str]:
    return cast(
        tuple[str, str, str, str],
        tuple(
            str(record.get(field) or "").strip().casefold()
            for field in ("sku", "gtin", "url", "title")
        ),
    )


def _has_identity(identity: tuple[str, str, str, str]) -> bool:
    return any(identity)


def _identities_match(
    left: tuple[str, str, str, str], right: tuple[str, str, str, str]
) -> bool:
    shared_stable = [(a, b) for a, b in zip(left[:3], right[:3]) if a and b]
    if any(a == b for a, b in shared_stable):
        return True
    if shared_stable:
        return False
    return bool(left[3] and right[3] and left[3] == right[3])


def _matched_records(
    recipe_records: tuple[PublicRecord, ...],
    challenger_records: tuple[PublicRecord, ...],
) -> tuple[
    list[tuple[PublicRecord, PublicRecord]],
    list[PublicRecord],
    list[PublicRecord],
]:
    unmatched_challenger = list(challenger_records)
    pairs: list[tuple[PublicRecord, PublicRecord]] = []
    unmatched_recipe: list[PublicRecord] = []
    for recipe_record in recipe_records:
        recipe_identity = _identity(recipe_record)
        match_index = next(
            (
                index
                for index, challenger_record in enumerate(unmatched_challenger)
                if _has_identity(recipe_identity)
                and _identities_match(recipe_identity, _identity(challenger_record))
            ),
            None,
        )
        if match_index is None:
            unmatched_recipe.append(recipe_record)
            continue
        pairs.append((recipe_record, unmatched_challenger.pop(match_index)))

    recipe_without_identity = [
        row for row in unmatched_recipe if not _has_identity(_identity(row))
    ]
    challenger_without_identity = [
        row for row in unmatched_challenger if not _has_identity(_identity(row))
    ]
    fallback_count = min(len(recipe_without_identity), len(challenger_without_identity))
    for index in range(fallback_count):
        recipe_record = recipe_without_identity[index]
        challenger_record = challenger_without_identity[index]
        pairs.append((recipe_record, challenger_record))
        unmatched_recipe.remove(recipe_record)
        unmatched_challenger.remove(challenger_record)
    return pairs, unmatched_recipe, unmatched_challenger


def _normalized(value: object) -> object:
    if value in (None, "", [], {}, ()):
        return None
    if isinstance(value, str):
        text = value.strip()
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return text.casefold()
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return Decimal(str(value))
    if isinstance(value, list):
        return tuple(_normalized(row) for row in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _normalized(val)) for key, val in value.items()))
    return value


def _clamped_rate(raw: object) -> float:
    try:
        value = float(cast(Any, raw))
    except (TypeError, ValueError):
        return memory_config.SENTINEL_DEFAULT_SAMPLE_RATE
    return max(0.0, min(1.0, value))
