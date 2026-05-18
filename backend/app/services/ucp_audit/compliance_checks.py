from __future__ import annotations

import re

from app.services.config import ucp_audit as config
from app.services.ucp_audit.types import (
    PolicyReadabilityReport,
    UCPFinding,
    VariantFidelityReport,
)


# D-UCP5 reads from existing crawl record variant data.
# If fidelity scores are systematically low, the fix is upstream
# in the commerce extractor, not in this audit module. (Rule 4)
def build_variant_fidelity_report(records) -> VariantFidelityReport:
    """Build D-UCP5 fidelity from already-extracted variant rows."""
    return _variant_report(list(records))


def _variants(row) -> list:
    """Return public variant rows for a product record."""
    return list(row.get(config.PUBLIC_VARIANTS_FIELD) or [])


def _products(rows: list[dict]) -> list[dict]:
    """Keep products with enough variant rows for fidelity checks."""
    return [row for row in rows if len(_variants(row)) > 1]


def _variant_value(row, key: str):
    """Read a variant value only from dict rows."""
    return row.get(key) if isinstance(row, dict) else None


def _price_key(row) -> tuple[object, object]:
    """Return the price/currency identity used for collapse detection."""
    return (
        _variant_value(row, config.PUBLIC_VARIANT_PRICE_FIELD),
        _variant_value(row, config.PUBLIC_VARIANT_CURRENCY_FIELD),
    )


def _missing(row, key: str) -> bool:
    """Return true when a public variant field is empty."""
    return _variant_value(row, key) in (None, "", [], {})


def _collapsed(rows: list[dict]) -> int:
    """Count products whose variant rows share one price/currency pair."""
    return sum(1 for row in rows if len({_price_key(item) for item in _variants(row)}) == 1)


def _missing_count(rows: list[dict], key: str) -> int:
    """Count missing variant field values across sampled products."""
    return sum(1 for row in rows for item in _variants(row) if _missing(item, key))


def _finding(code: str, count: int) -> UCPFinding:
    """Build a D-UCP5 warning finding."""
    return UCPFinding(
        code=code,
        dimension_id=config.D_UCP5_ID,
        severity=config.UCP_FINDING_WARNING,
        affected_count=count,
    )


def _variant_findings(collapsed: int, sku: int, availability: int) -> list[UCPFinding]:
    """Build variant findings for non-zero issue counts."""
    findings = [
        _finding(config.FINDING_VARIANT_OFFERS_COLLAPSED, collapsed) if collapsed else None,
        _finding(config.FINDING_VARIANT_SKU_MISSING, sku) if sku else None,
        _finding(config.FINDING_VARIANT_AVAILABILITY_MISSING, availability)
        if availability
        else None,
    ]
    return [item for item in findings if item is not None]


def _variant_score(total: int, collapsed: int, sku: int, availability: int) -> int:
    """Score variant fidelity from issue density."""
    if total <= 0:
        return 100
    metrics = (collapsed, sku, availability)
    metric_count = sum(1 for metric in metrics if metric > 0)
    if metric_count <= 0:
        return 100
    return max(0, int(100 - ((sum(metrics) / (total * metric_count)) * 100)))


def _variant_report(rows: list[dict]) -> VariantFidelityReport:
    """Build a fidelity report from raw product rows."""
    return _variant_report_from_products(_products(rows))


def _variant_report_from_products(products: list[dict]) -> VariantFidelityReport:
    """Build a fidelity report from products with variant evidence."""
    collapsed = _collapsed(products)
    sku = _missing_count(products, config.PUBLIC_VARIANT_SKU_FIELD)
    availability = _missing_count(products, config.PUBLIC_VARIANT_AVAILABILITY_FIELD)
    return VariantFidelityReport(
        products_with_variants_sampled=len(products),
        collapsed_offers_count=collapsed,
        missing_sku_count=sku,
        missing_availability_count=availability,
        fidelity_score=_variant_score(len(products), collapsed, sku, availability),
        findings=_variant_findings(collapsed, sku, availability),
    )


def build_policy_readability_report(
    *,
    structured_shipping_found,
    period_machine_readable=False,
    currency_value="",
    policy_page_http_accessible=False,
) -> PolicyReadabilityReport:
    """Build D-UCP6 readability signals and missing-signal findings."""
    has_shipping = bool(structured_shipping_found)
    has_period = bool(period_machine_readable)
    currency_valid = bool(re.fullmatch(config.ISO4217_PATTERN, str(currency_value or "")))
    page_accessible = bool(policy_page_http_accessible)
    findings = [
        UCPFinding(
            config.FINDING_POLICY_SHIPPING_MISSING,
            config.D_UCP6_ID,
            config.UCP_FINDING_WARNING,
            count_kind="domain_check",
        )
        if not has_shipping
        else None,
        UCPFinding(
            config.FINDING_POLICY_RETURN_PERIOD_MISSING,
            config.D_UCP6_ID,
            config.UCP_FINDING_WARNING,
            count_kind="domain_check",
        )
        if not has_period
        else None,
        UCPFinding(
            config.FINDING_POLICY_CURRENCY_INVALID,
            config.D_UCP6_ID,
            config.UCP_FINDING_WARNING,
            count_kind="domain_check",
        )
        if not currency_valid
        else None,
        UCPFinding(
            config.FINDING_POLICY_PAGE_INACCESSIBLE,
            config.D_UCP6_ID,
            config.UCP_FINDING_WARNING,
            count_kind="domain_check",
        )
        if not page_accessible
        else None,
    ]
    return PolicyReadabilityReport(
        structured_shipping_found=has_shipping,
        return_period_machine_readable=has_period,
        currency_is_iso4217=currency_valid,
        policy_page_http_accessible=page_accessible,
        readability_score=config.POLICY_SCORE_PER_SIGNAL
        * sum((has_shipping, has_period, currency_valid, page_accessible)),
        findings=[item for item in findings if item is not None],
    )
