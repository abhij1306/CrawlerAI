"""Bounded, self-contained recording of dropped variant rows.

Spec §6 requires that every dropped variant is explainable from
``diagnose.json`` alone, with ``row, stage, rule, reason``. Variants are
filtered at three layers (materialization coherence, output-safety
actionability, and the public firewall sellability gate). Each layer appends
to a shared :class:`VariantDropRecorder`; the publisher reads the accumulated
drops off the record and hands them to the diagnosis builder.

Previews are bounded so the artifact stays small regardless of how many
variants a page declares.
"""

from __future__ import annotations

from app.extraction.contracts import VariantDrop

# Record-private carrier key; mirrors the existing ``_lineage`` / ``_field_sources``
# convention so drops ride the record dict without engine signature churn.
VARIANT_DROPS_KEY = "_variant_drops"

_MAX_DROPS = 200
_PREVIEW_FIELDS = ("variant_id", "sku", "gtin", "url", "color", "size", "price")


def variant_row_preview(row: dict[str, object], *, limit: int = 120) -> str:
    """Identity-first, length-bounded preview of a variant row."""

    parts = [
        f"{field}={row[field]}"
        for field in _PREVIEW_FIELDS
        if row.get(field) not in (None, "", [], {}, ())
    ]
    text = ", ".join(parts) if parts else "<empty variant row>"
    return text if len(text) <= limit else text[: limit - 1] + "…"


class VariantDropRecorder:
    """Accumulates bounded variant drops across the filtering layers."""

    def __init__(self) -> None:
        self._drops: list[VariantDrop] = []

    def record(
        self, row: dict[str, object], *, stage: str, rule: str, reason: str
    ) -> None:
        if len(self._drops) >= _MAX_DROPS:
            return
        self._drops.append(
            VariantDrop(
                row=variant_row_preview(row),
                stage=stage,
                rule=rule,
                reason=reason,
            )
        )

    def extend(self, drops: tuple[VariantDrop, ...]) -> None:
        for drop in drops:
            if len(self._drops) >= _MAX_DROPS:
                return
            self._drops.append(drop)

    @property
    def drops(self) -> tuple[VariantDrop, ...]:
        return tuple(self._drops)


def drops_from_record(record: dict[str, object]) -> tuple[VariantDrop, ...]:
    """Read drops a materialization layer stashed on the record dict.

    Drops are stashed as plain dicts (json-safe) so they survive
    ``model_dump(mode="json")`` of the public record; reconstruct them here.
    """

    stashed = record.get(VARIANT_DROPS_KEY)
    if not isinstance(stashed, (list, tuple)):
        return ()
    result: list[VariantDrop] = []
    for item in stashed:
        if isinstance(item, VariantDrop):
            result.append(item)
        elif isinstance(item, dict):
            try:
                result.append(VariantDrop.model_validate(item))
            except Exception:  # noqa: BLE001
                continue
    return tuple(result)
