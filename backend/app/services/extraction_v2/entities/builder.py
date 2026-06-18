from __future__ import annotations

from app.services.extraction_v2.contracts import CaptureBundle, Evidence
from app.services.extraction_v2.entities.asset_linker import link_assets
from app.services.extraction_v2.entities.contracts import EntitySet, ProductEntity, VariantEntity
from app.services.extraction_v2.entities.offer_linker import link_offers
from app.services.extraction_v2.entities.product_linker import link_product
from app.services.extraction_v2.entities.variant_linker import link_variants


def build_entities(bundle: CaptureBundle, evidence: tuple[Evidence, ...]) -> EntitySet:
    product = link_product(evidence)
    if product is None:
        return EntitySet()
    variants = link_variants(evidence, product.entity_id)
    offers = link_offers(bundle, evidence, product.entity_id, variants)
    assets = link_assets(evidence, product.entity_id, variants)
    product = _attach_product(product, variants, offers, assets)
    variants = _attach_variants(variants, offers, assets)
    return EntitySet(products=(product,), variants=variants, offers=offers, assets=assets)


def _attach_product(product, variants, offers, assets) -> ProductEntity:
    return product.model_copy(update={"variant_ids": tuple(v.entity_id for v in variants), "offer_ids": tuple(o.entity_id for o in offers if o.variant_entity_id is None), "asset_ids": tuple(a.entity_id for a in assets if a.variant_entity_id is None)})


def _attach_variants(variants, offers, assets) -> tuple[VariantEntity, ...]:
    rows = []
    for variant in variants:
        rows.append(variant.model_copy(update={"offer_ids": tuple(o.entity_id for o in offers if o.variant_entity_id == variant.entity_id), "asset_ids": tuple(a.entity_id for a in assets if a.variant_entity_id == variant.entity_id)}))
    return tuple(rows)
