from __future__ import annotations

from collections import defaultdict

from pydantic import Field

from app.core.config.extraction_rules import DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_url_resource_identity,
)
from app.core.records.product_identity import (
    normalized_product_identity_value,
    product_identity_sets_compatible,
    product_identity_sets_match,
    product_title_identity_tokens,
    product_url_target_rank,
    target_product_owner_id,
)
from app.core.records.variant_identity import (
    matching_variant_owner,
    preferred_variant_key,
    selected_variant_values,
    variant_identity_keys,
    variant_identity_keys_overlap,
    variant_options,
    variant_values_support_selection,
)
from app.core.shared.ids import stable_id
from app.core.shared.url_utils import asset_url_identity
from app.extraction.contracts import (
    CaptureBundle,
    Evidence,
    FrozenModel,
    ProductOptionCatalog,
)
from app.extraction.product_options import (
    apply_dom_variant_selection,
    build_option_catalogs,
    is_dom_selection_signal,
)

type ProductIds = set[tuple[str, str]]


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
    identity_keys: tuple[str, ...] = ()
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
    target_rank: int = 2


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
    option_catalogs = build_option_catalogs(evidence, product_by_subject)
    variants = _link_variants(evidence, product_by_subject)
    variants = apply_dom_variant_selection(
        bundle, evidence, variants, product_by_subject
    )
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
    target_title_tokens = product_title_identity_tokens(
        (detail_title_from_url(bundle.final_url or bundle.requested_url),)
    )
    product_by_subject = _product_by_subject(products, evidence)
    ranked: list[tuple[int, str, ProductEntity]] = []
    for product in products:
        rows = _product_selection_rows(product, by_id, product_by_subject)
        score = _primary_product_root_score(
            rows,
            target_identity=target_identity,
            target_title_tokens=target_title_tokens,
        )
        ranked.append((score, product.entity_id, product))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] <= 0:
        return products
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return products
    return (ranked[0][2],)


def _product_selection_rows(
    product: ProductEntity,
    by_id: dict[str, Evidence],
    product_by_subject: dict[str, str],
) -> list[Evidence]:
    rows = [
        by_id[evidence_id]
        for ids in product.attribute_evidence.values()
        for evidence_id in ids
        if evidence_id in by_id
    ]
    product_id = product.entity_id
    rows.extend(
        row
        for row in by_id.values()
        if row.fact_type.startswith(("variant.", "offer."))
        and _owner_product_id(
            [row],
            product_by_subject,
            allowed_relations=frozenset({"product_variant", "variant_offer"}),
        )
        == product_id
    )
    return rows


def _primary_product_root_score(
    rows: list[Evidence], *, target_identity: str, target_title_tokens: set[str]
) -> int:
    return sum(
        _product_root_row_score(
            row,
            target_identity=target_identity,
            target_title_tokens=target_title_tokens,
        )
        for row in rows
    )


def _product_root_row_score(
    row: Evidence, *, target_identity: str, target_title_tokens: set[str]
) -> int:
    score = (
        100 if row.entity_hint is not None and row.entity_hint.selected is True else 0
    )
    if row.fact_type == "product.url":
        identity = detail_url_resource_identity(str(row.value))
        score += (
            80
            if target_identity and identity == target_identity
            else -20
            if identity
            else 0
        )
    if row.fact_type == "product.title" and target_title_tokens:
        title_tokens = product_title_identity_tokens((row.value,))
        if title_tokens == target_title_tokens:
            score += 40
        elif target_title_tokens <= title_tokens:
            score += 15
        elif title_tokens & target_title_tokens:
            score += 5
    if row.fact_type in {"variant.gtin", "variant.sku"}:
        score += 130
    if row.collector_id == "url" and row.fact_type == "product.url":
        score += 10
    return score + int(row.subject_scope == "product")


def _product_child_ids(children, product_id: str) -> tuple[str, ...]:
    return tuple(
        item.entity_id
        for item in children
        if item.product_entity_id == product_id and item.variant_entity_id is None
    )


