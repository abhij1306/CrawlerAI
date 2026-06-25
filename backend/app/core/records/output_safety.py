from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.config.extraction_rules import (
    DETAIL_BRAND_BOILERPLATE_VALUES,
    DETAIL_BRAND_FRAGMENT_PATTERN,
    DETAIL_BRAND_WEAK_SINGLE_TOKEN_PATTERN,
    PRODUCT_ASSET_GENERIC_PATH_TOKENS,
)
from app.core.records.url_identity import (
    detail_title_from_url,
    semantic_identity_tokens,
)
from app.core.shared.url_utils import public_asset_delivery_url
from app.extraction.contracts import (
    AssetDecision,
    CommerceDetailRecord,
    CommerceVariantRecord,
)

_TRANSPORT_FIELDS = {
    "variant_id",
    "sku",
    "gtin",
    "url",
    "image_url",
    "price",
    "currency",
    "availability",
    "stock_quantity",
}


def typed_detail_record(record: dict[str, object]) -> CommerceDetailRecord:
    cleaned = {
        key: value for key, value in record.items() if value not in (None, "", [], {})
    }
    variants = cleaned.get("variants")
    if isinstance(variants, list):
        cleaned["variants"] = tuple(
            CommerceVariantRecord.model_validate(row).model_dump(exclude_none=True)
            for row in variants
            if isinstance(row, dict)
        )
    return CommerceDetailRecord.model_validate(cleaned)


def materialize_product_assets(
    record: dict[str, object],
    lineages: dict[str, object],
    asset_decisions: tuple[AssetDecision, ...],
) -> None:
    selected = [
        item
        for item in asset_decisions
        if item.url
        and item.accepted_evidence_ids
        and not _asset_conflicts_with_product(record, item.url)
    ]
    primary = next((item for item in selected if item.role == "primary"), None)
    if primary is None:
        return
    primary_url = public_asset_delivery_url(primary.url)
    if not primary_url:
        return
    record["image_url"] = primary_url
    lineages["image_url"] = _asset_lineage(primary)
    additional: list[str] = []
    additional_lineage: list[dict[str, object]] = []
    for item in selected:
        candidate_url = public_asset_delivery_url(item.url)
        if (
            item.role != "additional"
            or not candidate_url
            or candidate_url == primary_url
        ):
            continue
        if candidate_url in additional:
            continue
        additional.append(candidate_url)
        additional_lineage.append(_asset_lineage(item))
    if additional:
        record["additional_images"] = tuple(additional)
        lineages["additional_images"] = additional_lineage


def _asset_conflicts_with_product(record: dict[str, object], asset_url: str) -> bool:
    path = urlparse(asset_url).path.casefold()
    product_text = " ".join(
        str(record.get(field) or "") for field in ("title", "brand", "sku", "url")
    )
    product_tokens = set(semantic_identity_tokens(product_text))
    candidate_tokens = {
        token
        for token in semantic_identity_tokens(detail_title_from_url(asset_url))
        if token not in PRODUCT_ASSET_GENERIC_PATH_TOKENS
    }

    product_ids = {
        re.sub(r"[-_]\d+$", "", value)
        for value in re.findall(
            r"(?<![a-z0-9])[a-z0-9-]*\d[a-z0-9-]{4,}(?![a-z0-9])",
            product_text.casefold(),
        )
    }
    asset_ids = {
        re.sub(r"[-_]\d+$", "", value)
        for value in re.findall(
            r"(?<![a-z0-9])[a-z0-9-]*\d[a-z0-9-]{4,}(?![a-z0-9])", path
        )
    }
    if product_ids and asset_ids:
        matched = any(
            p == a or a.startswith(f"{p}-") or p.startswith(f"{a}-")
            for p in product_ids
            for a in asset_ids
        )
        if not matched:
            return True

    if "sourcing_images" in path and product_tokens and candidate_tokens:
        return not bool(product_tokens & candidate_tokens)
    if len(candidate_tokens) >= 3 and len(product_tokens) >= 2:
        return not bool(product_tokens & candidate_tokens)
    return False


def _asset_identity_key(url: str) -> str:
    path = urlparse(url).path.casefold().rstrip("/")
    name = path.rsplit("/", 1)[-1]
    name = re.sub(r"_(?:\d+x|large|small|medium)$", "", name)
    return name if len(name) >= 12 else path


def _asset_lineage(decision: AssetDecision) -> dict[str, object]:
    return {
        "asset_entity_id": decision.asset_entity_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rank": decision.rank,
        "role": decision.role,
        "rule_id": decision.rule_id,
    }


