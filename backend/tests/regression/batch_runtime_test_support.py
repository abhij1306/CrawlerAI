from __future__ import annotations

import asyncio

from types import SimpleNamespace

import pytest

from app.models.crawl_settings import CrawlRunSettings

from app.crawl import batch_runtime as batch_runtime_module

from app.crawl.pipeline import extraction_loop, url_worker

from app.crawl.pipeline import record_extraction_stage

from app.crawl.batch_runtime import process_run
from app.crawl.pipeline.url_worker import (
    parallel_url_concurrency,
    parallel_worker_record_limit,
)

from app.crawl.pipeline.run_progress import assemble_run_summary_payload

from app.crawl.state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    set_control_request,
)

from app.core.config.sitemap import SITEMAP_DEFAULT_MAX_URLS

from app.acquisition.acquirer import PageAcquisitionResult

from app.crawl.crud import create_crawl_run, get_run_records

from app.models.crawl_run import CrawlRecord

from app.crawl.pipeline.types import URLProcessingResult

from app.crawl.robots_policy import (
    ROBOTS_ALLOWED,
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    RobotsPolicyResult,
)

from sqlalchemy import select

from sqlalchemy.exc import PendingRollbackError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CommitTrackingSession:
    checked_out = False
    commit_count = 0

    async def commit(self) -> None:
        self.checked_out = False
        self.commit_count += 1


def _detail_html() -> str:
    return """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "brand": "Example Works",
          "description": "A deterministic widget",
          "image": "https://example.com/images/widget-prime.jpg",
          "sku": "W-100",
          "offers": {"price": "19.99", "priceCurrency": "USD", "availability": "InStock"}
        }
        </script>
      </head>
      <body><h1>Widget Prime</h1></body>
    </html>
    """


def _listing_shell_html() -> str:
    return "<html><body><h1>Empty category</h1></body></html>"


__all__ = [
    "CONTROL_REQUEST_KILL",
    "CONTROL_REQUEST_PAUSE",
    "ROBOTS_ALLOWED",
    "ROBOTS_FETCH_FAILURE",
    "ROBOTS_MISSING",
    "SITEMAP_DEFAULT_MAX_URLS",
    "AsyncSession",
    "CommitTrackingSession",
    "CrawlRecord",
    "CrawlRunSettings",
    "CrawlStatus",
    "PageAcquisitionResult",
    "PendingRollbackError",
    "RobotsPolicyResult",
    "SimpleNamespace",
    "URLProcessingResult",
    "_detail_html",
    "_listing_shell_html",
    "assemble_run_summary_payload",
    "async_sessionmaker",
    "asyncio",
    "batch_runtime_module",
    "create_crawl_run",
    "extraction_loop",
    "get_run_records",
    "parallel_url_concurrency",
    "parallel_worker_record_limit",
    "process_run",
    "pytest",
    "record_extraction_stage",
    "select",
    "set_control_request",
    "url_worker",
]
