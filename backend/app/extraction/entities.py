from __future__ import annotations

from collections import defaultdict

from pydantic import Field
from app.core.records.url_identity import detail_url_resource_identity
from app.core.shared.url_utils import asset_url_identity
from app.extraction.contracts import (
    CaptureBundle,
    Evidence,
    FrozenModel,
    OptionAxis,
    OptionValue,
    ProductOptionCatalog,
)
from app.core.shared.ids import stable_id


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
    source_subject_ids: tuple[str, ...] = ()
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
    url: str
    identity_key: str
    url_evidence_ids: tuple[str, ...]


class EntitySet(FrozenModel):
    products: tuple[ProductEntity, ...] = ()
    variants: tuple[VariantEntity, ...] = ()
    offers: tuple[OfferEntity, ...] = ()
    assets: tuple[AssetEntity, ...] = ()
    product_option_metadata: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    option_catalogs: tuple[ProductOptionCatalog, ...] = ()


def build_entities(bundle: CaptureBundle, evidence: tuple[Evidence, ...]) -> EntitySet:
    products = _select_primary_product_roots(bundle, evidence, _link_products(evidence))
    if not products:
        return EntitySet()
    product_by_subject = _product_by_subject(products, evidence)
    option_catalogs = _option_catalogs(evidence, product_by_subject)
    variants = _link_variants(evidence, product_by_subject)
    offers = _link_offers(bundle, evidence, product_by_subject, variants)
    assets = _link_assets(evidence, product_by_subject, variants)
    products = tuple(
        product.model_copy(
            update={
                "variant_ids": tuple(
                    v.entity_id
                    for v in variants
                    if v.product_entity_id == product.entity_id
                ),
                "offer_ids": _product_child_ids(offers, product.entity_id),
                "asset_ids": _product_child_ids(assets, product.entity_id),
            }
        )
        for product in products
    )
    variants = tuple(
        variant.model_copy(
            update={
                "offer_ids": tuple(
                    o.entity_id
                    for o in offers
                    if o.variant_entity_id == variant.entity_id
                ),
                "asset_ids": tuple(
                    a.entity_id
                    for a in assets
                    if a.variant_entity_id == variant.entity_id
                ),
            }
        )
        for variant in variants
    )
    return EntitySet(
        products=products,
        variants=variants,
        offers=offers,
        assets=assets,
        option_catalogs=option_catalogs,
    )


def _select_primary_product_roots(
    bundle: CaptureBundle,
    evidence: tuple[Evidence, ...],
    products: tuple[ProductEntity, ...],
) -> tuple[ProductEntity, ...]:
    if len(products) <= 1:
        return products
    by_id = {item.evidence_id: item for item in evidence}
    target_identity = detail_url_resource_identity(
        bundle.final_url or bundle.requested_url
    )
    ranked: list[tuple[int, str, ProductEntity]] = []
    for product in products:
        rows = [
            by_id[evidence_id]
            for ids in product.attribute_evidence.values()
            for evidence_id in ids
            if evidence_id in by_id
        ]
        score = _primary_product_root_score(rows, target_identity=target_identity)
        ranked.append((score, product.entity_id, product))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] <= 0:
        return products
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return products
    return (ranked[0][2],)


def _primary_product_root_score(rows: list[Evidence], *, target_identity: str) -> int:
    score = 0
    for row in rows:
        if row.entity_hint is not None and row.entity_hint.selected is True:
            score += 100
        if row.fact_type == "product.url":
            identity = detail_url_resource_identity(str(row.value))
            if target_identity and identity == target_identity:
                score += 80
            elif identity:
                score -= 20
        if row.collector_id == "url" and row.fact_type == "product.url":
            score += 10
        if row.subject_scope == "product":
            score += 1
    return score


