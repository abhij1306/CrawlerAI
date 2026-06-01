from __future__ import annotations

import asyncio
import json
from random import SystemRandom
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.monitor import MonitorEvent, MonitorJob, MonitorWebhookDelivery
from app.services.config.monitor_settings import (
    MONITOR_EVENT_FIELD_CHANGED,
    WEBHOOK_DELIVERY_TIMEOUT_SECONDS,
    WEBHOOK_MAX_RETRY_ATTEMPTS,
    WEBHOOK_PAYLOAD_MAX_BYTES,
    WEBHOOK_RETRY_BACKOFF_BASE_SECONDS,
    WEBHOOK_RETRY_BACKOFF_MAX_SECONDS,
    WEBHOOK_RETRY_JITTER_SECONDS,
    WEBHOOK_STATUS_FAILED,
    WEBHOOK_STATUS_SENT,
    WEBHOOK_STATUS_SKIPPED,
)
from app.services.monitor_service import utcnow

_jitter_random = SystemRandom()


async def dispatch_alert_webhooks(
    session: AsyncSession,
    *,
    monitor: MonitorJob,
    events: list[MonitorEvent],
) -> None:
    if not monitor.webhook_url:
        for event in events:
            if event.condition_met:
                session.add(
                    MonitorWebhookDelivery(
                        monitor_id=monitor.id,
                        event_id=event.id,
                        status=WEBHOOK_STATUS_SKIPPED,
                        attempt=0,
                        payload_preview={},
                        error_message="No webhook_url configured",
                    )
                )
        return
    for event in events:
        if event.event_type != MONITOR_EVENT_FIELD_CHANGED or not event.condition_met:
            continue
        payload = _webhook_payload(monitor, event)
        await _deliver_payload(session, monitor=monitor, event=event, payload=payload)


async def list_webhook_deliveries(
    session: AsyncSession,
    *,
    monitor_id: int,
    limit: int = 100,
) -> list[MonitorWebhookDelivery]:
    rows = await session.scalars(
        select(MonitorWebhookDelivery)
        .where(MonitorWebhookDelivery.monitor_id == monitor_id)
        .order_by(MonitorWebhookDelivery.created_at.desc(), MonitorWebhookDelivery.id.desc())
        .limit(limit)
    )
    return list(rows.all())


async def _deliver_payload(
    session: AsyncSession,
    *,
    monitor: MonitorJob,
    event: MonitorEvent,
    payload: dict[str, Any],
) -> None:
    encoded = json.dumps(payload, default=str).encode("utf-8")
    if len(encoded) > WEBHOOK_PAYLOAD_MAX_BYTES:
        session.add(
            MonitorWebhookDelivery(
                monitor_id=monitor.id,
                event_id=event.id,
                status=WEBHOOK_STATUS_FAILED,
                attempt=0,
                payload_preview=_payload_preview(payload),
                error_message="Webhook payload exceeds size limit",
            )
        )
        return

    async with httpx.AsyncClient(timeout=WEBHOOK_DELIVERY_TIMEOUT_SECONDS) as client:
        for attempt in range(1, WEBHOOK_MAX_RETRY_ATTEMPTS + 1):
            delivery = MonitorWebhookDelivery(
                monitor_id=monitor.id,
                event_id=event.id,
                status=WEBHOOK_STATUS_FAILED,
                attempt=attempt,
                payload_preview=_payload_preview(payload),
            )
            try:
                response = await client.post(str(monitor.webhook_url), json=payload)
                delivery.response_code = response.status_code
                if 200 <= response.status_code < 300:
                    delivery.status = WEBHOOK_STATUS_SENT
                    delivery.delivered_at = utcnow()
                    session.add(delivery)
                    return
                delivery.error_message = f"HTTP {response.status_code}"
            except httpx.RequestError as exc:
                delivery.error_message = f"{type(exc).__name__}: {exc}"
            session.add(delivery)
            if attempt < WEBHOOK_MAX_RETRY_ATTEMPTS:
                await asyncio.sleep(_retry_backoff_seconds(attempt))


def _webhook_payload(monitor: MonitorJob, event: MonitorEvent) -> dict[str, Any]:
    snapshot = dict(monitor.last_known_values or {})
    return {
        "alert_id": str(monitor.id),
        "url": (monitor.urls or [""])[0],
        "triggered_at": event.detected_at.isoformat(),
        "condition": monitor.condition,
        "delta": {
            "field": event.field_name,
            "previous_value": event.old_value,
            "current_value": event.new_value,
            "currency": snapshot.get("currency"),
        },
        "current_snapshot": snapshot,
        "source_url": event.source_url,
        "crawl_method": monitor.last_crawl_method or "unknown",
    }


def _payload_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "alert_id": payload.get("alert_id"),
        "url": payload.get("url"),
        "condition": payload.get("condition"),
        "delta": payload.get("delta"),
    }


def _retry_backoff_seconds(attempt: int) -> float:
    backoff = min(
        WEBHOOK_RETRY_BACKOFF_MAX_SECONDS,
        WEBHOOK_RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)),
    )
    return backoff + _jitter_random.uniform(0.0, WEBHOOK_RETRY_JITTER_SECONDS)
