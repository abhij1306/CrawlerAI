from __future__ import annotations

from typing import Any

from app.services.acquisition.runtime import classify_blocked_page
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.extract.content_listing_handler import validate_table_rows_quality
from app.services.extract.detail.identity.core import (
    listing_detail_like_path,
    listing_url_is_structural,
)
from app.services.extract.detail.assembly.record_assembly import extract_detail_records
from app.services.extract.detail.assembly.final_cleanup import repair_ecommerce_detail_record_quality
from app.services.extract.detail.price.core import drop_low_signal_zero_detail_price
from app.services.extract.listing_candidate_ranking import best_listing_candidate_set
from app.services.extract.listing_record_finalizer import finalize_listing_price_fields
from app.services.extract.network_listing_mapper import (
    backfill_listing_rows_from_network,
    extract_listing_rows_from_network,
    listing_identity_from_url,
)
from app.services.listing_extractor import (
    apply_listing_integrity_gate,
    extract_listing_records,
)
from app.services.pipeline.listing_integrity import (
    propagate_listing_integrity_to_diagnostics,
)
from app.services.pipeline.raw_json import extract_raw_json_records
from app.services.pipeline.sitemap import extract_xml_sitemap_records
from app.services.shared.field_coerce import (
    clean_text,
    direct_record_to_surface_fields,
    finalize_record,
    is_title_noise,
)

def extract_records(
    html: str,
    page_url: str,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str | None = None,
    requested_fields: list[str] | None = None,
    adapter_records: list[dict] | None = None,
    network_payloads: list[dict[str, object]] | None = None,
    artifacts: dict[str, object] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    extraction_runtime_snapshot: dict[str, object] | None = None,
    content_type: str | None = None,
    browser_diagnostics: dict[str, object] | None = None,
) -> list[dict]:
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_surface or normalized_surface == "auto":
        raise ValueError(f"Surface must be explicit, got: {surface!r}")
    xml_records = extract_xml_sitemap_records(
        html,
        page_url,
        normalized_surface,
        max_records=max_records,
        content_type=content_type,
    )
    if xml_records:
        return xml_records
    raw_json_surface_field_overlap_absolute = int(
        crawler_runtime_settings.raw_json_surface_field_overlap_absolute
    )
    raw_json_surface_field_overlap_ratio = float(
        crawler_runtime_settings.raw_json_surface_field_overlap_ratio
    )
    json_records = extract_raw_json_records(
        html,
        page_url,
        normalized_surface,
        max_records=max_records,
        requested_fields=requested_fields,
        content_type=content_type,
        raw_json_surface_field_overlap_absolute=(
            raw_json_surface_field_overlap_absolute
        ),
        raw_json_surface_field_overlap_ratio=raw_json_surface_field_overlap_ratio,
    )
    if json_records:
        if "listing" in normalized_surface:
            return json_records
        return _postprocess_detail_records(
            json_records[:max_records],
            html=html,
            page_url=page_url,
            requested_page_url=requested_page_url,
        )
    if _html_is_blocked_extraction_shell(html):
        return []
    if "listing" in normalized_surface:
        adapter_rows: list[dict[str, Any]] = []
        if adapter_records:
            for record in list(adapter_records or []):
                if not isinstance(record, dict):
                    continue
                shaped = direct_record_to_surface_fields(
                    record,
                    surface=normalized_surface,
                    page_url=page_url,
                    requested_fields=requested_fields,
                    base_fields={
                        "source_url": page_url,
                        "_source": str(record.get("_source") or "adapter"),
                    },
                )
                if shaped.get("title") and shaped.get("url"):
                    adapter_rows.append(shaped)
        listing_rows = extract_listing_records(
            html,
            page_url,
            normalized_surface,
            max_records=max_records,
            artifacts=artifacts,
            selector_rules=selector_rules,
            network_payloads=network_payloads,
        )
        network_rows = extract_listing_rows_from_network(
            network_payloads,
            page_url=page_url,
            surface=normalized_surface,
            max_records=max_records,
        )
        backfill_listing_rows_from_network(
            adapter_rows,
            network_payloads=network_payloads,
        )
        backfill_listing_rows_from_network(
            listing_rows,
            network_payloads=network_payloads,
        )
        adapter_rows = _finalize_listing_rows(adapter_rows)
        listing_rows = _finalize_listing_rows(listing_rows)
        network_rows = _finalize_listing_rows(network_rows)
        if (
            normalized_surface == "content_listing"
            and listing_rows
            and all(row.get("_extraction_mode") == "table_rows" for row in listing_rows)
            and validate_table_rows_quality(listing_rows)
        ):
            return listing_rows[:max_records]
        _backfill_listing_rows_from_adapter(
            listing_rows,
            adapter_rows=adapter_rows,
        )
        candidate_sets: list[tuple[str, list[dict[str, Any]]]] = []
        if adapter_rows:
            candidate_sets.append(("adapter", adapter_rows))
        if listing_rows:
            candidate_sets.append(("generic", listing_rows))
        if network_rows:
            candidate_sets.append(("network", network_rows))
        combined_rows = [*listing_rows, *adapter_rows, *network_rows]
        if len(candidate_sets) >= 2 and combined_rows:
            candidate_sets.append(("combined", combined_rows))
        if candidate_sets:
            candidate_rows = best_listing_candidate_set(
                candidate_sets,
                page_url=page_url,
                surface=normalized_surface,
                max_records=max_records,
                title_is_noise=is_title_noise,
                url_is_structural=listing_url_is_structural,
                detail_like_url=lambda candidate_url: listing_detail_like_path(
                    candidate_url,
                    is_job=str(normalized_surface or "").startswith("job_"),
                ),
            )[:max_records]
            gated_rows = apply_listing_integrity_gate(
                candidate_rows,
                page_url=page_url,
                surface=normalized_surface,
                artifacts=artifacts,
            )
            propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
            return gated_rows
        propagate_listing_integrity_to_diagnostics(artifacts, browser_diagnostics)
        return []
    detail_rows = _postprocess_detail_records(
        extract_detail_records(
            html,
            page_url,
            normalized_surface,
            requested_page_url=requested_page_url,
            requested_fields=requested_fields,
            adapter_records=adapter_records,
            network_payloads=network_payloads,
            selector_rules=selector_rules,
            extraction_runtime_snapshot=extraction_runtime_snapshot,
        )[:max_records],
        html=html,
        page_url=page_url,
        requested_page_url=requested_page_url,
        repair_quality=False,
    )
    return detail_rows


