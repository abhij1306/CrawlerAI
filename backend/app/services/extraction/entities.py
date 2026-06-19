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
    products = _link_products(evidence)
    if not products:
        return EntitySet()
    product_by_subject = _product_by_subject(products, evidence)
    variants = _link_variants(evidence, product_by_subject)
    offers = _link_offers(bundle, evidence, product_by_subject, variants)
    assets = _link_assets(evidence, product_by_subject, variants)
    products = tuple(
        product.model_copy(
            update={
                "variant_ids": tuple(v.entity_id for v in variants if v.product_entity_id == product.entity_id),
                "offer_ids": tuple(o.entity_id for o in offers if o.product_entity_id == product.entity_id and o.variant_entity_id is None),
                "asset_ids": tuple(a.entity_id for a in assets if a.product_entity_id == product.entity_id and a.variant_entity_id is None),
            }
        )
        for product in products
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
    return EntitySet(products=products, variants=variants, offers=offers, assets=assets)


def _link_products(evidence: tuple[Evidence, ...]) -> tuple[ProductEntity, ...]:
    by_subject: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if not ev.fact_type.startswith("product."):
            continue
        by_subject[ev.subject_id].append(ev)
    groups: list[list[Evidence]] = []
    group_identities: list[set[tuple[str, str]]] = []
    for subject, rows in sorted(by_subject.items()):
        identities = _product_identities(rows)
        matched = next(
            (
                index
                for index, existing in enumerate(group_identities)
                if identities and existing & identities
            ),
            None,
        )
        if matched is None:
            groups.append(list(rows))
            group_identities.append(set(identities) or {("subject", subject)})
            continue
        groups[matched].extend(rows)
        group_identities[matched].update(identities)
    _merge_url_only_groups(groups, group_identities)
    products: list[ProductEntity] = []
    for identities, rows in sorted(zip(group_identities, groups), key=lambda item: str(sorted(item[0]))):
        attributes: dict[str, list[str]] = {}
        identity_rows = [
            ev
            for ev in rows
            if ev.fact_type in {"product.gtin", "product.mpn", "product.sku", "product.url"}
        ]
        for ev in rows:
            attributes.setdefault(ev.fact_type, []).append(ev.evidence_id)
        products.append(
            ProductEntity(
                entity_id=stable_id("product", sorted(identities)),
                identity_evidence_ids=tuple(sorted(ev.evidence_id for ev in identity_rows or rows)),
                attribute_evidence={name: tuple(sorted(set(ids))) for name, ids in attributes.items()},
                variant_ids=(),
                offer_ids=(),
                asset_ids=(),
            )
        )
    return tuple(products)


def _merge_url_only_groups(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
) -> None:
    if len(groups) < 2:
        return
    target = max(
        range(len(groups)),
        key=lambda index: sum(row.collector_id != "url" for row in groups[index]),
    )
    for index in reversed(range(len(groups))):
        if index == target or any(row.collector_id != "url" for row in groups[index]):
            continue
        groups[target].extend(groups.pop(index))
        group_identities[target].update(group_identities.pop(index))


def _product_identities(rows: list[Evidence]) -> set[tuple[str, str]]:
    return {
        (row.fact_type, str(row.value))
        for row in rows
        if row.fact_type in {"product.gtin", "product.mpn", "product.sku", "product.url"}
    }


def _product_by_subject(
    products: tuple[ProductEntity, ...],
    evidence: tuple[Evidence, ...],
) -> dict[str, str]:
    by_evidence = {
        evidence_id: product.entity_id
        for product in products
        for evidence_id in product.attribute_evidence.get("product.title", ())
        + product.attribute_evidence.get("product.url", ())
        + product.identity_evidence_ids
    }
    return {
        ev.subject_id: by_evidence[ev.evidence_id]
        for ev in evidence
        if ev.evidence_id in by_evidence
    }


def _link_variants(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
) -> tuple[VariantEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type.startswith("variant."):
            key = _variant_key(ev)
            if key:
                groups[key].append(ev)
    variants: list[VariantEntity] = []
    for key, rows in sorted(groups.items()):
        product_id = _owner_product_id(rows, product_by_subject)
        if product_id is None:
            continue
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
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
) -> tuple[OfferEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type.startswith("offer."):
            groups[ev.group_id or f"ungrouped:{ev.evidence_id}"].append(ev)
    offers: list[OfferEntity] = []
    for group_id, rows in sorted(groups.items()):
        product_id = _owner_product_id(rows, product_by_subject)
        if product_id is None:
            continue
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


def _link_assets(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
) -> tuple[AssetEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type == "asset.image_url":
            groups[str(ev.value)].append(ev)
    assets: list[AssetEntity] = []
    for url, rows in sorted(groups.items()):
        product_id = _owner_product_id(rows, product_by_subject)
        if product_id is None:
            continue
        assets.append(
            AssetEntity(
                entity_id=stable_id("asset", product_id, url),
                product_entity_id=product_id,
                variant_entity_id=_variant_for(rows, variants),
                url_evidence_ids=tuple(sorted(ev.evidence_id for ev in rows)),
            )
        )
    return tuple(assets)


def _owner_product_id(
    rows: list[Evidence],
    product_by_subject: dict[str, str],
) -> str | None:
    for ev in rows:
        if ev.parent_subject_id and ev.parent_subject_id in product_by_subject:
            return product_by_subject[ev.parent_subject_id]
    if len(set(product_by_subject.values())) == 1:
        return next(iter(product_by_subject.values()))
    return None