def _link_products(evidence: tuple[Evidence, ...]) -> tuple[ProductEntity, ...]:
    by_subject = _product_rows_by_subject(evidence)
    groups: list[list[Evidence]] = []
    group_identities: list[set[tuple[str, str]]] = []
    child_rows_by_parent_subject = _child_variant_urls_by_parent(evidence)
    for subject, rows in sorted(by_subject.items()):
        identities = _product_identities(rows + child_rows_by_parent_subject[subject])
        matched = _matching_product_group_index(group_identities, identities)
        if matched is None:
            groups.append(list(rows))
            group_identities.append(set(identities) or {("subject", subject)})
            continue
        groups[matched].extend(rows)
        group_identities[matched].update(identities)
    _merge_target_url_groups(groups, group_identities)
    _merge_exact_title_groups(groups, group_identities)
    return tuple(
        _product_entity(identities, rows)
        for identities, rows in sorted(
            zip(group_identities, groups), key=lambda item: tuple(sorted(item[0]))
        )
    )


def _product_rows_by_subject(
    evidence: tuple[Evidence, ...],
) -> dict[str, list[Evidence]]:
    by_subject: dict[str, list[Evidence]] = defaultdict(list)
    for row in evidence:
        if row.fact_type.startswith("product."):
            by_subject[row.subject_id].append(row)
    return by_subject


def _child_variant_urls_by_parent(
    evidence: tuple[Evidence, ...],
) -> dict[str, list[Evidence]]:
    child_rows: dict[str, list[Evidence]] = defaultdict(list)
    for row in evidence:
        if row.fact_type != "variant.url" or row.relation_type != "product_variant":
            continue
        for subject_id in _parent_subject_aliases(row):
            child_rows[subject_id].append(row)
    return child_rows


def _product_entity(identities: ProductIds, rows: list[Evidence]) -> ProductEntity:
    identity_rows = [
        row
        for row in rows
        if row.fact_type
        in {"product.gtin", "product.mpn", "product.sku", "product.url"}
    ]
    return ProductEntity(
        entity_id=stable_id("product", sorted(identities)),
        identity_evidence_ids=tuple(
            sorted(row.evidence_id for row in identity_rows or rows)
        ),
        attribute_evidence=_fact_evidence(rows),
        variant_ids=(),
        offer_ids=(),
        asset_ids=(),
    )


