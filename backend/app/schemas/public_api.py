from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.services.config.public_api import (
    PUBLIC_API_DEFAULT_MAX_WAIT_SECONDS,
    PUBLIC_API_MAX_BATCH_URLS,
    PUBLIC_API_MAX_WAIT_SECONDS,
    PUBLIC_API_SURFACE_ECOMMERCE,
)


class PublicExtractOptions(BaseModel):
    use_cache: bool = False
    max_wait_seconds: int = Field(
        default=PUBLIC_API_DEFAULT_MAX_WAIT_SECONDS,
        ge=1,
        le=PUBLIC_API_MAX_WAIT_SECONDS,
    )


class PublicExtractRequest(BaseModel):
    url: str = Field(min_length=1)
    surface: str = PUBLIC_API_SURFACE_ECOMMERCE
    fields: list[str] = Field(default_factory=list)
    options: PublicExtractOptions = Field(default_factory=PublicExtractOptions)

    @field_validator("fields")
    @classmethod
    def _clean_fields(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value or []:
            text = str(item or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
        return cleaned


class PublicBatchExtractRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=PUBLIC_API_MAX_BATCH_URLS)
    surface: str = PUBLIC_API_SURFACE_ECOMMERCE
    fields: list[str] = Field(default_factory=list)
    webhook_url: str | None = None


class PublicProductExtraction(BaseModel):
    url: str
    surface: str
    extracted_at: datetime
    crawl_method: str
    fields: dict[str, Any]


class PublicDomainInfo(BaseModel):
    domain: str
    known: bool
    surface: str | None = None
    last_crawled_at: datetime | None = None
    has_cached_selectors: bool = False
    acquisition_profile: str = "unknown"
