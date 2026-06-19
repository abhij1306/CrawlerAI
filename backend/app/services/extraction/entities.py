from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from app.services.extraction.contracts import CaptureBundle, Evidence, FrozenModel
from app.services.extraction.ids import stable_id


class ProductEntity(FrozenModel):
    entity_id: str
    identity_evidence_ids: tuple[str, ...]
    attribute_evidence: dict[str, tuple[str, ...]]
    variant_ids: tuple[str, ...]
    offer_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]


class VariantEntity(FrozenModel):
    entity_id: str
    product_entity_id: str
    identity_key: str
    identity_evidence_ids: tuple[str, ...]
    option_values: dict[str, str]
    attribute_evidence: dict[str, tuple[str, ...]]
    offer_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    selected: bool


class OfferEntity(FrozenModel):
    entity_id: str
    product_entity_id: str
    variant_entity_id: str | None
    group_id: str
    request_context_id: str
    fact_evidence: dict[str, tuple[str, ...]]


class AssetEntity(FrozenModel):
    entity_id: str
    product_entity_id: str
    variant_entity_id: str | None
    url_evidence_ids: tuple[str, ...]


class EntitySet(FrozenModel):
    products: tuple[ProductEntity, ...] = ()
    variants: tuple[VariantEntity, ...] = ()
    offers: tuple[OfferEntity, ...] = ()
    assets: tuple[AssetEntity, ...] = ()
    product_option_metadata: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def build_entities(bundle: CaptureBundle, evidence: tuple[Evidence, ...]) -> EntitySet:
    product = _link_product(evidence)
    if product is None:
        return EntitySet()
    variants = _link_variants(evidence, product.entity_id)
    offers = _link_offers(bundle, evidence, product.entity_id, variants)
    assets = _link_assets(evidence, product.entity_id)
    product = product.model_copy(
        update={
            "variant_ids": tuple(v.entity_id for v in variants),
            "offer_ids": tuple(o.entity_id for o in offers if o.variant_entity_id is None),
            "asset_ids": tuple(a.entity_id for a in assets if a.variant_entity_id is None),
        }
    )
    variants = tuple(
        variant.model_copy(
            update={
                "offer_ids": tuple(o.entity_id for o in offers if o.variant_entity_id == variant.entity_id),
                "asset_ids": tuple(a.entity_id for a in assets if a.variant_entity_id == variant.entity_id),
            }
        )
        for variant in variants
    )
    return EntitySet(products=(product,), variants=variants, offers=offers, assets=assets)


def _link_product(evidence: tuple[Evidence, ...]) -> ProductEntity | None:
    product_evidence = [ev for ev in evidence if ev.fact_type.startswith("product.")]
    if not product_evidence:
        return None
    identity = [
        ev
        for ev in product_evidence
        if ev.fact_type in {"product.gtin", "product.mpn", "product.sku", "product.url"}
    ]
    identity_key = tuple(sorted((ev.fact_type, str(ev.value)) for ev in identity))
    attributes: dict[str, list[str]] = {}
    for ev in product_evidence:
        attributes.setdefault(ev.fact_type, []).append(ev.evidence_id)
    return ProductEntity(
        entity_id=stable_id("product", identity_key or "primary"),
        identity_evidence_ids=tuple(sorted(ev.evidence_id for ev in identity or product_evidence)),
        attribute_evidence={key: tuple(sorted(set(ids))) for key, ids in attributes.items()},
        variant_ids=(),
        offer_ids=(),
        asset_ids=(),
    )


def _link_variants(evidence: tuple[Evidence, ...], product_id: str) -> tuple[VariantEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type.startswith("variant."):
            key = _variant_key(ev)
            if key:
                groups[key].append(ev)
    variants: list[VariantEntity] = []
    for key, rows in sorted(groups.items()):
        attrs: dict[str, list[str]] = defaultdict(list)
        for ev in rows:
            attrs[ev.fact_type].append(ev.evidence_id)
        variants.append(
            VariantEntity(
                entity_id=stable_id("variant", product_id, key),
                product_entity_id=product_id,
                identity_key=key,
                identity_evidence_ids=tuple(
                    sorted(
                        ev.evidence_id
                        for ev in rows
                        if ev.fact_type in {"variant.id", "variant.sku", "variant.gtin", "variant.url"}
                    )
                )
                or tuple(sorted(ev.evidence_id for ev in rows)),
                option_values={
                    ev.fact_type.removeprefix("variant.option."): str(ev.value)
                    for ev in rows
                    if ev.fact_type.startswith("variant.option.")
                },
                attribute_evidence={name: tuple(sorted(set(ids))) for name, ids in attrs.items()},
                offer_ids=(),
                asset_ids=(),
                selected=any(ev.fact_type == "variant.selected" and bool(ev.value) for ev in rows),
            )
        )
    return tuple(variants)


def _variant_key(ev: Evidence) -> str:
    hint = ev.entity_hint
    if ev.group_id:
        return f"group:{ev.group_id}"
    if hint and hint.variant_id:
        return f"id:{hint.variant_id}"
    if ev.fact_type in {"variant.id", "variant.sku", "variant.gtin", "variant.url"}:
        return f"{ev.fact_type}:{ev.value}"
    if hint and hint.sku:
        return f"sku:{hint.sku}"
    return ""


def _link_offers(
    bundle: CaptureBundle,
    evidence: tuple[Evidence, ...],
    product_id: str,
    variants: tuple[VariantEntity, ...],
) -> tuple[OfferEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type.startswith("offer."):
            groups[ev.group_id or f"ungrouped:{ev.evidence_id}"].append(ev)
    offers: list[OfferEntity] = []
    for group_id, rows in sorted(groups.items()):
        attrs: dict[str, list[str]] = defaultdict(list)
        for ev in rows:
            attrs[ev.fact_type].append(ev.evidence_id)
        variant_id = _variant_for(rows, variants)
        offers.append(
            OfferEntity(
                entity_id=stable_id("offer", product_id, variant_id, group_id),
                product_entity_id=product_id,
                variant_entity_id=variant_id,
                group_id=group_id,
                request_context_id=bundle.request_context.context_id,
                fact_evidence={name: tuple(sorted(set(ids))) for name, ids in attrs.items()},
            )
        )
    return tuple(offers)


def _variant_for(rows: list[Evidence], variants: tuple[VariantEntity, ...]) -> str | None:
    skus = {str(ev.entity_hint.sku) for ev in rows if ev.entity_hint and ev.entity_hint.sku}
    for variant in variants:
        if any(str(item).split(":", 1)[-1] in skus for item in (variant.identity_key,)):
            return variant.entity_id
    return None


def _link_assets(evidence: tuple[Evidence, ...], product_id: str) -> tuple[AssetEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type == "asset.image_url":
            groups[str(ev.value)].append(ev)
    return tuple(
        AssetEntity(
            entity_id=stable_id("asset", product_id, url),
            product_entity_id=product_id,
            variant_entity_id=None,
            url_evidence_ids=tuple(sorted(ev.evidence_id for ev in rows)),
        )
        for url, rows in sorted(groups.items())
    )