def _fact_evidence(rows: list[Evidence]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        grouped[row.fact_type].append(row.evidence_id)
    return {name: tuple(sorted(set(ids))) for name, ids in grouped.items()}


def _matching_product_group_index(
    group_identities: list[ProductIds],
    identities: ProductIds,
) -> int | None:
    if not identities:
        return None
    return next(
        (
            index
            for index, existing in enumerate(group_identities)
            if product_identity_sets_match(existing, identities)
            and product_identity_sets_compatible(existing, identities)
        ),
        None,
    )


def _merge_exact_title_groups(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
) -> None:
    def _identified_indices() -> list[int]:
        return [
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
            for target in _identified_indices()
            if target != index
            and product_identity_sets_compatible(
                group_identities[target], group_identities[index]
            )
            and titles & _normalized_product_titles(groups[target])
        ]
        if len(matches) != 1:
            continue
        target = matches[0]
        groups[target].extend(groups.pop(index))
        group_identities[target].update(group_identities.pop(index))


def _normalized_product_titles(rows: list[Evidence]) -> set[str]:
    return {
        " ".join(str(row.value).casefold().split())
        for row in rows
        if row.fact_type == "product.title"
        and str(row.value).strip()
        and set(row.flags) <= {"title_url_match", "url_derived_title"}
    }


def _merge_target_url_groups(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
) -> None:
    url_only = [
        index for index, rows in enumerate(groups) if _url_collector_group(rows)
    ]
    if len(url_only) != 1:
        return
    source = url_only[0]
    candidates = _target_group_candidates(groups, group_identities, source)
    best = max((score for score, _index in candidates), default=0)
    targets = [
        index
        for score, index in candidates
        if score == best and score >= DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP
    ]
    if len(targets) != 1:
        return
    target = targets[0]
    compatible = _compatible_target_group_indices(
        candidates, group_identities, source=source, target=target
    )
    target_rows = groups[target]
    target_identities = group_identities[target]
    for index in sorted(compatible, reverse=True):
        target_rows.extend(groups.pop(index))
        target_identities.update(group_identities.pop(index))


def _target_group_candidates(
    groups: list[list[Evidence]],
    group_identities: list[set[tuple[str, str]]],
    source: int,
) -> list[tuple[int, int]]:
    target_tokens = product_title_identity_tokens(
        row.value for row in groups[source] if row.fact_type == "product.title"
    )
    return [
        (
            _compatible_group_score(
                ids, group_identities[source], groups[index], target_tokens
            ),
            index,
        )
        for index, ids in enumerate(group_identities)
        if index != source
    ]


def _compatible_target_group_indices(
    candidates: list[tuple[int, int]],
    group_identities: list[set[tuple[str, str]]],
    *,
    source: int,
    target: int,
) -> set[int]:
    compatible = {
        index
        for score, index in candidates
        if score >= DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP
        and product_identity_sets_compatible(
            group_identities[index], group_identities[target]
        )
    }
    compatible.add(source)
    compatible.discard(target)
    return compatible


def _url_collector_group(rows: list[Evidence]) -> bool:
    return bool(rows) and all(row.collector_id == "url" for row in rows)


def _compatible_group_score(
    identities: ProductIds,
    source_identities: ProductIds,
    rows: list[Evidence],
    target_tokens: set[str],
) -> int:
    if not product_identity_sets_compatible(identities, source_identities):
        return 0
    return 100 * int(product_identity_sets_match(identities, source_identities)) + len(
        target_tokens
        & product_title_identity_tokens(
            row.value for row in rows if row.fact_type == "product.title"
        )
    )


def _product_identities(rows: list[Evidence]) -> ProductIds:
    identities: ProductIds = set()
    has_product_url = any(
        row.fact_type == "product.url" and str(row.value).strip() for row in rows
    )
    for row in rows:
        identities.update(_row_product_identities(row, has_product_url=has_product_url))
    return identities


def _row_product_identities(
    row: Evidence, *, has_product_url: bool
) -> set[tuple[str, str]]:
    identities: set[tuple[str, str]] = set()
    product_id = normalized_product_identity_value(
        row.entity_hint.product_id if row.entity_hint else None
    )
    if product_id:
        identities.add(("product.id", product_id))
    if row.fact_type in {"product.gtin", "product.mpn", "product.sku"}:
        value = normalized_product_identity_value(row.value)
        if value:
            identities.add((row.fact_type, value))
    identities.update(_jsonld_product_identities(row, has_product_url=has_product_url))
    if row.fact_type in {"product.url", "variant.url"}:
        resource_identity = detail_url_resource_identity(str(row.value))
        if resource_identity:
            identities.add(("product.url_resource", resource_identity))
    if row.fact_type == "product.url":
        exact_url = normalized_product_identity_value(row.value)
        if exact_url:
            identities.add(("product.url", exact_url))
    return identities


def _jsonld_product_identities(
    row: Evidence, *, has_product_url: bool
) -> set[tuple[str, str]]:
    if row.collector_id != "jsonld":
        return set()
    node_id = normalized_product_identity_value(row.metadata.get("jsonld_node_id"))
    node_path = normalized_product_identity_value(row.metadata.get("jsonld_node_path"))
    if node_id:
        identities = {("jsonld.node_id", node_id)}
        if resource_identity := detail_url_resource_identity(node_id):
            identities.add(("product.url_resource", resource_identity))
        return identities
    return (
        {("jsonld.node_path", node_path)}
        if node_path and not has_product_url
        else set()
    )


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
    return ev.source_subject_ids or _metadata_subject_aliases(ev, "source_subject_ids")


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
    groups = _merge_selected_variant_groups(groups)
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


def _merge_selected_variant_groups(
    groups: list[tuple[str, set[str], list[Evidence], set[str]]],
) -> list[tuple[str, set[str], list[Evidence], set[str]]]:
    removed: set[int] = set()
    for source, (product_id, _keys, rows, _subjects) in enumerate(groups):
        if source in removed:
            continue
        hint = next((r.entity_hint for r in rows if r.collector_id == "url"), None)
        if hint is None or hint.selected is not True:
            continue
        selected = selected_variant_values(row.entity_hint for row in rows)
        matches = _selected_variant_group_matches(
            groups,
            source=source,
            removed=removed,
            product_id=product_id,
            selected=selected,
        )
        if not matches:
            continue
        for target in matches:
            groups[target][1].update(groups[source][1])
            groups[target][2].extend(rows)
            groups[target][3].update(groups[source][3])
        removed.add(source)
    return [group for index, group in enumerate(groups) if index not in removed]


def _selected_variant_group_matches(
    groups: list[tuple[str, set[str], list[Evidence], set[str]]],
    *,
    source: int,
    removed: set[int],
    product_id: str,
    selected: tuple[str, ...],
) -> list[int]:
    return [
        index
        for index, (owner, _keys, candidate, _subjects) in enumerate(groups)
        if index != source
        and index not in removed
        and owner == product_id
        and variant_values_support_selection((row.value for row in candidate), selected)
    ]


def _variant_options_from_rows(rows: list[Evidence]) -> dict[str, str]:
    return variant_options(rows)


def _variant_groups(
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
) -> list[tuple[str, set[str], list[Evidence], set[str]]]:
    provisional = _provisional_variant_rows(evidence)
    selected_owners = _selected_variant_owners(provisional, product_by_subject)
    commercially_owned_subjects = _commercially_owned_variant_subjects(evidence)
    groups: list[list[Evidence]] = []
    group_keys: list[set[str]] = []
    subjects: list[set[str]] = []
    product_ids: list[str] = []
    for subject_id, rows in provisional.items():
        group = _variant_group_input(
            subject_id,
            rows,
            product_by_subject,
            inferred_product_id=matching_variant_owner(
                (row.value for row in rows),
                (
                    (owner, (row.entity_hint for row in selected_rows))
                    for owner, selected_rows in selected_owners
                ),
            ),
            commercially_owned_subjects=commercially_owned_subjects,
        )
        if group is None:
            continue
        product_id, keys, source_subjects = group
        matched = next(
            (
                index
                for index, existing in enumerate(group_keys)
                if product_ids[index] == product_id
                and variant_identity_keys_overlap(existing, keys)
            ),
            None,
        )
        if matched is None:
            groups.append(list(rows))
            group_keys.append(set(keys))
            subjects.append(source_subjects)
            product_ids.append(product_id)
        else:
            groups[matched].extend(rows)
            group_keys[matched].update(keys)
            subjects[matched].update(source_subjects)
    return sorted(
        zip(product_ids, group_keys, groups, subjects),
        key=lambda item: (item[0], sorted(item[1])),
    )


def _provisional_variant_rows(
    evidence: tuple[Evidence, ...],
) -> dict[str, list[Evidence]]:
    provisional: dict[str, list[Evidence]] = defaultdict(list)
    for row in evidence:
        if row.fact_type.startswith("variant.") and not is_dom_selection_signal(row):
            provisional[row.subject_id].append(row)
    return provisional


def _selected_variant_owners(
    provisional: dict[str, list[Evidence]], product_by_subject: dict[str, str]
) -> list[tuple[str, list[Evidence]]]:
    return [
        (owner, rows)
        for rows in provisional.values()
        if any(row.fact_type == "variant.selected" and row.value for row in rows)
        if (
            owner := _owner_product_id(rows, product_by_subject, allowed_relations=None)
        )
    ]


def _commercially_owned_variant_subjects(
    evidence: tuple[Evidence, ...],
) -> set[str]:
    return {
        ev.parent_subject_id
        for ev in evidence
        if ev.fact_type.startswith("offer.") and ev.parent_subject_id
    }


def _variant_group_input(
    subject_id: str,
    rows: list[Evidence],
    product_by_subject: dict[str, str],
    *,
    inferred_product_id: str | None,
    commercially_owned_subjects: set[str],
) -> tuple[str, set[str], set[str]] | None:
    product_id = _owner_product_id(rows, product_by_subject, allowed_relations=None)
    product_id = product_id or inferred_product_id
    keys = variant_identity_keys(rows)
    has_sellable_identity = any(
        key.startswith(("sku:", "gtin:", "url:")) for key in keys
    ) or (
        any(key.startswith("id:") for key in keys)
        and any(row.fact_type.startswith("variant.option.") for row in rows)
    )
    if (
        not product_id
        or not keys
        or not (has_sellable_identity or subject_id in commercially_owned_subjects)
    ):
        return None
    source_subjects = {
        subject_id,
        *(alias for row in rows for alias in _source_subject_aliases(row)),
    }
    return product_id, keys, source_subjects


def _variant_entity(
    product_id: str,
    keys: set[str],
    rows: list[Evidence],
    source_subjects: set[str],
) -> VariantEntity:
    identity_facts = {"variant.id", "variant.sku", "variant.gtin", "variant.url"}
    identity_ids = tuple(
        sorted(ev.evidence_id for ev in rows if ev.fact_type in identity_facts)
    )
    return VariantEntity(
        entity_id=stable_id("variant", product_id, preferred_variant_key(keys)),
        product_entity_id=product_id,
        identity_key=preferred_variant_key(keys),
        identity_keys=tuple(sorted(keys)),
        source_subject_ids=tuple(sorted(source_subjects)),
        identity_evidence_ids=identity_ids
        or tuple(sorted(ev.evidence_id for ev in rows)),
        option_values={
            ev.fact_type.removeprefix("variant.option."): str(ev.value)
            for ev in rows
            if ev.fact_type.startswith("variant.option.")
        },
        attribute_evidence=_fact_evidence(rows),
        offer_ids=(),
        asset_ids=(),
        selected=any(
            (ev.fact_type == "variant.selected" and bool(ev.value))
            or bool(ev.entity_hint and ev.entity_hint.selected)
            for ev in rows
        ),
    )


def _link_offers(
    bundle: CaptureBundle,
    evidence: tuple[Evidence, ...],
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
) -> tuple[OfferEntity, ...]:
    groups = _offer_evidence_groups(evidence)
    offers: list[OfferEntity] = []
    for group_id, rows in sorted(groups.items()):
        offer = _offer_entity(
            bundle,
            group_id,
            rows,
            product_by_subject=product_by_subject,
            variants=variants,
        )
        if offer is not None:
            offers.append(offer)
    return tuple(offers)


def _offer_evidence_groups(
    evidence: tuple[Evidence, ...],
) -> dict[str, list[Evidence]]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for row in evidence:
        if row.fact_type.startswith("offer."):
            groups[row.group_id or f"ungrouped:{row.evidence_id}"].append(row)
    return groups


def _offer_entity(
    bundle: CaptureBundle,
    group_id: str,
    rows: list[Evidence],
    *,
    product_by_subject: dict[str, str],
    variants: tuple[VariantEntity, ...],
) -> OfferEntity | None:
    relations = {row.relation_type for row in rows} - {None}
    if len(relations) > 1:
        return None
    relation = next(iter(relations), None)
    row_variant_ids = {_variant_for([row], variants) for row in rows}
    mixed_variant_scope = None in row_variant_ids and len(row_variant_ids) > 1
    if (relation, mixed_variant_scope) in {(None, True), ("variant_offer", True)}:
        return None
    variant_id = (
        _variant_for(rows, variants) if relation in {None, "variant_offer"} else None
    )
    is_target = group_id.startswith("offer:target:")
    target_rank = (
        -1
        if is_target
        else product_url_target_rank(bundle.final_url or bundle.requested_url, rows)
    )
    product_id = target_product_owner_id(
        is_target,
        _product_for_child(rows, product_by_subject, variants, variant_id),
        product_by_subject.values(),
    )
    if relation == "variant_offer" and variant_id is None:
        return None
    if relation == "product_offer" and variant_id is not None:
        return None
    if product_id is None:
        return None
    return OfferEntity(
        entity_id=stable_id("offer", product_id, variant_id, group_id),
        product_entity_id=product_id,
        variant_entity_id=variant_id,
        group_id=group_id,
        request_context_id=bundle.request_context.context_id,
        fact_evidence=_fact_evidence(rows),
        target_rank=target_rank,
    )


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
        candidate_keys = variant.identity_keys or (variant.identity_key,)
        if any(
            str(item).split(":", 1)[-1] in skus
            for item in candidate_keys
            if str(item).startswith("sku:")
        ):
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