def _sanitize_title(record: dict[str, object], lineages: dict[str, object]) -> None:
    title = str(record.get("title") or "").strip()
    if not title:
        return
    normalized = title.casefold()
    size_only = bool(
        re.fullmatch(
            r"(?:xxs|xs|s|m|l|xl|xxl|xxxl|small|medium|large|x-large|one size|o/s)",
            normalized,
        )
    )
    code_suffix = re.search(r"\s+p\d{6,}$", title, flags=re.IGNORECASE)
    if code_suffix and lineages.get("title", {}).get("rule_id") != "TITLE_URL_REVIEW_ONLY":
        cleaned = title[: code_suffix.start()].strip(" -_/|")
        if cleaned:
            record["title"] = cleaned.title() if cleaned.islower() else cleaned
            return
    if not size_only:
        return
    fallback = detail_title_from_url(str(record.get("url") or "")).strip()
    if fallback and fallback.casefold() != normalized:
        record["title"] = fallback
        lineages["title"] = {
            "rule_id": "title_recovered_from_product_url",
            "evidence_ids": [],
        }
    else:
        record.pop("title", None)
        lineages.pop("title", None)


def _repair_parent_sku_from_selected_variant(record: dict[str, object]) -> None:
    parent_sku = str(record.get("sku") or "").strip()
    variants = record.get("variants")
    if not parent_sku or not isinstance(variants, list):
        return
    for row in variants:
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        variant_sku = str(row.get("sku") or "").strip()
        if parent_sku == variant_id and variant_sku and variant_sku != variant_id:
            record["sku"] = variant_sku
            return


def sanitize_materialized_record(
    record: dict[str, object], lineages: dict[str, object]
) -> None:
    _sanitize_title(record, lineages)
    brand = str(record.get("brand") or "").strip()
    brand_key = brand.casefold()
    if brand and (
        brand_key in DETAIL_BRAND_BOILERPLATE_VALUES
        or re.fullmatch(DETAIL_BRAND_WEAK_SINGLE_TOKEN_PATTERN, brand_key)
        or re.fullmatch(DETAIL_BRAND_FRAGMENT_PATTERN, brand_key)
    ):
        record.pop("brand", None)
        lineages.pop("brand", None)

    if "availability" in record:
        normalized = public_availability(record.get("availability"))
        if normalized:
            record["availability"] = normalized
        else:
            record.pop("availability", None)
            lineages.pop("availability", None)

    variants = record.get("variants")
    if not isinstance(variants, list):
        return
    raw_lineage = lineages.get("variants")
    lineage_rows = raw_lineage if isinstance(raw_lineage, list) else []
    rows: list[dict[str, object]] = []
    retained_lineage: list[dict[str, object]] = []
    for index, raw_row in enumerate(variants):
        if not isinstance(raw_row, dict):
            continue
        row = dict(raw_row)
        if "availability" in row:
            normalized = public_availability(row.get("availability"))
            if normalized:
                row["availability"] = normalized
            else:
                row.pop("availability", None)
        if looks_like_size_inventory_blob(str(row.get("size") or "").strip()):
            row.pop("size", None)
        if not _has_variant_option(row) and not _has_commercial_fact(row):
            continue
        rows.append(row)
        lineage = lineage_rows[index] if index < len(lineage_rows) else {}
        retained_lineage.append(
            {
                field: value
                for field, value in lineage.items()
                if field in row
            }
            if isinstance(lineage, dict)
            else {}
        )

    rows, retained_lineage = filter_variant_product_family(
        record, rows, retained_lineage
    )
    rows, retained_lineage = _drop_aggregate_variant_rows(rows, retained_lineage)
    rows, retained_lineage = _drop_ambiguous_repeated_variants(rows, retained_lineage)
    if rows:
        record["variants"] = rows
        record["variant_count"] = len(rows)
        lineages["variants"] = retained_lineage
        _repair_parent_sku_from_selected_variant(record)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)
    lineages.pop("variants", None)