def _html_is_blocked_extraction_shell(html: str) -> bool:
    if not str(html or "").strip():
        return False
    classification = classify_blocked_page(html, 0)
    if classification.blocked:
        return True
    return bool(
        (classification.active_provider_hits or classification.challenge_element_hits)
        and (
            classification.strong_hits
            or classification.weak_hits
            or classification.title_matches
        )
    )


def _finalize_listing_rows(rows: list[dict]) -> list[dict[str, Any]]:
    return [
        finalize_listing_price_fields(dict(row))
        for row in rows
        if isinstance(row, dict)
    ]


def _postprocess_detail_records(
    records: list[dict],
    *,
    html: str,
    page_url: str,
    requested_page_url: str | None,
    repair_quality: bool = True,
) -> list[dict]:
    rows: list[dict] = []
    for record in list(records or []):
        if not isinstance(record, dict):
            continue
        if repair_quality:
            repair_ecommerce_detail_record_quality(
                record,
                html=html,
                page_url=page_url,
                requested_page_url=requested_page_url,
            )
        drop_low_signal_zero_detail_price(record)
        rows.append(finalize_record(record, surface="ecommerce_detail"))
    return rows


def _backfill_listing_rows_from_adapter(
    rows: list[dict],
    *,
    adapter_rows: list[dict[str, Any]],
) -> None:
    if not rows or not adapter_rows:
        return
    adapter_by_url = {
        str(row.get("url") or "").strip(): row
        for row in adapter_rows
        if isinstance(row, dict) and str(row.get("url") or "").strip()
    }
    adapter_by_identity = {
        identity: row
        for row in adapter_rows
        if isinstance(row, dict) and (identity := _listing_row_identity(row))
    }
    if not adapter_by_url and not adapter_by_identity:
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        adapter_row = adapter_by_url.get(str(row.get("url") or "").strip())
        if adapter_row is None:
            row_identity = _listing_row_identity(row)
            if row_identity:
                adapter_row = adapter_by_identity.get(row_identity)
        if not isinstance(adapter_row, dict):
            continue
        for field_name, value in adapter_row.items():
            if str(field_name).startswith("_") or value in (None, "", [], {}):
                continue
            if row.get(field_name) in (None, "", [], {}):
                row[field_name] = value


def _listing_row_identity(row: dict[str, Any]) -> str:
    product_id = clean_text(
        row.get("product_id") or row.get("productId") or row.get("sku")
    )
    if product_id:
        return product_id.lower()
    return listing_identity_from_url(str(row.get("url") or ""))


