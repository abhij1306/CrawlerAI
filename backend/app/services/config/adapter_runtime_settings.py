from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings

from app.services.config.runtime_settings import settings_config


class AdapterRuntimeSettings(BaseSettings):
    """Typed env-backed runtime settings for adapter-specific heuristics."""

    model_config = settings_config(env_prefix="ADAPTER_RUNTIME_")

    ats_request_timeout_seconds: int = 12
    shopify_request_timeout_seconds: int = 6
    shopify_catalog_limit: int = 250
    shopify_max_products: int = 500
    shopify_max_option_axis_count: int = 3
    shopify_linked_variant_max_handles: int = 8
    belk_max_products: int = 500
    icims_pagination_timeout_seconds: int = 15
    icims_page_size: int = 100
    icims_max_offset: int = 1000
    icims_title_min_length: int = 3
    bullhorn_page_size: int = 200
    bullhorn_max_offset: int = 1000
    bullhorn_request_timeout_seconds: int = 15
    default_locale: str = "en-US"
    jibe_listing_default_limit: str = "100"
    jibe_listing_default_page: str = "1"
    algolia_jobs_hits_per_page: int = 100
    firestore_jobs_page_size: int = 100
    oracle_hcm_detail_page_size: int = 25
    oracle_hcm_listing_page_size: int = 100
    paycom_listing_page_size: int = 100
    saashr_pagination_size: int = 50
    saashr_job_reqs_sort: str = "desc"

    @model_validator(mode="after")
    def _validate(self) -> AdapterRuntimeSettings:
        if self.ats_request_timeout_seconds <= 0:
            raise ValueError("ats_request_timeout_seconds must be > 0")
        if self.shopify_request_timeout_seconds <= 0:
            raise ValueError("shopify_request_timeout_seconds must be > 0")
        if self.shopify_catalog_limit <= 0:
            raise ValueError("shopify_catalog_limit must be > 0")
        if self.shopify_max_products <= 0:
            raise ValueError("shopify_max_products must be > 0")
        if self.shopify_max_option_axis_count <= 0:
            raise ValueError("shopify_max_option_axis_count must be > 0")
        if self.shopify_linked_variant_max_handles <= 0:
            raise ValueError("shopify_linked_variant_max_handles must be > 0")
        if self.belk_max_products <= 0:
            raise ValueError("belk_max_products must be > 0")
        if self.icims_pagination_timeout_seconds <= 0:
            raise ValueError("icims_pagination_timeout_seconds must be > 0")
        if self.icims_page_size <= 0:
            raise ValueError("icims_page_size must be > 0")
        if self.icims_max_offset <= 0:
            raise ValueError("icims_max_offset must be > 0")
        if self.icims_title_min_length <= 0:
            raise ValueError("icims_title_min_length must be > 0")
        if self.icims_max_offset < self.icims_page_size:
            raise ValueError("icims_max_offset must be >= icims_page_size")
        if self.bullhorn_page_size <= 0:
            raise ValueError("bullhorn_page_size must be > 0")
        if self.bullhorn_max_offset <= 0:
            raise ValueError("bullhorn_max_offset must be > 0")
        if self.bullhorn_max_offset < self.bullhorn_page_size:
            raise ValueError("bullhorn_max_offset must be >= bullhorn_page_size")
        if self.bullhorn_request_timeout_seconds <= 0:
            raise ValueError("bullhorn_request_timeout_seconds must be > 0")
        if self.paycom_listing_page_size <= 0:
            raise ValueError("paycom_listing_page_size must be > 0")
        if self.algolia_jobs_hits_per_page <= 0:
            raise ValueError("algolia_jobs_hits_per_page must be > 0")
        if self.firestore_jobs_page_size <= 0:
            raise ValueError("firestore_jobs_page_size must be > 0")
        if self.oracle_hcm_detail_page_size <= 0:
            raise ValueError("oracle_hcm_detail_page_size must be > 0")
        if self.oracle_hcm_listing_page_size <= 0:
            raise ValueError("oracle_hcm_listing_page_size must be > 0")
        if self.saashr_pagination_size <= 0:
            raise ValueError("saashr_pagination_size must be > 0")
        if not str(self.saashr_job_reqs_sort or "").strip():
            raise ValueError("saashr_job_reqs_sort must not be empty")
        return self


adapter_runtime_settings = AdapterRuntimeSettings()

__all__ = ["AdapterRuntimeSettings", "adapter_runtime_settings"]