def _product_child_ids(children, product_id: str) -> tuple[str, ...]:
    return tuple(
        item.entity_id
        for item in children
        if item.product_entity_id == product_id and item.variant_entity_id is None
    )


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
                if identities
                and _product_identity_sets_match(existing, identities)
                and _product_identity_sets_compatible(existing, identities)
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
    _merge_exact_title_groups(groups, group_identities)
    products: list[ProductEntity] = []
    for identities, rows in sorted(
        zip(group_identities, groups), key=lambda item: str(sorted(item[0]))
    ):
        attributes: dict[str, list[str]] = {}
        identity_rows = [
            ev
            for ev in rows
            if ev.fact_type
            in {"product.gtin", "product.mpn", "product.sku", "product.url"}
        ]
        for ev in rows:
            attributes.setdefault(ev.fact_type, []).append(ev.evidence_id)
        products.append(
            ProductEntity(
                entity_id=stable_id("product", sorted(identities)),
                identity_evidence_ids=tuple(
                    sorted(ev.evidence_id for ev in identity_rows or rows)
                ),
                attribute_evidence={
                    name: tuple(sorted(set(ids))) for name, ids in attributes.items()
                },
                variant_ids=(),
                offer_ids=(),
                asset_ids=(),
            )
        )
    return tuple(products)


def _merge_exact_title_groups(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
) -> None:
    identified = [
        index
        for index, identities in enumerate(group_identities)
        if any(kind != "subject" for kind, _value in identities)
    ]
    for index in reversed(range(len(groups))):
        titles = _normalized_product_titles(groups[index])
        if not titles:
            continue
        matches = [
            target
            for target in identified
            if target != index
            and target < len(groups)
            and _product_identity_sets_compatible(
                group_identities[target], group_identities[index]
            )
            and titles & _normalized_product_titles(groups[target])
        ]
        if len(matches) != 1:
            continue
        target = matches[0]
        groups[target].extend(groups.pop(index))
        group_identities[target].update(group_identities.pop(index))
        identified = [
            item - 1 if item > index else item for item in identified if item != index
        ]


def _normalized_product_titles(rows: list[Evidence]) -> set[str]:
    return {
        " ".join(str(row.value).casefold().split())
        for row in rows
        if row.fact_type == "product.title"
        and str(row.value).strip()
        and set(row.flags) <= {"title_url_match", "url_derived_title"}
    }


def _merge_url_only_groups(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
) -> None:
    if len(groups) < 2:
        return
    for index in reversed(range(len(groups))):
        if any(row.collector_id != "url" for row in groups[index]):
            continue
        matches = [
            target
            for target in range(len(groups))
            if target != index
            and any(row.collector_id != "url" for row in groups[target])
            and _product_identity_sets_match(
                group_identities[target], group_identities[index]
            )
            and _product_identity_sets_compatible(
                group_identities[target], group_identities[index]
            )
        ]
        if len(matches) != 1:
            continue
        target = matches[0]
        groups[target].extend(groups.pop(index))
        group_identities[target].update(group_identities.pop(index))


def _product_identities(rows: list[Evidence]) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    for row in rows:
        if row.fact_type in {"product.gtin", "product.mpn", "product.sku"}:
            value = " ".join(str(row.value).casefold().split())
            if value:
                identities.add((row.fact_type, value))
        if row.fact_type == "product.url":
            resource_identity = detail_url_resource_identity(str(row.value))
            if resource_identity:
                identities.add(("product.url_resource", resource_identity))
    return identities


