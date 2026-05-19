from __future__ import annotations

MAX_RETENTION_DAYS = 90
MIN_SCHEDULE_INTERVAL_HOURS = 1
MAX_URLS_PER_MONITOR = 500
MAX_CONCURRENT_MONITOR_DISPATCHES_PER_TICK = 20
SCHEDULER_POLL_INTERVAL_SECONDS = 300
SCHEDULER_DRIVER_DEV = "dev"
SCHEDULER_DRIVER_CELERY = "celery"
HEAD_CHECK_TIMEOUT_SECONDS = 5
MAX_HASH_BYTES = 5_000_000

MONITOR_STATUS_ACTIVE = "active"
MONITOR_STATUS_PAUSED = "paused"
MONITOR_STATUS_ARCHIVED = "archived"

MONITOR_PRIORITY_ON_DEMAND = "on_demand"
MONITOR_PRIORITY_PRIORITY = "priority"
MONITOR_PRIORITY_BACKGROUND = "background"

NOTIFICATION_STATUS_PENDING = "pending"
NOTIFICATION_STATUS_SENT = "sent"
NOTIFICATION_STATUS_SKIPPED = "skipped"
MONITOR_NOTIFICATION_MESSAGE_TEMPLATE = "{monitor_name}: {event_count} tracked price change(s) detected"

MONITOR_EVENT_FIELD_CHANGED = "field_changed"
MONITOR_EVENT_RECORD_NEW = "record_new"
MONITOR_EVENT_RECORD_REMOVED = "record_removed"

MONITOR_RUN_TYPE_CRAWL = "crawl"
MONITOR_RUN_TYPE_BATCH = "batch"
MONITOR_ID_SETTING_KEY = "monitor_id"
SKIP_HEAD_CHECK_KEY = "skip_head_check"
PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SURFACE = "ecommerce_detail"
PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_TRACKED_FIELDS = ["price", "availability"]
PRODUCT_INTELLIGENCE_MONITOR_DEFAULT_SCHEDULE_HOURS = 24

# Surfaces where HEAD pre-check should be skipped by default (CDN ETags unreliable)
ECOMMERCE_SURFACES = frozenset({
    "ecommerce_detail",
    "ecommerce_listing",
})

# Maps raw extraction field names to standard monitored field names
TRACKED_FIELD_ALIASES: dict[str, str] = {
    "sale_price": "price",
    "current_price": "price",
    "final_price": "price",
    "upc": "gtin",
    "ean": "gtin",
    "isbn": "gtin",
    "in_stock": "availability",
    "stock_status": "availability",
    "product_title": "title",
    "name": "title",
    "manufacturer": "brand",
    "primary_image": "image",
    "thumbnail": "image",
}