def public_availability(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    key = text.casefold().rstrip("/")
    token = key.rsplit("/", 1)[-1].replace("-", "").replace("_", "")
    if token in {"instock", "available", "availableforsale", "true", "1"}:
        return "in_stock"
    if token in {"outofstock", "soldout", "unavailable", "false", "0"}:
        return "out_of_stock"
    if token in {"limitedavailability", "limitedstock", "lowstock"}:
        return "limited_stock"
    if token in {"preorder", "preorders"}:
        return "preorder"
    if token in {"backorder", "backorders"}:
        return "backorder"
    if token == "discontinued":
        return "discontinued"
    if text in {
        "in_stock",
        "out_of_stock",
        "limited_stock",
        "preorder",
        "backorder",
        "discontinued",
    }:
        return text
    return ""


def looks_like_size_inventory_blob(value: str) -> bool:
    tokens = [token for token in value.replace(",", " ").split() if token]
    if len(tokens) < 4:
        return False
    size_tokens = 0
    for token in tokens:
        normalized = token.casefold().strip()
        if normalized in {"xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl"}:
            size_tokens += 1
        elif normalized.startswith(("uk", "us")):
            size_tokens += 1
        else:
            try:
                float(normalized)
                size_tokens += 1
            except ValueError:
                pass
    return size_tokens >= 4 and size_tokens / len(tokens) >= 0.75


def _drop_aggregate_variant_rows(
    rows: list[dict[str, object]],
    lineage_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    option_keys = ("color", "style", "flavor", "material")
    leaf_groups = {
        tuple(str(row.get(key) or "").strip().casefold() for key in option_keys)
        for row in rows
        if row.get("size") not in (None, "")
    }
    if not leaf_groups:
        return rows, lineage_rows
    keep: list[bool] = []
    for row in rows:
        group = tuple(str(row.get(key) or "").strip().casefold() for key in option_keys)
        aggregate = (
            row.get("size") in (None, "") and group in leaf_groups and any(group)
        )
        keep.append(not aggregate)
    return (
        [row for row, accepted in zip(rows, keep) if accepted],
        [lineage for lineage, accepted in zip(lineage_rows, keep) if accepted],
    )


def _drop_ambiguous_repeated_variants(
    rows: list[dict[str, object]],
    lineage_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(rows) < 8:
        return rows, lineage_rows
    option_fields = ("size", "color", "style", "flavor", "material")
    signatures = [
        tuple(str(row.get(field) or "").strip().casefold() for field in option_fields)
        for row in rows
    ]
    distinct = len(set(signatures))
    has_only_size = all(
        row.get("size") not in (None, "")
        and all(row.get(field) in (None, "") for field in option_fields[1:])
        for row in rows
    )
    if has_only_size and distinct * 2 < len(rows):
        return [], []
    return rows, lineage_rows


def _same_product_url(left: str, right: str) -> bool:
    try:
        left_url = urlparse(left)
        right_url = urlparse(right)
    except ValueError:
        return False
    left_host = (left_url.hostname or "").removeprefix("www.").casefold()
    right_host = (right_url.hostname or "").removeprefix("www.").casefold()
    if left_host != right_host:
        return False
    return left_url.path.rstrip("/").casefold() == right_url.path.rstrip("/").casefold()


def filter_variant_product_family(
    record: dict[str, object],
    rows: list[dict[str, object]],
    lineage_rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if len(rows) < 3:
        return rows, lineage_rows
    product_sku = str(record.get("sku") or "").strip()
    product_url = str(record.get("url") or "").strip()
    if not product_sku:
        matching_url_rows = [
            row
            for row in rows
            if str(row.get("url") or "").strip()
            and _same_product_url(str(row.get("url") or ""), product_url)
        ]
        matching_skus = [str(row.get("sku") or "").strip() for row in matching_url_rows]
        product_sku = next((sku for sku in matching_skus if sku), "")
    if not product_sku:
        url_codes = re.findall(r"[a-z0-9-]*\d[a-z0-9-]{4,}", product_url.casefold())
        product_sku = max(url_codes, key=len, default="")
    if not product_sku:
        return rows, lineage_rows
    matched = [
        _variant_matches_product_family(product_sku, product_url, row) for row in rows
    ]
    match_count = sum(matched)
    if match_count == 0 or match_count == len(rows):
        return rows, lineage_rows
    if match_count > max(1, len(rows) // 2):
        return rows, lineage_rows
    return (
        [row for row, keep in zip(rows, matched) if keep],
        [lineage for lineage, keep in zip(lineage_rows, matched) if keep],
    )


def _variant_matches_product_family(
    product_sku: str, product_url: str, row: dict[str, object]
) -> bool:
    row_sku = str(row.get("sku") or "").strip()
    if not row_sku:
        return False
    parent_parts = _sku_family_tokens(product_sku)
    row_parts = _sku_family_tokens(row_sku)
    if parent_parts and row_parts:
        if parent_parts[0] == row_parts[0] and len(parent_parts[0]) >= 3:
            return True
        parent_compact = "".join(parent_parts)
        row_compact = "".join(row_parts)
        prefix = 0
        for left, right in zip(parent_compact, row_compact):
            if left != right:
                break
            prefix += 1
        if prefix >= 6:
            return True
    product_codes = {
        token.upper()
        for token in semantic_identity_tokens(detail_title_from_url(product_url))
        if any(char.isdigit() for char in token) and len(token) >= 5
    }
    row_compact = "".join(row_parts)
    return any(code in row_compact for code in product_codes)


def _sku_family_tokens(value: object) -> tuple[str, ...]:
    text = str(value or "").strip().upper()
    return tuple(part for part in re.split(r"[^A-Z0-9]+", text) if part)


def _has_variant_option(row: dict[str, object]) -> bool:
    return any(
        key not in _TRANSPORT_FIELDS and value not in (None, "", [], {}, ())
        for key, value in row.items()
    )


def _has_commercial_fact(row: dict[str, object]) -> bool:
    return any(
        row.get(field) not in (None, "", [], {}, ())
        for field in ("price", "availability", "stock_quantity")
    )