def _product_identity_sets_match(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    return bool(left & right)


def _product_identity_sets_compatible(
    left: set[tuple[str, str]], right: set[tuple[str, str]]
) -> bool:
    for kind in {identity_kind for identity_kind, _value in left | right}:
        left_values = {value for identity_kind, value in left if identity_kind == kind}
        right_values = {
            value for identity_kind, value in right if identity_kind == kind
        }
        if left_values and right_values and left_values.isdisjoint(right_values):
            return False
    return True


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
    subjects: dict[str, str] = {}
    for ev in evidence:
        product_id = by_evidence.get(ev.evidence_id)
        if product_id is None:
            continue
        subjects[ev.subject_id] = product_id
        for subject_id in _source_subject_aliases(ev):
            subjects.setdefault(subject_id, product_id)
    return subjects


def _source_subject_aliases(ev: Evidence) -> tuple[str, ...]:
    if ev.source_subject_ids:
        return ev.source_subject_ids
    return _metadata_subject_aliases(ev, "source_subject_ids")


def _parent_subject_aliases(ev: Evidence) -> tuple[str, ...]:
    aliases = list(
        ev.parent_source_subject_ids
        or _metadata_subject_aliases(ev, "parent_source_subject_ids")
    )
    if ev.parent_subject_id:
        aliases.append(ev.parent_subject_id)
    return tuple(dict.fromkeys(alias for alias in aliases if alias))


def _metadata_subject_aliases(ev: Evidence, key: str) -> tuple[str, ...]:
    aliases = ev.metadata.get(key)
    if not isinstance(aliases, (list, tuple)):
        return ()
    return tuple(text for alias in aliases if (text := str(alias or "").strip()))


def _link_variants(
    evidence: tuple[Evidence, ...], product_by_subject: dict[str, str]
) -> tuple[VariantEntity, ...]:
    return tuple(
        _variant_entity(product_id, keys, rows, source_subjects)
        for product_id, keys, rows, source_subjects in _merge_single_color_size_groups(
            _variant_groups(evidence, product_by_subject)
        )
    )


def _merge_single_color_size_groups(
    groups: list[tuple[str, set[str], list[Evidence], set[str]]],
) -> list[tuple[str, set[str], list[Evidence], set[str]]]:
    by_product_size: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, (product_id, _keys, rows, _subjects) in enumerate(groups):
        options = _variant_options_from_rows(rows)
        if options.get("size"):
            by_product_size[(product_id, options["size"])].append(index)
    removed: set[int] = set()
    for indices in by_product_size.values():
        size_only = [
            index
            for index in indices
            if set(_variant_options_from_rows(groups[index][2])) == {"size"}
        ]
        color_size = [
            index
            for index in indices
            if {"color", "size"} <= set(_variant_options_from_rows(groups[index][2]))
        ]
        if len(size_only) != 1 or len(color_size) != 1:
            continue
        target, source = color_size[0], size_only[0]
        groups[target][1].update(groups[source][1])
        groups[target][2].extend(groups[source][2])
        groups[target][3].update(groups[source][3])
        removed.add(source)
    return [group for index, group in enumerate(groups) if index not in removed]


def _variant_options_from_rows(rows: list[Evidence]) -> dict[str, str]:
    return {
        row.fact_type.removeprefix("variant.option."): str(row.value).strip()
        for row in rows
        if row.fact_type.startswith("variant.option.") and str(row.value).strip()
    }


def _variant_groups(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
) -> list[tuple[str, set[str], list[Evidence], set[str]]]:
    provisional: dict[str, list[Evidence]] = defaultdict(list)
    commercially_owned_subjects = {
        ev.parent_subject_id
        for ev in evidence
        if ev.fact_type.startswith("offer.") and ev.parent_subject_id
    }
    for ev in evidence:
        if ev.fact_type.startswith("variant."):
            provisional[ev.subject_id].append(ev)
    groups: list[list[Evidence]] = []
    group_keys: list[set[str]] = []
    subjects: list[set[str]] = []
    product_ids: list[str] = []
    for subject_id, rows in provisional.items():
        product_id = _owner_product_id(
            rows,
            product_by_subject,
            allowed_relations=None,
        )
        keys = _variant_identity_keys(rows)
        has_sellable_identity = any(
            row.fact_type in {"variant.sku", "variant.gtin", "variant.url"}
            and str(row.value).strip()
            for row in rows
        )
        has_commercial_evidence = subject_id in commercially_owned_subjects
        if (
            not product_id
            or not keys
            or not (has_sellable_identity or has_commercial_evidence)
        ):
            continue
        matched = next(
            (
                index
                for index, existing in enumerate(group_keys)
                if product_ids[index] == product_id and existing & keys
            ),
            None,
        )
        if matched is None:
            groups.append(list(rows))
            group_keys.append(set(keys))
            subjects.append(
                {
                    subject_id,
                    *(
                        _alias
                        for row in rows
                        for _alias in _source_subject_aliases(row)
                    ),
                }
            )
            product_ids.append(product_id)
        else:
            groups[matched].extend(rows)
            group_keys[matched].update(keys)
            subjects[matched].update(
                {
                    subject_id,
                    *(
                        _alias
                        for row in rows
                        for _alias in _source_subject_aliases(row)
                    ),
                }
            )
    return sorted(
        zip(product_ids, group_keys, groups, subjects),
        key=lambda item: (item[0], sorted(item[1])),
    )


def _variant_entity(
    product_id: str,
    keys: set[str],
    rows: list[Evidence],
    source_subjects: set[str],
) -> VariantEntity:
    attrs: dict[str, list[str]] = defaultdict(list)
    for ev in rows:
        attrs[ev.fact_type].append(ev.evidence_id)
    identity_facts = {"variant.id", "variant.sku", "variant.gtin", "variant.url"}
    identity_ids = tuple(
        sorted(ev.evidence_id for ev in rows if ev.fact_type in identity_facts)
    )
    return VariantEntity(
        entity_id=stable_id("variant", product_id, _preferred_variant_key(keys)),
        product_entity_id=product_id,
        identity_key=_preferred_variant_key(keys),
        source_subject_ids=tuple(sorted(source_subjects)),
        identity_evidence_ids=identity_ids
        or tuple(sorted(ev.evidence_id for ev in rows)),
        option_values={
            ev.fact_type.removeprefix("variant.option."): str(ev.value)
            for ev in rows
            if ev.fact_type.startswith("variant.option.")
        },
        attribute_evidence={
            name: tuple(sorted(set(ids))) for name, ids in attrs.items()
        },
        offer_ids=(),
        asset_ids=(),
        selected=any(
            ev.fact_type == "variant.selected" and bool(ev.value) for ev in rows
        ),
    )


def _variant_identity_keys(rows: list[Evidence]) -> set[str]:
    keys: set[str] = set()
    for prefix, fact_type in (
        ("id", "variant.id"),
        ("sku", "variant.sku"),
        ("gtin", "variant.gtin"),
        ("url", "variant.url"),
    ):
        keys.update(
            f"{prefix}:{str(ev.value).strip()}"
            for ev in rows
            if ev.fact_type == fact_type and str(ev.value).strip()
        )
    for prefix, attr in (("id", "variant_id"), ("sku", "sku"), ("url", "url")):
        keys.update(
            f"{prefix}:{str(getattr(ev.entity_hint, attr) or '').strip()}"
            for ev in rows
            if ev.entity_hint and str(getattr(ev.entity_hint, attr) or "").strip()
        )
    options = {
        ev.fact_type.removeprefix("variant.option."): str(ev.value).strip()
        for ev in rows
        if ev.fact_type.startswith("variant.option.") and str(ev.value).strip()
    }
    selected = any(ev.fact_type == "variant.selected" and bool(ev.value) for ev in rows)
    if selected and options:
        keys.add(
            "options:" + "|".join(f"{key}={options[key]}" for key in sorted(options))
        )
    if len(options) >= 2:
        keys.add(
            "options:" + "|".join(f"{key}={options[key]}" for key in sorted(options))
        )
    if len(options) == 1 and _rows_from_structured_variant_object(rows):
        keys.add(
            "options:" + "|".join(f"{key}={options[key]}" for key in sorted(options))
        )
    return keys


def _rows_from_structured_variant_object(rows: list[Evidence]) -> bool:
    return any(
        row.collector_id in {"jsonld", "js_state", "network", "adapter"}
        and row.fact_type.startswith("variant.option.")
        for row in rows
    )


def _preferred_variant_key(keys: set[str]) -> str:
    for prefix in ("id:", "sku:", "gtin:", "url:", "options:"):
        match = sorted(key for key in keys if key.startswith(prefix))
        if match:
            return match[0]
    return sorted(keys)[0]


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
        relations = {row.relation_type for row in rows if row.relation_type}
        if len(relations) > 1:
            continue
        relation = next(iter(relations), None)
        row_variant_ids = {_variant_for([row], variants) for row in rows}
        if None in row_variant_ids and len(row_variant_ids) > 1:
            continue
        variant_id = (
            _variant_for(rows, variants)
            if relation in {None, "variant_offer"}
            else None
        )
        product_id = _product_for_child(rows, product_by_subject, variants, variant_id)
        if relation == "variant_offer" and variant_id is None:
            continue
        if relation == "product_offer" and variant_id is not None:
            continue
        if product_id is None:
            continue
        attrs: dict[str, list[str]] = defaultdict(list)
        for ev in rows:
            attrs[ev.fact_type].append(ev.evidence_id)
        offers.append(
            OfferEntity(
                entity_id=stable_id("offer", product_id, variant_id, group_id),
                product_entity_id=product_id,
                variant_entity_id=variant_id,
                group_id=group_id,
                request_context_id=bundle.request_context.context_id,
                fact_evidence={
                    name: tuple(sorted(set(ids))) for name, ids in attrs.items()
                },
            )
        )
    return tuple(offers)


def _variant_for(
    rows: list[Evidence], variants: tuple[VariantEntity, ...]
) -> str | None:
    source_subjects = {
        subject_id for ev in rows for subject_id in _parent_subject_aliases(ev)
    }
    for variant in variants:
        if source_subjects & set(variant.source_subject_ids):
            return variant.entity_id
    skus = {
        str(ev.entity_hint.sku) for ev in rows if ev.entity_hint and ev.entity_hint.sku
    }
    for variant in variants:
        if any(str(item).split(":", 1)[-1] in skus for item in (variant.identity_key,)):
            return variant.entity_id
    return None


def _product_for_child(
    rows: list[Evidence],
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
    variant_id: str | None,
) -> str | None:
    if variant_id:
        return next(
            (
                variant.product_entity_id
                for variant in variants
                if variant.entity_id == variant_id
            ),
            None,
        )
    return _owner_product_id(rows, product_by_subject)


def _link_assets(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
) -> tuple[AssetEntity, ...]:
    groups: dict[str, list[tuple[Evidence, str]]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type == "asset.image_url":
            normalized = asset_url_identity(ev.value)
            if normalized is not None:
                url, identity_key = normalized
                groups[identity_key].append((ev, url))
    assets: list[AssetEntity] = []
    for identity_key, asset_rows in sorted(groups.items()):
        rows = [ev for ev, _url in asset_rows]
        variant_id = (
            None
            if any(row.relation_type == "product_asset" for row in rows)
            else _variant_for(rows, variants)
        )
        product_id = _product_for_child(rows, product_by_subject, variants, variant_id)
        if product_id is None:
            continue
        assets.append(
            AssetEntity(
                entity_id=stable_id("asset", product_id, identity_key),
                product_entity_id=product_id,
                variant_entity_id=variant_id,
                url=asset_rows[0][1],
                identity_key=identity_key,
                url_evidence_ids=tuple(sorted(ev.evidence_id for ev in rows)),
            )
        )
    return tuple(assets)


def _owner_product_id(
    rows: list[Evidence],
    product_by_subject: dict[str, str],
    *,
    allowed_relations: frozenset[str] | None = None,
) -> str | None:
    product_ids: set[str] = set()
    for ev in rows:
        subject_ids = _parent_subject_aliases(ev)
        if allowed_relations is not None:
            relation = ev.relation_type
            if relation is None and ev.subject_scope != "unknown":
                continue
            if relation is not None and relation not in allowed_relations:
                continue
        for subject_id in subject_ids:
            product_id = product_by_subject.get(subject_id)
            if product_id is not None:
                product_ids.add(product_id)
    if len(product_ids) != 1:
        return None
    return next(iter(product_ids))


def _option_catalogs(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
) -> tuple[ProductOptionCatalog, ...]:
    by_product: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for ev in evidence:
        if not ev.fact_type.startswith("option."):
            continue
        product_id = product_by_subject.get(ev.subject_id)
        if not product_id:
            continue
        axis = ev.fact_type.removeprefix("option.")
        by_product[product_id][axis][str(ev.value)].append(ev.evidence_id)
    catalogs: list[ProductOptionCatalog] = []
    for product_id, axes in sorted(by_product.items()):
        catalogs.append(
            ProductOptionCatalog(
                product_entity_id=product_id,
                axes=tuple(
                    OptionAxis(
                        axis=axis,
                        values=tuple(
                            OptionValue(value=value, evidence_ids=tuple(sorted(ids)))
                            for value, ids in sorted(values.items())
                        ),
                    )
                    for axis, values in sorted(axes.items())
                ),
                evidence_ids=tuple(
                    sorted(
                        evidence_id
                        for values in axes.values()
                        for ids in values.values()
                        for evidence_id in ids
                    )
                ),
            )
        )
    return tuple(catalogs)
