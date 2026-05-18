# Shopify platform adapter.
from __future__ import annotations

import json
import re
from json import loads as parse_json
import math
from urllib.parse import parse_qsl, urljoin, urlparse, urlsplit

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_identity_merge import split_variant_axes
from app.services.extract.variant_normalization.contract import (
    flatten_variants_for_public_output,
)
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import clean_text, text_or_none

_FETCH_ERRORS = (OSError, RuntimeError, ValueError, TypeError, json.JSONDecodeError)


class ShopifyAdapter(BaseAdapter):
    name = "shopify"
    domains: list[str] = []  # any domain can be Shopify; detected by signals

    async def can_handle(self, url: str, html: str) -> bool:
        signals = [
            "Shopify.theme" in html,
            "cdn.shopify.com" in html,
            '"shopify"' in html.lower(),
            "myshopify.com" in url,
        ]
        return any(signals)

    async def extract(
        self,
        url: str,
        html: str,
        surface: str,
        proxy: str | None = None,
    ) -> AdapterResult:
        records: list[dict] = []
        embedded = self._extract_embedded_product(html, url)
        if embedded:
            records.extend(embedded)
        # Listing pages are best served by the public collection endpoint.
        # Detail pages still probe the public endpoint to enrich the embedded
        # payload with the fuller Shopify product object.
        if surface in ("ecommerce_listing", "ecommerce_detail"):
            api_records = await self.try_public_endpoint(
                url,
                html=html,
                surface=surface,
                proxy=proxy,
            )
            if api_records:
                if surface == "ecommerce_detail" and records:
                    records = [self._merge_product_records(records[0], api_records[0])]
                else:
                    records = api_records
        return self._result(records)

    async def try_public_endpoint(
        self,
        url: str,
        html: str = "",
        surface: str = "",
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        """Fetch Shopify product endpoint data.

        Listing pages use `/collections/<handle>/products.json` when possible so
        records stay scoped to the requested collection instead of the entire catalog.
        Detail pages use `/products/<handle>.js` to avoid returning unrelated products.
        """
        parsed = urlparse(url)
        products: list[dict] = []
        if surface == "ecommerce_detail":
            handle = self._extract_product_handle(parsed.path)
            if not handle:
                return []
            linked_handles = self._linked_variant_product_handles(
                html,
                url,
                current_handle=handle,
            )
            if not linked_handles:
                linked_handles = [(handle, "", "")]
            product_records: list[dict] = []
            for linked_handle, axis_value, axis_key in linked_handles[
                : adapter_runtime_settings.shopify_linked_variant_max_handles
            ]:
                api_url = f"{parsed.scheme}://{parsed.netloc}/products/{linked_handle}.js"
                try:
                    data = await self._request_json(
                        api_url,
                        proxy=proxy,
                        timeout_seconds=adapter_runtime_settings.shopify_request_timeout_seconds,
                    )
                except _FETCH_ERRORS:
                    continue
                if not isinstance(data, dict):
                    continue
                record = self._build_product_record(
                    data,
                    page_url=urljoin(
                        url,
                        self._localized_product_path(parsed.path, linked_handle),
                    ),
                    surface=surface,
                )
                if not axis_value:
                    axis_value = self._linked_axis_value_from_product(
                        data,
                        axis_key=axis_key,
                        current_handle=handle,
                    )
                self._apply_linked_axis(record, axis_key=axis_key, axis_value=axis_value)
                product_records.append(record)
            return self._merge_linked_product_records(product_records)
        else:
            collection_handle = self._extract_collection_handle(parsed.path)
            api_path = (
                f"/collections/{collection_handle}/products.json"
                if collection_handle
                else "/products.json"
            )
            max_pages = max(
                1,
                math.ceil(
                    adapter_runtime_settings.shopify_max_products
                    / adapter_runtime_settings.shopify_catalog_limit
                ),
            )
            for page in range(1, max_pages + 1):
                api_url = (
                    f"{parsed.scheme}://{parsed.netloc}{api_path}"
                    f"?limit={adapter_runtime_settings.shopify_catalog_limit}&page={page}"
                )
                try:
                    data = await self._request_json(
                        api_url,
                        proxy=proxy,
                        timeout_seconds=adapter_runtime_settings.shopify_request_timeout_seconds,
                    )
                except _FETCH_ERRORS:
                    break
                if not isinstance(data, dict):
                    break
                batch = data.get("products", [])
                if not isinstance(batch, list) or not batch:
                    break
                products.extend(
                    product for product in batch if isinstance(product, dict)
                )
                if (
                    len(products) >= adapter_runtime_settings.shopify_max_products
                    or len(batch) < adapter_runtime_settings.shopify_catalog_limit
                ):
                    break

        return [
            self._build_product_record(product, page_url=url, surface=surface)
            for product in products[: adapter_runtime_settings.shopify_max_products]
            if isinstance(product, dict)
        ]

    def _linked_variant_product_handles(
        self,
        html: str,
        page_url: str,
        *,
        current_handle: str,
    ) -> list[tuple[str, str, str]]:
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        parsed = urlparse(page_url)
        current_host = parsed.netloc.lower()
        current_handle = str(current_handle or "").strip()
        rows: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for group in soup.select(
            "[role='radiogroup'], fieldset, [class*='swatch' i], "
            "[class*='variant' i], [class*='option' i], [data-testid*='swatch' i], "
            "[role='group'][aria-label]"
        ):
            axis_key = self._linked_group_axis(group)
            if axis_key not in {"color", "scent", "style", "material"}:
                continue
            anchors = group.select("a[href*='/products/']")
            if len(anchors) < 2:
                continue
            for anchor in anchors:
                href = text_or_none(anchor.get("href"))
                if not href:
                    continue
                absolute = urljoin(page_url, href)
                linked_parsed = urlparse(absolute)
                if linked_parsed.netloc.lower() != current_host:
                    continue
                handle = self._extract_product_handle(linked_parsed.path)
                if not handle or handle in seen:
                    continue
                label = self._linked_axis_value(anchor, handle, current_handle)
                rows.append((handle, label, axis_key))
                seen.add(handle)
                if len(rows) >= adapter_runtime_settings.shopify_linked_variant_max_handles:
                    return rows
        if current_handle and current_handle not in seen and rows:
            rows.insert(0, (current_handle, "", rows[0][2]))
        if not rows:
            rows.extend(
                self._linked_variant_handles_from_raw_html(
                    html,
                    current_handle=current_handle,
                )
            )
        return rows

    def _linked_variant_handles_from_raw_html(
        self,
        html: str,
        *,
        current_handle: str,
    ) -> list[tuple[str, str, str]]:
        pattern = re.compile(r"/products/([a-z0-9][a-z0-9-]+)", re.I)
        handles = [match.group(1).strip("-") for match in pattern.finditer(html)]
        family_prefix = self._linked_handle_family_prefix(current_handle, handles)
        if not family_prefix:
            return []
        axis_key = "scent" if any(
            token in family_prefix for token in ("mist", "fragrance", "scent")
        ) else "color"
        rows: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for handle in handles:
            if not handle.startswith(f"{family_prefix}-") and handle != current_handle:
                continue
            if handle in seen:
                continue
            value = self._axis_value_from_handle(handle, family_prefix)
            rows.append((handle, value, axis_key))
            seen.add(handle)
            if len(rows) >= adapter_runtime_settings.shopify_linked_variant_max_handles:
                break
        if current_handle and current_handle not in seen and rows:
            rows.insert(
                0,
                (
                    current_handle,
                    self._axis_value_from_handle(current_handle, family_prefix),
                    axis_key,
                ),
            )
        return rows

    def _linked_handle_family_prefix(
        self,
        current_handle: str,
        handles: list[str] | None = None,
    ) -> str:
        tokens = [token for token in str(current_handle or "").split("-") if token]
        if len(tokens) < 3:
            return ""
        handle_set = {
            str(handle or "").strip()
            for handle in list(handles or [])
            if str(handle or "").strip()
        }
        for prefix_len in range(len(tokens) - 1, 2, -1):
            prefix = "-".join(tokens[:prefix_len])
            matches = [
                handle
                for handle in handle_set
                if handle == current_handle or handle.startswith(f"{prefix}-")
            ]
            if len(set(matches)) >= 2:
                return prefix
        if any(token in tokens for token in ("mist", "fragrance", "scent")) and len(tokens) > 3:
            return "-".join(tokens[:-2])
        return "-".join(tokens[:-1])

    def _linked_group_axis(self, group: object) -> str:
        if not hasattr(group, "get"):
            return ""
        values: list[object] = [
            group.get("aria-label"),
            group.get("data-option-name"),
            group.get("name"),
            group.get("id"),
            group.get("data-testid"),
            group.get("class"),
        ]
        legend = group.find("legend") if hasattr(group, "find") else None
        if legend is not None:
            values.append(legend.get_text(" ", strip=True))
        for value in values:
            if isinstance(value, list):
                value = " ".join(str(item) for item in value if item)
            axis_key = normalized_variant_axis_key(value)
            if axis_key:
                return axis_key
        return ""

    def _linked_axis_value(
        self,
        anchor: object,
        handle: str,
        current_handle: str,
    ) -> str:
        candidates: list[object] = []
        if hasattr(anchor, "get"):
            candidates.extend(
                [
                    anchor.get("aria-label"),
                    anchor.get("title"),
                    anchor.get("data-value"),
                    anchor.get("data-option-value"),
                    anchor.get_text(" ", strip=True) if hasattr(anchor, "get_text") else "",
                ]
            )
            for parent in (anchor.find_parent("button"), anchor.find_parent("label")):
                if parent is not None:
                    candidates.extend(
                        [
                            parent.get("aria-label"),
                            parent.get("title"),
                            parent.get("data-value"),
                            parent.get("data-option-value"),
                            parent.get_text(" ", strip=True),
                        ]
                    )
        for candidate in candidates:
            value = self._clean_linked_axis_label(candidate)
            if value:
                return value
        return self._axis_value_from_handle(handle, current_handle)

    def _linked_axis_value_from_product(
        self,
        product: dict,
        *,
        axis_key: str,
        current_handle: str,
    ) -> str:
        for field_name in (
            axis_key,
            "shade" if axis_key == "scent" else "",
            "color" if axis_key == "color" else "",
            "colour" if axis_key == "color" else "",
        ):
            value = text_or_none(product.get(field_name)) if field_name else None
            if value:
                return value
        title = text_or_none(product.get("title"))
        if title:
            parts = re.split(r"\s[-–—�]\s", title, maxsplit=1)
            if len(parts) == 2 and text_or_none(parts[1]):
                return text_or_none(parts[1]) or ""
        handle = text_or_none(product.get("handle")) or current_handle
        family_prefix = self._linked_handle_family_prefix(current_handle)
        return self._axis_value_from_handle(handle, family_prefix or current_handle)

    def _clean_linked_axis_label(self, value: object) -> str:
        label = clean_text(value)
        if not label:
            return ""
        label = re.sub(
            r"^(?:choose|select|view|alternate|product|color|variant)\s+",
            "",
            label,
            flags=re.I,
        )
        label = re.sub(
            r"^(?:view\s+)?alternate\s+product\s+color\s+",
            "",
            label,
            flags=re.I,
        )
        label = re.sub(r"\s+(?:variant|selected|unselected)$", "", label, flags=re.I)
        return clean_text(label)

    def _axis_value_from_handle(self, handle: str, current_handle: str) -> str:
        handle_tokens = [token for token in str(handle or "").split("-") if token]
        current_tokens = [token for token in str(current_handle or "").split("-") if token]
        common_prefix = 0
        for left, right in zip(handle_tokens, current_tokens):
            if left != right:
                break
            common_prefix += 1
        tail = handle_tokens[common_prefix:] or handle_tokens[-1:]
        return clean_text(" ".join(token.capitalize() for token in tail))

    def _apply_linked_axis(
        self,
        record: dict,
        *,
        axis_key: str,
        axis_value: str,
    ) -> None:
        if not axis_key or not axis_value:
            return
        if axis_key == "scent":
            record.pop("color", None)
        if record.get(axis_key) in (None, "", [], {}):
            record[axis_key] = axis_value
        variants = record.get("variants")
        if not isinstance(variants, list):
            variant = {
                field_name: record.get(field_name)
                for field_name in (
                    "sku",
                    "price",
                    "original_price",
                    "currency",
                    "url",
                    "image_url",
                    "availability",
                    "stock_quantity",
                )
                if record.get(field_name) not in (None, "", [], {})
            }
            variant[axis_key] = axis_value
            record["variants"] = [variant]
            record["variant_count"] = 1
            return
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            if axis_key == "scent":
                variant.pop("color", None)
            if variant.get(axis_key) in (None, "", [], {}):
                variant[axis_key] = axis_value

    def _merge_linked_product_records(self, records: list[dict]) -> list[dict]:
        if not records:
            return []
        primary = dict(records[0])
        variants: list[dict] = []
        for record in records:
            for variant in record.get("variants") or []:
                if isinstance(variant, dict):
                    variants.append(variant)
        merged_variants = self._dedupe_variants(variants)
        if merged_variants:
            primary["variants"] = merged_variants
            primary["variant_count"] = len(merged_variants)
        return [primary]

    def _extract_product_handle(self, path: str) -> str | None:
        match = re.search(r"/products/([^/?#]+)", path)
        return match.group(1) if match else None

    def _extract_collection_handle(self, path: str) -> str | None:
        match = re.search(r"/collections/([^/?#]+)", path)
        return match.group(1) if match else None

    def _extract_embedded_product(self, html: str, url: str) -> list[dict]:
        """Extract product data from Shopify's embedded JSON in <script> tags."""
        records = []
        # Look for ShopifyAnalytics.meta or similar
        pattern = r"var\s+meta\s*=\s*(\{.*?\});"
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                meta = parse_json(match.group(1))
                product = meta.get("product", {})
                if product.get("title"):
                    option_names = self._option_names(product.get("options"))
                    normalized_variants = [
                        normalized
                        for variant in (product.get("variants") or [])
                        if isinstance(variant, dict)
                        if (
                            normalized := self._normalize_variant(
                                variant,
                                option_names=option_names,
                                scheme=urlparse(url).scheme or "https",
                                base_url=url,
                            )
                        )
                    ]
                    normalized_variants = self._dedupe_variants(normalized_variants)
                    active_variant = self._select_shopify_variant(
                        normalized_variants,
                        base_url=url,
                    )
                    axes = self._variant_axes(normalized_variants)
                    # Only the single-value attributes are needed on this
                    # branch; discard the selectable-axes half of the tuple.
                    _, single_value_attributes = self._split_selectable_axes(axes)
                    selected_price = (
                        active_variant.get("price")
                        if isinstance(active_variant, dict)
                        else product.get("price")
                    )
                    flat_variants = flatten_variants_for_public_output(
                        normalized_variants,
                        page_url=url,
                    )
                    records.append(
                        {
                            "title": product.get("title"),
                            "brand": product.get("vendor"),
                            "vendor": product.get("vendor"),
                            "price": normalize_decimal_price(
                                selected_price,
                                interpret_integral_as_cents=True,
                            ),
                            "category": product.get("type"),
                            "product_type": product.get("type"),
                            "product_id": str(product.get("id"))
                            if product.get("id") not in (None, "", [], {})
                            else None,
                            "variants": flat_variants,
                            "variant_count": len(flat_variants or []) or None,
                            "product_attributes": single_value_attributes or None,
                        }
                    )
            except (json.JSONDecodeError, TypeError):
                pass
        return records

    def _image_src(self, image: object) -> str | None:
        if isinstance(image, str):
            return image or None
        if isinstance(image, dict):
            return image.get("src") or image.get("url") or None
        return None

    def _normalize_url(self, value: str | None, scheme: str) -> str | None:
        if not value:
            return None
        if value.startswith("//"):
            return f"{scheme}:{value}"
        return value

    def _option_names(self, raw_options: object) -> list[str]:
        names: list[str] = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if isinstance(option, str):
                    names.append(option)
                elif isinstance(option, dict):
                    label = option.get("name") or option.get("title")
                    if label:
                        names.append(str(label))
        return names

    def _normalize_variant(
        self,
        variant: dict,
        *,
        option_names: list[str],
        scheme: str,
        base_url: str,
    ) -> dict | None:
        row: dict[str, object] = {}
        if variant.get("id") not in (None, "", [], {}):
            row["variant_id"] = str(variant.get("id"))
            row["url"] = (
                f"{base_url}{'&' if '?' in base_url else '?'}variant={row['variant_id']}"
            )
        if variant.get("sku"):
            row["sku"] = variant.get("sku")
        if variant.get("barcode"):
            row["barcode"] = variant.get("barcode")
        price = normalize_decimal_price(
            variant.get("price"),
            interpret_integral_as_cents=True,
        )
        if price is not None:
            row["price"] = price
        original_price = normalize_decimal_price(
            variant.get("compare_at_price"),
            interpret_integral_as_cents=True,
        )
        if original_price is not None:
            row["original_price"] = original_price
        raw_available = variant.get("available")
        if raw_available is not None:
            if isinstance(raw_available, bool):
                available = raw_available
            elif isinstance(raw_available, str):
                available = raw_available.strip().lower() in {"true", "1", "yes"}
            elif isinstance(raw_available, (int, float)):
                available = raw_available != 0
            else:
                available = False
            row["available"] = available
            row["availability"] = "in_stock" if available else "out_of_stock"
        featured = self._normalize_url(
            self._image_src(variant.get("featured_image")), scheme
        )
        if featured:
            row["image_url"] = featured
        option_values: dict[str, str] = {}
        raw_options_payload = variant.get("options")
        raw_options: list[object] = (
            raw_options_payload if isinstance(raw_options_payload, list) else []
        )
        for index in range(
            1,
            adapter_runtime_settings.shopify_max_option_axis_count + 1,
        ):
            axis_name = (
                option_names[index - 1]
                if index - 1 < len(option_names)
                else f"option_{index}"
            )
            axis_key = normalized_variant_axis_key(axis_name) or self._normalize_axis(
                axis_name
            )
            value = variant.get(f"option{index}")
            if value in (None, "", [], {}) and index - 1 < len(raw_options):
                value = raw_options[index - 1]
            if value in (None, "", [], {}):
                continue
            option_values[axis_key] = str(value)
            if axis_key in {"color", "size"}:
                row[axis_key] = str(value)
        if option_values:
            row["option_values"] = option_values
        return row or None

    def _build_product_record(
        self,
        product: dict,
        *,
        page_url: str,
        surface: str,
    ) -> dict:
        parsed = urlparse(page_url)
        variants = (
            product.get("variants", [])
            if isinstance(product.get("variants"), list)
            else []
        )
        option_names = self._option_names(product.get("options"))
        product_url = urljoin(
            page_url,
            self._localized_product_path(parsed.path, product.get("handle")),
        )
        normalized_variants = [
            normalized
            for variant in variants
            if isinstance(variant, dict)
            if (
                normalized := self._normalize_variant(
                    variant,
                    option_names=option_names,
                    scheme=parsed.scheme,
                    base_url=product_url,
                )
            )
        ]
        normalized_variants = self._dedupe_variants(normalized_variants)
        active_variant = self._select_shopify_variant(
            normalized_variants,
            base_url=page_url,
        )
        axes = self._variant_axes(normalized_variants)
        # Only the single-value attributes are needed here; discard the
        # selectable-axes half of the tuple.
        _, single_value_attributes = self._split_selectable_axes(axes)
        flat_variants = flatten_variants_for_public_output(
            normalized_variants,
            page_url=page_url,
        )
        images = [
            image_url
            for img in product.get("images", [])
            if (image_url := self._normalize_url(self._image_src(img), parsed.scheme))
        ]
        raw_tags = product.get("tags")
        tags = (
            [
                token
                for token in (item.strip() for item in raw_tags.strip().split(","))
                if token
            ]
            if isinstance(raw_tags, str) and raw_tags.strip()
            else ([] if isinstance(raw_tags, str) else product.get("tags", []))
        )
        record = {
            "title": product.get("title"),
            "brand": product.get("vendor"),
            "description": product.get("body_html", ""),
            "url": product_url,
            "image_url": images[0] if images else None,
            "additional_images": ", ".join(images[1:]) if len(images) > 1 else None,
            "price": active_variant.get("price")
            if isinstance(active_variant, dict)
            else None,
            "original_price": active_variant.get("original_price")
            if isinstance(active_variant, dict)
            else None,
            "sku": active_variant.get("sku")
            if isinstance(active_variant, dict)
            else None,
            "availability": active_variant.get("availability")
            if isinstance(active_variant, dict)
            else None,
            "category": product.get("product_type"),
            "tags": tags,
            "variants": flat_variants,
            "variant_count": len(flat_variants or []) or None,
            "product_attributes": single_value_attributes or None,
        }
        if isinstance(active_variant, dict):
            for field_name in ("color", "size", "barcode"):
                if active_variant.get(field_name):
                    record[field_name] = active_variant[field_name]
        if surface == "ecommerce_detail":
            record.update(
                {
                    "vendor": product.get("vendor"),
                    "product_type": product.get("product_type"),
                    "product_id": str(product.get("id"))
                    if product.get("id") not in (None, "", [], {})
                    else None,
                    "handle": product.get("handle"),
                    "created_at": product.get("created_at"),
                    "updated_at": product.get("updated_at"),
                    "published_at": product.get("published_at"),
                    "image_count": len(images) or None,
                }
            )
        return record

    def _merge_product_records(self, primary: dict, fallback: dict) -> dict:
        merged = dict(primary)
        for key, value in fallback.items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
                continue
            if isinstance(merged.get(key), dict) and isinstance(value, dict) and value:
                nested = dict(value)
                nested.update(
                    {
                        nested_key: nested_value
                        for nested_key, nested_value in merged[key].items()
                        if nested_value not in (None, "", [], {})
                    }
                )
                merged[key] = nested
        return merged

    def _variant_axes(self, variants: list[dict]) -> dict[str, list[str]]:
        axes: dict[str, list[str]] = {}
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            option_values = variant.get("option_values")
            if not isinstance(option_values, dict):
                continue
            for axis_name, value in option_values.items():
                cleaned = str(value or "").strip()
                if not cleaned:
                    continue
                axes.setdefault(str(axis_name), [])
                if cleaned not in axes[str(axis_name)]:
                    axes[str(axis_name)].append(cleaned)
        return axes

    def _localized_product_path(self, page_path: str, handle: object) -> str:
        product_handle = str(handle or "").strip().strip("/")
        if not product_handle:
            return str(page_path or "") or "/"
        raw_path = str(page_path or "").strip()
        marker = "/products/"
        marker_index = raw_path.find(marker)
        prefix = raw_path[:marker_index] if marker_index >= 0 else ""
        if marker_index < 0:
            locale_match = re.match(
                r"^/([a-z]{2}(?:-[a-z]{2})?)(?:/|$)", raw_path, re.I
            )
            if locale_match is not None:
                prefix = f"/{locale_match.group(1)}"
        return f"{prefix}/products/{product_handle}"

    def _dedupe_variants(self, variants: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen: dict[str, int] = {}
        for variant in variants:
            fingerprint = self._variant_fingerprint(variant)
            if fingerprint is None:
                deduped.append(dict(variant))
                continue
            existing_index = seen.get(fingerprint)
            if existing_index is None:
                seen[fingerprint] = len(deduped)
                deduped.append(dict(variant))
                continue
            current = deduped[existing_index]
            if len(variant.keys()) > len(current.keys()):
                merged = dict(variant)
                for key, value in current.items():
                    if merged.get(key) in (None, "", [], {}) and value not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        merged[key] = value
                deduped[existing_index] = merged
                continue
            for key, value in variant.items():
                if current.get(key) in (None, "", [], {}) and value not in (
                    None,
                    "",
                    [],
                    {},
                ):
                    current[key] = value
        return deduped

    def _variant_fingerprint(self, variant: dict) -> str | None:
        variant_id = str(variant.get("variant_id") or "").strip()
        if variant_id:
            return f"id:{variant_id}"
        sku = str(variant.get("sku") or "").strip()
        option_values = variant.get("option_values")
        if sku and isinstance(option_values, dict) and option_values:
            return json.dumps(
                {"sku": sku, "option_values": option_values}, sort_keys=True
            )
        if sku:
            return f"sku:{sku}"
        if isinstance(option_values, dict) and option_values:
            return json.dumps({"option_values": option_values}, sort_keys=True)
        return None

    def _split_selectable_axes(
        self, axes: dict[str, list[str]]
    ) -> tuple[dict[str, list[str]], dict[str, str]]:
        return split_variant_axes(
            axes,
            always_selectable_axes=frozenset({"size"}),
        )

    def _select_shopify_variant(
        self,
        variants: list[dict],
        *,
        base_url: str,
    ) -> dict | None:
        if not variants:
            return None
        parsed = urlsplit(str(base_url or "").strip())
        variant_id = next(
            (
                str(value).strip()
                for key, value in parse_qsl(parsed.query, keep_blank_values=False)
                if key == "variant" and str(value).strip()
            ),
            "",
        )
        if variant_id:
            matched_variant = next(
                (
                    row
                    for row in variants
                    if str(row.get("variant_id") or "").strip() == variant_id
                ),
                None,
            )
            if matched_variant is not None:
                return matched_variant
        return (
            next((row for row in variants if row.get("available") is True), None)
            or variants[0]
        )

    def _normalize_axis(self, value: object) -> str:
        normalized = normalized_variant_axis_key(value)
        if normalized:
            return normalized
        text = str(value or "").strip().lower().replace("&", " ")
        text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
        return text or "option"
