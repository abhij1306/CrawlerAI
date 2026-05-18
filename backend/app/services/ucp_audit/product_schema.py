from __future__ import annotations

from bs4 import BeautifulSoup

from app.services.config import ucp_audit as config
from app.services.structured_sources import parse_json_ld
from app.services.ucp_audit.types import UCPSchemaScore


def score_product_schema(url: str, html: str) -> UCPSchemaScore:
    products = [
        item
        for item in parse_json_ld(BeautifulSoup(str(html or ""), "html.parser"))
        if _is_product(item)
    ]
    if not products:
        return UCPSchemaScore(
            url=url,
            product_jsonld_found=False,
            required_fields_present=[],
            recommended_fields_present=[],
            ucp_fields_present=[],
            completeness_score=0,
            missing_required=_path_labels(config.JSON_LD_REQUIRED_FIELD_PATHS),
            missing_recommended=_path_labels(config.JSON_LD_RECOMMENDED_FIELD_PATHS),
            raw_additional_properties=[],
            raw_product_type=None,
            raw_offers=[],
        )
    product = _richest_product(products)
    required_present = _present_path_labels(
        product, config.JSON_LD_REQUIRED_FIELD_PATHS
    )
    recommended_present = _present_path_labels(
        product, config.JSON_LD_RECOMMENDED_FIELD_PATHS
    )
    ucp_present = (
        [config.JSON_LD_ADDITIONAL_PROPERTY_FIELD]
        if _list_of_dicts(product.get(config.JSON_LD_ADDITIONAL_PROPERTY_FIELD))
        else []
    )
    required_labels = _path_labels(config.JSON_LD_REQUIRED_FIELD_PATHS)
    recommended_labels = _path_labels(config.JSON_LD_RECOMMENDED_FIELD_PATHS)
    total = len(required_labels) + len(recommended_labels) + 1
    found = len(required_present) + len(recommended_present) + len(ucp_present)
    return UCPSchemaScore(
        url=url,
        product_jsonld_found=True,
        required_fields_present=required_present,
        recommended_fields_present=recommended_present,
        ucp_fields_present=ucp_present,
        completeness_score=int((found / total) * 100) if total else 0,
        missing_required=[item for item in required_labels if item not in required_present],
        missing_recommended=[
            item for item in recommended_labels if item not in recommended_present
        ],
        raw_additional_properties=_list_of_dicts(
            product.get(config.JSON_LD_ADDITIONAL_PROPERTY_FIELD)
        ),
        raw_product_type=_first_text(product, config.JSON_LD_CATEGORY_FIELDS),
        raw_offers=_product_offer_rows(product),
    )


def _is_product(item: dict) -> bool:
    raw = item.get(config.JSON_LD_TYPE_KEY)
    values = raw if isinstance(raw, list) else [raw]
    return any(str(value or "").strip() in config.JSON_LD_PRODUCT_TYPES for value in values)


def _richest_product(products: list[dict]) -> dict:
    return max(products, key=lambda item: len(_nonempty_keys(item)))


def _nonempty_keys(item: dict) -> list[str]:
    return [str(key) for key, value in item.items() if value not in (None, "", [], {})]


def _present_path_labels(item: dict, paths: tuple[tuple[str, ...], ...]) -> list[str]:
    return [_path_label(path) for path in paths if _path_has_value(item, path)]


def _path_has_value(value: object, path: tuple[str, ...]) -> bool:
    if value in (None, "", [], {}):
        return False
    if not path:
        return value not in (None, "", [], {})
    key, *tail = path
    if isinstance(value, list):
        return any(_path_has_value(item, path) for item in value)
    if not isinstance(value, dict):
        return False
    if key == config.JSON_LD_OFFERS_FIELD and key not in value:
        variants = value.get("hasVariant")
        if isinstance(variants, dict):
            variants = [variants]
        if isinstance(variants, list):
            return any(_path_has_value(item, path) for item in variants)
    return _path_has_value(value.get(key), tuple(tail))


def _path_labels(paths: tuple[tuple[str, ...], ...]) -> list[str]:
    return [_path_label(path) for path in paths]


def _path_label(path: tuple[str, ...]) -> str:
    return ".".join(path)


def _list_of_dicts(value: object) -> list[dict]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def _offer_rows(value: object) -> list[dict]:
    return _list_of_dicts(value)


def _product_offer_rows(product: dict) -> list[dict]:
    rows = _offer_rows(product.get(config.JSON_LD_OFFERS_FIELD))
    variants = product.get("hasVariant")
    if isinstance(variants, dict):
        variants = [variants]
    if isinstance(variants, list):
        for variant in variants:
            if isinstance(variant, dict):
                for offer in _offer_rows(variant.get(config.JSON_LD_OFFERS_FIELD)):
                    rows.append(
                        {
                            **{
                                key: variant.get(key)
                                for key in ("sku", "gtin", "gtin13", "image", "name")
                                if variant.get(key) not in (None, "", [], {})
                            },
                            **offer,
                        }
                    )
    return rows


def _first_text(item: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return str(value).strip()
    return None
