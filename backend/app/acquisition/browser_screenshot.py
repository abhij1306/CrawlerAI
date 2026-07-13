"""Temporary browser screenshot capture."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)


async def capture_browser_screenshot(page: Any) -> str:
    temp_dir = Path(settings.artifacts_dir) / "tmp" / "browser_screenshots"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        temp_path = temp_dir / f"browser-screenshot-{uuid.uuid4().hex}.png"
        await page.screenshot(path=temp_path, full_page=True, type="png")
        if temp_path.is_file() and temp_path.stat().st_size > 0:
            return str(temp_path)
    except Exception:
        logger.debug("Browser screenshot capture failed", exc_info=True)
    if temp_path is not None:
        temp_path.unlink(missing_ok=True)
    return ""
