from __future__ import annotations

from app.core.records.attribute_normalization import audience_gender_from_path
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_url_looks_like_product,
    selected_variant_axes,
)
from app.extraction.collectors._helpers import evidence
from app.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class UrlCollector:
    collector_id = "url"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        del artifacts
        page_url = bundle.final_url or bundle.requested_url
        title = detail_title_from_url(page_url)
        selected_axes = selected_variant_axes(bundle.requested_url)
        if not (selected_axes or title or detail_url_looks_like_product(page_url)):
            return ()
        product_hint = EntityHint(entity_type="product", url=bundle.final_url)
        product_url = evidence(
            bundle,
            "url",
            "url",
            "product.url",
            bundle.final_url,
            SourceLocator(kind="url_component", value="url"),
            hint=product_hint,
            directness="inferred",
            confidence=0.55,
        )
        rows = [product_url]
        if title:
            rows.append(
                evidence(
                    bundle,
                    "url",
                    "url",
                    "product.title",
                    title,
                    SourceLocator(kind="url_component", value="path"),
                    hint=product_hint,
                    directness="inferred",
                    confidence=0.35,
                    subject_id=product_url.subject_id,
                )
            )
        # The requested path states the product the caller asked for; a site may
        # redirect a unisex PDP into a gendered department, so the served URL is
        # only a fallback.
        gender = audience_gender_from_path(
            bundle.requested_url
        ) or audience_gender_from_path(page_url)
        if gender:
            rows.append(
                evidence(
                    bundle,
                    "url",
                    "url",
                    "product.gender",
                    gender,
                    SourceLocator(kind="url_component", value="path"),
                    hint=product_hint,
                    directness="inferred",
                    confidence=0.4,
                    subject_id=product_url.subject_id,
                )
            )
        return tuple(rows)
