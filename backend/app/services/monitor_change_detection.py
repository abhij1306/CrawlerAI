from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.monitor import (
    MonitorEvent,
    MonitorJob,
    MonitorSnapshot,
    MonitorSnapshotRecord,
)
from app.services.config.monitor_settings import (
    MONITOR_EVENT_FIELD_CHANGED,
    MONITOR_EVENT_RECORD_NEW,
    MONITOR_EVENT_RECORD_REMOVED,
    MONITOR_ID_SETTING_KEY,
    NOTIFICATION_STATUS_PENDING,
    TRACKED_FIELD_ALIASES,
)
from app.services.monitor_alert_service import create_monitor_change_notification
from app.services.monitor_service import utcnow
from app.services.pipeline.run_complete_callbacks import register_run_complete_callback

_CALLBACK_KEY = "monitor_change_detection"
_PRICE_RE = re.compile(r"-?\d+(?:\.\d+)?")


class MonitorChangeDetectionService:
    async def handle_run_complete(self, run_id: int) -> None:
        async with SessionLocal() as session:
            run = await session.get(CrawlRun, run_id)
            if run is None:
                return
            settings = run.settings if isinstance(run.settings, dict) else {}
            monitor_id = _as_int(settings.get(MONITOR_ID_SETTING_KEY))
            if monitor_id is None:
                return
            monitor = await session.get(MonitorJob, monitor_id)
            if monitor is None:
                return

            previous_records = await _latest_snapshot_records(session, monitor.id)
            current_records = list(
                (
                    await session.scalars(
                        select(CrawlRecord)
                        .where(CrawlRecord.run_id == run.id)
                        .order_by(CrawlRecord.id)
                    )
                ).all()
            )
            previous = {record.url_identity_key: record for record in previous_records}
            current = {
                _record_identity(record): record
                for record in current_records
                if record.data and _record_identity(record)
            }

            events: list[MonitorEvent] = []
            detected_at = utcnow()
            tracked_fields = [str(field) for field in list(monitor.tracked_fields or [])]

            for key, record in current.items():
                if key not in previous:
                    events.append(
                        _event(
                            monitor_id=monitor.id,
                            run_id=run.id,
                            source_url=record.source_url,
                            event_type=MONITOR_EVENT_RECORD_NEW,
                            detected_at=detected_at,
                            new_value=_tracked_values(record, tracked_fields),
                        )
                    )
                    continue
                previous_row = previous[key]
                for field in tracked_fields:
                    old_raw = dict(previous_row.field_values or {}).get(field)
                    new_raw = _get_field_value(dict(record.data or {}), field)

                    old_value = _normalized_value(field, old_raw)
                    new_value = _normalized_value(field, new_raw)

                    if old_value != new_value:
                        events.append(
                            _event(
                                monitor_id=monitor.id,
                                run_id=run.id,
                                source_url=record.source_url,
                                event_type=MONITOR_EVENT_FIELD_CHANGED,
                                field_name=field,
                                old_value=old_raw,
                                new_value=new_raw,
                                detected_at=detected_at,
                            )
                        )

            for key, previous_row in previous.items():
                if key not in current:
                    events.append(
                        _event(
                            monitor_id=monitor.id,
                            run_id=run.id,
                            source_url=previous_row.source_url,
                            event_type=MONITOR_EVENT_RECORD_REMOVED,
                            detected_at=detected_at,
                            old_value=dict(previous_row.field_values or {}),
                        )
                    )

            snapshot = MonitorSnapshot(
                monitor_id=monitor.id,
                run_id=run.id,
                snapshot_data={
                    "tracked_fields": tracked_fields,
                    "run_id": run.id,
                },
                record_count=len(current),
                change_count=len(events),
            )
            session.add(snapshot)
            await session.flush()
            for key, record in current.items():
                session.add(
                    MonitorSnapshotRecord(
                        snapshot_id=snapshot.id,
                        monitor_id=monitor.id,
                        source_url=record.source_url,
                        url_identity_key=key,
                        field_values=_tracked_values(record, tracked_fields),
                    )
                )
            for event in events:
                session.add(event)
            await create_monitor_change_notification(
                session,
                monitor=monitor,
                events=events,
            )
            summary = dict(run.result_summary or {})
            summary["monitor_change_count"] = len(events)
            run.result_summary = summary
            await session.commit()


def ensure_monitor_change_detection_registered() -> None:
    service = MonitorChangeDetectionService()
    register_run_complete_callback(service.handle_run_complete, key=_CALLBACK_KEY)


async def _latest_snapshot_records(session, monitor_id: int) -> list[MonitorSnapshotRecord]:
    snapshot_id = await session.scalar(
        select(MonitorSnapshot.id)
        .where(MonitorSnapshot.monitor_id == monitor_id)
        .order_by(MonitorSnapshot.created_at.desc(), MonitorSnapshot.id.desc())
        .limit(1)
    )
    if snapshot_id is None:
        return []
    return list(
        (
            await session.scalars(
                select(MonitorSnapshotRecord).where(
                    MonitorSnapshotRecord.snapshot_id == snapshot_id
                )
            )
        ).all()
    )


def _event(
    *,
    monitor_id: int,
    run_id: int,
    source_url: str,
    event_type: str,
    detected_at,
    field_name: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
) -> MonitorEvent:
    return MonitorEvent(
        monitor_id=monitor_id,
        run_id=run_id,
        source_url=source_url,
        event_type=event_type,
        field_name=field_name,
        old_value=old_value,
        new_value=new_value,
        detected_at=detected_at,
        notification_status=NOTIFICATION_STATUS_PENDING,
    )


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
        # Strip query parameters, fragment, and normalize scheme/host/path
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")
        # We unparse without params, query, fragment
        return urlunparse((scheme, netloc, path, "", "", ""))
    except Exception:
        return url.strip()


def _record_identity(record: CrawlRecord) -> str:
    key = record.url_identity_key or record.source_url or ""
    return _normalize_url(str(key))


def _get_field_value(data: dict[str, Any], field: str) -> Any:
    # First check exact field
    if field in data and data[field] not in (None, "", [], {}):
        return data[field]
    # Check aliases
    for k, v in data.items():
        if TRACKED_FIELD_ALIASES.get(k) == field and v not in (None, "", [], {}):
            return v
    return data.get(field)


def _tracked_values(record: CrawlRecord, tracked_fields: list[str]) -> dict[str, Any]:
    data = dict(record.data or {})
    return {field: _get_field_value(data, field) for field in tracked_fields}


def _normalized_value(field: str, value: Any) -> object:
    if value in (None, "", [], {}):
        return None
    if "price" in field.lower():
        return _price_value(value)
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    return value


def _price_value(value: Any) -> Decimal | object:
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    match = _PRICE_RE.search(str(value or ""))
    if not match:
        return _normalized_value("text", value)
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return _normalized_value("text", value)


def _as_int(value: object) -> int | None:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
