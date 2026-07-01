from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Literal
from app.core.config.field_mappings import (
    ASSET_IMAGE_URL_FACT_TYPE,
    ECOMMERCE_DETAIL_FIELD_FACT_TYPES,
    ECOMMERCE_IMAGE_SOURCE_KEYS,
    ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS,
    ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_CONTAINER_SOURCE_KEYS,
    ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES,
    VARIANT_GTIN_FACT_TYPE,
)
from app.core.config.extraction_rules import (
    ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS,
    ECOMMERCE_EMBEDDED_STATE_NOISE_SCOPE_TOKENS,
    MAX_DIAGNOSTIC_EXAMPLES_PER_REASON,
    MAX_EVIDENCE_PER_SOURCE_OBJECT,
    MAX_SOURCE_OBJECTS_PER_ARTIFACT,
    VARIANT_PLACEHOLDER_VALUES,
    VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS,
)
from app.core.config import variant_policy
from app.core.records.html_helpers import bounded_json_objects, embedded_state_payloads
from app.core.records.structured_variant_state import (
    canonical_axis as _canonical_axis,
    configured_value_path_rows,
    expand_embedded_state_payload,
    first as _first,
    same_product_variant_endpoint,
    scalar_value as _scalar_value,
    source_values,
    url_value as _url_value,
    variant_axis_hints,
    with_parent_variant_axes,
)
from app.core.records.js_state_scope import (
    has_product_context as _has_product_context,
    path_product_identity_conflicts as _path_product_identity_conflicts,
    path_tokens as _path_tokens,
    root_admits_path,
    select_product_roots,
)
from app.core.records.url_identity import (
    detail_title_from_url,
    detail_urls_conflict,
    semantic_identity_tokens,
)
from app.core.shared.field_coerce import (
    sanitize_option_scalar,
    variant_option_value_is_opaque_numeric,
)
from app.extraction.collectors._helpers import evidence, html_doc, json_objects
from app.extraction.contracts import (
    CaptureBundle,
    CollectorOutcome,
    EntityHint,
    Evidence,
    SourceLocator,
)
from app.core.shared.ids import stable_id


@dataclass(frozen=True)
class StructuredHarvestResult:
    evidence: tuple[Evidence, ...]
    outcomes: tuple[CollectorOutcome, ...]
    admitted_source_objects: int


class JsStateCollector:
    collector_id = "js_state"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        return self.harvest(bundle, artifacts).evidence

    def harvest(
        self,
        bundle: CaptureBundle,
        artifacts,
        *,
        requested_fields: tuple[str, ...] = (),
    ) -> StructuredHarvestResult:
        out: list[Evidence] = []
        outcomes: list[CollectorOutcome] = []
        admitted_source_objects = 0
        for artifact_id, root_path, data in _state_payloads(bundle, artifacts):
            objects = tuple(
                json_objects(data)
                if not root_path
                else bounded_json_objects(
                    data,
                    max_depth=variant_policy.EMBEDDED_STATE_MAX_DEPTH,
                    max_nodes=variant_policy.EMBEDDED_STATE_MAX_NODES,
                    max_list_items=variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS,
                )
            )
            if len(objects) > MAX_SOURCE_OBJECTS_PER_ARTIFACT:
                outcomes.append(
                    budget_outcome(
                        variant_policy.STRUCTURED_SOURCE_OBJECT_BUDGET_REASON,
                        artifact_id=artifact_id,
                        root_path=root_path,
                        count=len(objects),
                        limit=MAX_SOURCE_OBJECTS_PER_ARTIFACT,
                        examples=tuple(
                            path
                            for path, _ in objects[:MAX_DIAGNOSTIC_EXAMPLES_PER_REASON]
                        ),
                    )
                )
                objects = objects[:MAX_SOURCE_OBJECTS_PER_ARTIFACT]
            axis_hints = variant_axis_hints(objects)
            selection = select_product_roots(objects, bundle.final_url)
            for path, obj in objects:
                if not root_admits_path(selection, path):
                    continue
                if isinstance(obj, dict):
                    admitted_source_objects += 1
                    enriched = with_parent_variant_axes(obj, axis_hints.get(path, ()))
                    rows = network_row(
                        bundle,
                        artifact_id,
                        f"{root_path}{path}",
                        enriched,
                    )
                    rows, dropped = prioritize_evidence_rows(
                        rows,
                        requested_fields=requested_fields,
                        limit=MAX_EVIDENCE_PER_SOURCE_OBJECT,
                    )
                    if dropped:
                        outcomes.append(
                            budget_outcome(
                                variant_policy.STRUCTURED_EVIDENCE_BUDGET_REASON,
                                artifact_id=artifact_id,
                                root_path=f"{root_path}{path}",
                                count=len(rows) + len(dropped),
                                limit=MAX_EVIDENCE_PER_SOURCE_OBJECT,
                                dropped=dropped,
                            )
                        )
                    out.extend(rows)
        produced = CollectorOutcome(
            collector_id=self.collector_id,
            outcome="produced_evidence" if out else "no_match",
            evidence_count=len(out),
        )
        return StructuredHarvestResult(
            evidence=tuple(out),
            outcomes=(*outcomes, produced),
            admitted_source_objects=admitted_source_objects,
        )


def budget_outcome(
    reason: str,
    *,
    artifact_id: str,
    root_path: str,
    count: int,
    limit: int,
    examples: tuple[str, ...] = (),
    dropped: tuple[Evidence, ...] = (),
) -> CollectorOutcome:
    bounded_examples = _bounded_unique_examples(
        examples or (row.locator.value for row in dropped)
    )
    dropped_families = tuple(
        dict.fromkeys(_evidence_fact_family(row) for row in dropped)
    )
    return CollectorOutcome(
        collector_id=JsStateCollector.collector_id,
        outcome="budget_limited",
        evidence_count=0,
        detail=(
            f"{reason}; artifact_id={artifact_id}; root_path={root_path or '/'}; "
            f"count={count}; limit={limit}; examples={list(bounded_examples)!r}"
        ),
        source_path=root_path or "/",
        dropped_fact_families=dropped_families,
        dropped_source_paths=bounded_examples,
    )


def _bounded_unique_examples(examples: Iterable[str]) -> tuple[str, ...]:
    bounded: list[str] = []
    seen: set[str] = set()
    for example in examples:
        value = str(example)
        if value in seen:
            continue
        seen.add(value)
        bounded.append(value)
        if len(bounded) >= MAX_DIAGNOSTIC_EXAMPLES_PER_REASON:
            break
    return tuple(bounded)


def prioritize_evidence_rows(
    rows: list[Evidence],
    *,
    requested_fields: tuple[str, ...],
    limit: int,
) -> tuple[list[Evidence], tuple[Evidence, ...]]:
    """Keep structural and requested facts before descriptive bulk evidence."""

    requested_facts = {
        fact
        for field in requested_fields
        if (fact := ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field))
    }
    if requested_facts & variant_policy.STRUCTURED_EVIDENCE_ATOMIC_OFFER_FACTS:
        requested_facts.update(variant_policy.STRUCTURED_EVIDENCE_ATOMIC_OFFER_FACTS)
    ranked = sorted(
        enumerate(rows),
        key=lambda item: (_evidence_priority(item[1], requested_facts), item[0]),
    )
    kept = [row for _index, row in ranked[: max(0, limit)]]
    dropped = tuple(row for _index, row in ranked[max(0, limit) :])
    return kept, dropped


def _evidence_priority(row: Evidence, requested_facts: set[str]) -> int:
    fact = row.fact_type
    ranks = variant_policy.STRUCTURED_EVIDENCE_PRIORITY_RANKS
    if fact in variant_policy.STRUCTURED_EVIDENCE_IDENTITY_FACTS:
        return ranks["identity"]
    if fact in requested_facts:
        return ranks["requested"]
    if fact.startswith("variant.option."):
        return ranks["options"]
    if fact in variant_policy.STRUCTURED_EVIDENCE_ATOMIC_OFFER_FACTS:
        return ranks["offer"]
    if fact in variant_policy.STRUCTURED_EVIDENCE_IDENTIFIER_FACTS:
        return ranks["identifiers"]
    if fact == "variant.url" or row.relation_type == "variant_asset":
        return ranks["variant_assets"]
    if fact in variant_policy.STRUCTURED_EVIDENCE_DESCRIPTIVE_FACTS:
        return ranks["descriptive"]
    return ranks["identifiers"]


def _evidence_fact_family(row: Evidence) -> str:
    fact = row.fact_type
    prefixes = variant_policy.STRUCTURED_EVIDENCE_FACT_PREFIXES
    families = variant_policy.STRUCTURED_EVIDENCE_FACT_FAMILIES
    if fact.startswith(prefixes["variant_options"]):
        return families["variant_options"]
    if fact.startswith(prefixes["variant_identity"]):
        return families["variant_identity"]
    if fact.startswith(prefixes["offer"]):
        return families["offer"]
    if fact.startswith(prefixes["assets"]):
        return (
            families["variant_assets"]
            if row.relation_type == "variant_asset"
            else families["assets"]
        )
    return fact.split(".", 1)[0]


def _state_payloads(bundle: CaptureBundle, artifacts):
    for ref in bundle.artifacts:
        if ref.artifact_type == "js_state":
            yield ref.artifact_id, "", artifacts.read_json(ref)
    _, document = html_doc(bundle, artifacts)
    payloads = tuple(
        embedded_state_payloads(
            document,
            selector=variant_policy.EMBEDDED_STATE_SCRIPT_SELECTOR,
            global_keys=variant_policy.EMBEDDED_STATE_GLOBAL_KEYS,
            max_scripts=variant_policy.EMBEDDED_STATE_MAX_SCRIPTS,
            max_script_chars=variant_policy.EMBEDDED_STATE_MAX_SCRIPT_CHARS,
            exclude_node=_embedded_state_node_is_noise,
        )
    )
    meta_segment = f"/{variant_policy.EMBEDDED_STATE_PRODUCT_META_KEY}/"
    richer_variant_ids = {
        variant_id
        for root_path, data in payloads
        if meta_segment not in root_path
        for variant_id in _payload_variant_ids(data)
    }
    for root_path, data in payloads:
        if _is_unrelated_meta_payload(
            root_path,
            data,
            richer_variant_ids=richer_variant_ids,
        ):
            continue
        for expanded_path, expanded in expand_embedded_state_payload(root_path, data):
            yield document.artifact_id, expanded_path, expanded


def _embedded_state_node_is_noise(node: object) -> bool:
    scoped_nodes = (node, *getattr(node, "ancestors")())
    for scoped_node in scoped_nodes:
        attribute = getattr(scoped_node, "attribute")
        scope = " ".join(
            str(attribute(name) or "")
            for name in (
                "class",
                "id",
                "data-section-type",
                "data-testid",
                "aria-label",
            )
        )
        normalized = "".join(char for char in scope.casefold() if char.isalnum())
        if any(
            token in normalized for token in ECOMMERCE_EMBEDDED_STATE_NOISE_SCOPE_TOKENS
        ):
            return True
    return False


def _is_unrelated_meta_payload(
    root_path: str,
    data: object,
    *,
    richer_variant_ids: set[str],
) -> bool:
    meta_segment = f"/{variant_policy.EMBEDDED_STATE_PRODUCT_META_KEY}/"
    if meta_segment not in root_path:
        return False
    if not isinstance(data, dict):
        return True
    product = data.get(variant_policy.EMBEDDED_STATE_PRODUCT_META_CONTAINER_KEY)
    if not (
        isinstance(product, dict)
        and isinstance(
            product.get(variant_policy.EMBEDDED_STATE_PRODUCT_META_VARIANTS_KEY), list
        )
    ):
        return True
    compact_ids = set(_payload_variant_ids(product))
    return bool(compact_ids and compact_ids <= richer_variant_ids)


def _payload_variant_ids(data: object) -> tuple[str, ...]:
    rows = bounded_json_objects(
        data,
        max_depth=variant_policy.EMBEDDED_STATE_MAX_DEPTH,
        max_nodes=variant_policy.EMBEDDED_STATE_MAX_NODES,
        max_list_items=variant_policy.EMBEDDED_STATE_MAX_LIST_ITEMS,
    )
    return tuple(
        variant_id
        for path, obj in rows
        if isinstance(obj, dict)
        and _path_tokens(path) & variant_policy.VARIANT_STRUCTURED_PATH_TOKENS
        for variant_id in [_variant_identity_value(obj)]
        if variant_id
    )


def network_row(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    *,
    collector_id: str = "js_state",
) -> list[Evidence]:
    out: list[Evidence] = []
    if _path_tokens(path) & ECOMMERCE_CONTEXT_NOISE_PATH_TOKENS:
        return out
    if _path_product_identity_conflicts(bundle.final_url, path):
        return out
    if _has_only_opaque_numeric_options(obj):
        return out
    if _looks_like_variant(obj, path=path):
        if _variant_url_conflicts(bundle.final_url, obj) or _variant_title_conflicts(
            bundle.final_url, obj
        ):
            return out
        return _variant_row(bundle, artifact_id, path, obj, collector_id=collector_id)
    direct_keys = tuple(
        key
        for key in ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES
        if key in obj
        and not (
            isinstance(obj.get(key), dict)
            and key in ECOMMERCE_STRUCTURED_CONTAINER_SOURCE_KEYS
        )
    )
    path_rows = configured_value_path_rows(obj)
    if not direct_keys and not path_rows:
        return out
    if _product_url_conflicts(bundle.final_url, obj):
        return out
    product_context = _has_product_context(path, obj)
    offer_context = _has_offer_context(path, obj, product_context=product_context)
    if not product_context and not offer_context:
        return out
    group = f"offer:{artifact_id}:{path}" if offer_context else None
    product_subject = evidence(
        bundle,
        "url",
        "url",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="url_component", value="url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        directness="inferred",
        confidence=0.0,
    ).subject_id
    product_source_subject_ids = _structured_source_subject_ids(bundle, obj)
    source_rows = [
        (key, fact, value, suffix)
        for key in direct_keys
        for fact in (ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES[key],)
        for index, value in enumerate(source_values(key, obj.get(key)))
        for suffix in (f"/{index}" if key in ECOMMERCE_IMAGE_SOURCE_KEYS else "",)
    ]
    source_rows.extend(path_rows)
    for key, fact, value, suffix in source_rows:
        if fact.startswith("product.") and not product_context:
            continue
        if fact.startswith("offer.") and not offer_context:
            continue
        if value in (None, "", [], {}):
            continue
        entity_type: Literal["offer", "asset", "product"] = (
            "offer"
            if fact.startswith("offer.")
            else "asset"
            if fact.startswith("asset.")
            else "product"
        )
        product_identity = next(
            (
                str(obj.get(identity_key) or "").strip()
                for identity_key in ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS
                if str(obj.get(identity_key) or "").strip()
            ),
            None,
        )
        hint = EntityHint(
            entity_type=entity_type,
            product_id=product_identity if entity_type == "product" else None,
            sku=str(obj.get("sku") or "").strip() or None,
        )
        out.append(
            evidence(
                bundle,
                artifact_id,
                collector_id,
                fact,
                value,
                SourceLocator(kind="script_path", value=f"{path}/{key}{suffix}"),
                group_id=group if fact.startswith("offer.") else None,
                hint=hint,
                directness="embedded",
                confidence=0.8,
                parent_subject_id=product_subject
                if fact.startswith(("offer.", "asset."))
                else None,
                parent_scope="product"
                if fact.startswith(("offer.", "asset."))
                else None,
                source_subject_ids=product_source_subject_ids
                if fact.startswith("product.")
                else (),
            )
        )
    return out


def _variant_url_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _url_value(obj)
    if candidate and same_product_variant_endpoint(page_url, candidate):
        return False
    return bool(
        candidate
        and detail_urls_conflict(
            page_url,
            candidate,
            strict_terminal_code=False,
        )
    )


def _variant_title_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _scalar_value(
        _first(obj, "productName", "product_name", "productTitle", "product_title")
    )
    if not isinstance(candidate, str) or not candidate.strip():
        return False
    page_tokens = set(semantic_identity_tokens(detail_title_from_url(page_url)))
    candidate_tokens = set(semantic_identity_tokens(candidate))
    if len(page_tokens) < 2 or len(candidate_tokens) < 2:
        return False
    overlap = len(page_tokens & candidate_tokens)
    return overlap == 0


def _product_url_conflicts(page_url: str, obj: dict) -> bool:
    candidate = _url_value(obj)
    if candidate and same_product_variant_endpoint(page_url, candidate):
        return False
    return bool(
        candidate
        and detail_urls_conflict(
            page_url,
            candidate,
            strict_terminal_code=False,
        )
    )


def _has_offer_context(path: str, obj: dict, *, product_context: bool) -> bool:
    type_name = str(obj.get("@type") or obj.get("type") or "").casefold()
    path_tokens = _path_tokens(path)
    return (
        product_context
        or "offer" in type_name
        or bool(path_tokens & ECOMMERCE_OFFER_CONTEXT_PATH_TOKENS)
    )


def _variant_row(
    bundle: CaptureBundle, artifact_id: str, path: str, obj: dict, *, collector_id: str
) -> list[Evidence]:
    if not _looks_like_variant(obj, path=path):
        return []
    variant_id = _variant_identity_value(obj)
    sku = str(
        _scalar_value(_first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS)) or ""
    ).strip()
    hint = EntityHint(
        entity_type="variant",
        variant_id=variant_id,
        sku=sku or None,
        selected=bool(obj.get("selected") or obj.get("isSelected"))
        if "selected" in obj or "isSelected" in obj
        else None,
    )
    group = f"variant:{artifact_id}:{path}"
    subject_id = stable_id(
        "subject",
        bundle.bundle_id,
        artifact_id,
        "variant",
        hint.variant_id or sku or group,
    )
    product_subject = evidence(
        bundle,
        "url",
        "url",
        "product.url",
        bundle.final_url,
        SourceLocator(kind="url_component", value="url"),
        hint=EntityHint(entity_type="product", url=bundle.final_url),
        directness="inferred",
        confidence=0.0,
    ).subject_id
    variant_source_subject_ids = _variant_source_subject_ids(bundle, obj)
    fields = _variant_fields(obj)
    flags = (
        (variant_policy.DEFAULT_VARIANT_PLACEHOLDER_FLAG,)
        if str(_scalar_value(obj.get("title")) or "").strip().casefold()
        in VARIANT_PLACEHOLDER_VALUES
        else ()
    )
    out = [
        evidence(
            bundle,
            artifact_id,
            collector_id,
            fact,
            value,
            SourceLocator(kind="script_path", value=f"{path}/{name}"),
            group_id=group,
            hint=hint,
            directness="embedded",
            confidence=0.82,
            subject_id=subject_id,
            parent_subject_id=product_subject,
            parent_scope="product",
            source_subject_ids=variant_source_subject_ids,
            flags=flags,
        )
        for name, fact, value in fields
        if value not in (None, "", [], {})
    ]
    out.extend(
        _variant_offer(
            bundle, artifact_id, path, obj, hint, subject_id, collector_id=collector_id
        )
    )
    out.extend(
        _variant_assets(
            bundle, artifact_id, path, obj, hint, subject_id, collector_id=collector_id
        )
    )
    return out


def _looks_like_variant(obj: dict, *, path: str = "") -> bool:
    if _has_variant_children(obj):
        return False
    sku = _scalar_value(_first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS))
    identity = _variant_identity_value(obj) is not None or sku not in (None, "", [], {})
    option_count = len(_variant_options(obj))
    variant_specific_identity = any(
        _scalar_value(obj.get(key)) not in (None, "", [], {})
        for key in ("variantId", "variant_id", "skuId", "sku_id")
    )
    commercial = any(
        _scalar_value(_first(obj, *keys)) not in (None, "", [], {})
        for keys in (
            variant_policy.VARIANT_OFFER_PRICE_KEYS,
            variant_policy.VARIANT_OFFER_CURRENCY_KEYS,
            variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS,
            variant_policy.VARIANT_OFFER_STOCK_KEYS,
        )
    )
    type_name = str(obj.get("type") or obj.get("__typename") or "").lower()
    if any(
        token in type_name for token in VARIANT_JS_STATE_NON_VARIANT_TYPENAME_TOKENS
    ):
        return False
    typed = "variant" in type_name
    variant_path = bool(
        _path_tokens(path) & variant_policy.VARIANT_STRUCTURED_PATH_TOKENS
    )
    return (
        identity
        and (
            (
                option_count > 0
                and (
                    typed
                    or variant_path
                    or variant_specific_identity
                    or commercial
                    or sku not in (None, "", [], {})
                )
            )
            or variant_specific_identity
            or (commercial and (typed or variant_path))
            or (variant_path and sku not in (None, "", [], {}))
        )
        or (typed and option_count >= 2)
    )


def _has_variant_children(obj: dict) -> bool:
    return any(
        isinstance(obj.get(key), list) and bool(obj.get(key))
        for key in variant_policy.VARIANT_CHILD_COLLECTION_KEYS
    )


def _variant_fields(obj: dict) -> list[tuple[str, str, object]]:
    selected = (
        bool(obj.get("selected") or obj.get("isSelected"))
        if "selected" in obj or "isSelected" in obj
        else None
    )
    raw = [
        ("id", "variant.id", _variant_identity_value(obj)),
        ("sku", "variant.sku", _first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS)),
        (
            "gtin",
            VARIANT_GTIN_FACT_TYPE,
            _first(obj, *variant_policy.VARIANT_GTIN_VALUE_KEYS),
        ),
        (
            "url",
            "variant.url",
            _first(obj, *variant_policy.VARIANT_URL_VALUE_KEYS),
        ),
        ("selected", "variant.selected", selected),
    ]
    raw.extend(
        (name, f"variant.option.{axis}", value)
        for name, axis, value in _variant_options(obj)
    )
    return [(name, fact, _scalar_value(value)) for name, fact, value in raw]


def _variant_assets(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    hint: EntityHint,
    variant_subject_id: str,
    *,
    collector_id: str,
) -> list[Evidence]:
    rows: list[Evidence] = []
    seen: set[str] = set()
    source_subject_ids = _variant_source_subject_ids(bundle, obj)
    for key in ECOMMERCE_IMAGE_SOURCE_KEYS:
        if key not in obj:
            continue
        for index, url in enumerate(source_values(key, obj.get(key))):
            normalized = str(url or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rows.append(
                evidence(
                    bundle,
                    artifact_id,
                    collector_id,
                    ASSET_IMAGE_URL_FACT_TYPE,
                    normalized,
                    SourceLocator(kind="script_path", value=f"{path}/{key}/{index}"),
                    group_id=f"variant_asset:{artifact_id}:{path}:{key}:{index}",
                    hint=EntityHint(entity_type="asset", sku=hint.sku),
                    directness="embedded",
                    confidence=0.8,
                    parent_subject_id=variant_subject_id,
                    parent_scope="variant",
                    source_subject_ids=source_subject_ids,
                )
            )
    return rows


def _variant_offer(
    bundle: CaptureBundle,
    artifact_id: str,
    path: str,
    obj: dict,
    hint: EntityHint,
    variant_subject_id: str,
    *,
    collector_id: str,
) -> list[Evidence]:
    group = f"offer:{artifact_id}:{path}"
    source_subject_ids = _variant_source_subject_ids(bundle, obj)
    rows = [
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_PRICE_KEYS) or "price",
            "offer.price",
            _first(obj, *variant_policy.VARIANT_OFFER_PRICE_KEYS),
        ),
        *(
            (key, "offer.price", obj.get(key))
            for key in variant_policy.VARIANT_OFFER_DISPLAY_PRICE_KEYS
            if obj.get(key) not in (None, "", [], {})
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_ORIGINAL_PRICE_KEYS)
            or "original_price",
            "offer.original_price",
            _first(obj, *variant_policy.VARIANT_OFFER_ORIGINAL_PRICE_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_CURRENCY_KEYS) or "currency",
            "offer.currency",
            _first(obj, *variant_policy.VARIANT_OFFER_CURRENCY_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS)
            or "availability",
            "offer.availability",
            _first(obj, *variant_policy.VARIANT_OFFER_AVAILABILITY_KEYS),
        ),
        (
            _first_key(obj, *variant_policy.VARIANT_OFFER_STOCK_KEYS)
            or "stock_quantity",
            "offer.stock_quantity",
            _first(obj, *variant_policy.VARIANT_OFFER_STOCK_KEYS),
        ),
    ]
    return [
        evidence(
            bundle,
            artifact_id,
            collector_id,
            fact,
            _scalar_value(value),
            SourceLocator(kind="script_path", value=f"{path}/{name}"),
            group_id=group,
            hint=hint,
            directness="embedded",
            confidence=0.82,
            parent_subject_id=variant_subject_id,
            parent_scope="variant",
            source_subject_ids=source_subject_ids,
        )
        for name, fact, value in rows
        if _scalar_value(value) not in (None, "", [], {})
    ]


def _structured_source_subject_ids(bundle: CaptureBundle, obj: dict) -> tuple[str, ...]:
    values = [bundle.final_url]
    values.extend(
        str(obj.get(key) or "").strip()
        for key in ECOMMERCE_PRODUCT_IDENTITY_SOURCE_KEYS
        if str(obj.get(key) or "").strip()
    )
    values.extend(
        str(_scalar_value(_first(obj, *keys)) or "").strip()
        for keys in (
            variant_policy.VARIANT_SKU_VALUE_KEYS,
            variant_policy.VARIANT_URL_VALUE_KEYS,
        )
        if str(_scalar_value(_first(obj, *keys)) or "").strip()
    )
    return _source_subject_ids(bundle, values)


def _variant_source_subject_ids(bundle: CaptureBundle, obj: dict) -> tuple[str, ...]:
    values = (
        _variant_identity_value(obj),
        _scalar_value(_first(obj, *variant_policy.VARIANT_SKU_VALUE_KEYS)),
        _url_value(obj),
    )
    return _source_subject_ids(bundle, values)


def _source_subject_ids(bundle: CaptureBundle, values) -> tuple[str, ...]:
    return tuple(
        stable_id("subject", bundle.bundle_id, "product", normalized)
        for normalized in dict.fromkeys(
            str(value).strip() for value in values if value not in (None, "", [], {})
        )
        if normalized
    )


def _first_key(obj: dict, *keys: str) -> str | None:
    for key in keys:
        value = obj.get(key)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, dict):
            return _first_key(value, *keys) or key
        return key
    for source in obj.values():
        if not isinstance(source, dict):
            continue
        nested_key = _first_key(source, *keys)
        if nested_key:
            return nested_key
    return None


def _variant_identity_value(obj: dict) -> str | None:
    for key in ("variantId", "variant_id", "skuId", "sku_id", "id"):
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            return str(value).strip()
    return None


def _variant_options(obj: dict) -> list[tuple[str, str, object]]:
    cleaned: list[tuple[str, str, object]] = []
    for name, axis, value in _raw_variant_options(obj):
        option_value = sanitize_option_scalar(axis, _scalar_value(value))
        if option_value is not None:
            cleaned.append((name, axis, option_value))
    return _dedupe_options(cleaned)


def _raw_variant_options(obj: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    for key, axis in variant_policy.VARIANT_DIRECT_OPTION_FIELD_AXES.items():
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            rows.append((key, axis, value))
    for key in variant_policy.VARIANT_OPTION_CONTAINER_KEYS:
        rows.extend(_option_rows_from_value(key, obj.get(key)))
    if not any(axis == "size" for _name, axis, _value in rows):
        rows.extend(_merch_sku_size_rows(obj))
    if not any(axis == "size" for _name, axis, _value in rows):
        rows.extend(_positional_numeric_size_rows(obj))
    if not rows:
        rows.extend(_shopify_fallback_rows(obj))
    if "variationType" in obj:
        rows.extend(_option_rows_from_value("variation", [obj]))
    return rows


def _merch_sku_size_rows(obj: dict) -> list[tuple[str, str, object]]:
    if not any(
        _scalar_value(obj.get(key)) not in (None, "", [], {})
        for key in variant_policy.VARIANT_MERCH_SKU_ID_KEYS
    ):
        return []
    for key in variant_policy.VARIANT_MERCH_SKU_SIZE_KEYS:
        value = _scalar_value(obj.get(key))
        if value not in (None, "", [], {}):
            return [(key, "size", value)]
    return []


def _shopify_fallback_rows(obj: dict) -> list[tuple[str, str, object]]:
    for key in variant_policy.VARIANT_SHOPIFY_SIZE_KEYS:
        value = _scalar_value(obj.get(key))
        text = str(value or "").strip()
        if text:
            axis = (
                "size"
                if re.fullmatch(
                    variant_policy.VARIANT_SIZE_LIKE_PATTERN,
                    text,
                    flags=re.IGNORECASE,
                )
                else "style"
            )
            return [(key, axis, value)]
    return []


def _positional_numeric_size_rows(obj: dict) -> list[tuple[str, str, object]]:
    for key in variant_policy.VARIANT_POSITIONAL_OPTION_KEYS:
        value = _scalar_value(obj.get(key))
        text = str(value or "").strip()
        if not text or text.count(".") > 1 or not text.replace(".", "", 1).isdigit():
            continue
        numeric = float(text)
        if (
            variant_policy.VARIANT_POSITIONAL_NUMERIC_SIZE_MIN
            <= numeric
            <= variant_policy.VARIANT_POSITIONAL_NUMERIC_SIZE_MAX
        ):
            return [(key, "size", value)]
    return []


def _has_only_opaque_numeric_options(obj: dict) -> bool:
    rows = [
        (axis, str(_scalar_value(value) or "").strip())
        for _name, axis, value in _raw_variant_options(obj)
        if str(_scalar_value(value) or "").strip()
    ]
    return len(rows) >= 2 and all(
        variant_option_value_is_opaque_numeric(axis, value) for axis, value in rows
    )


def _option_rows_from_value(
    prefix: str, value: object
) -> list[tuple[str, str, object]]:
    if isinstance(value, dict):
        rows: list[tuple[str, str, object]] = []
        for raw_axis, raw_value in value.items():
            axis = _canonical_axis(raw_axis)
            option_value = _scalar_value(raw_value)
            if axis and option_value not in (None, "", [], {}):
                rows.append((f"{prefix}/{raw_axis}", axis, option_value))
        return rows
    if isinstance(value, list):
        rows = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            raw_axis = _first(item, *variant_policy.VARIANT_OPTION_AXIS_KEYS)
            axis = _canonical_axis(raw_axis)
            option_value = _first(item, *variant_policy.VARIANT_OPTION_VALUE_KEYS)
            if axis and option_value not in (None, "", [], {}):
                rows.append((f"{prefix}/{index}", axis, _scalar_value(option_value)))
        return rows
    return []


def _dedupe_options(
    rows: list[tuple[str, str, object]],
) -> list[tuple[str, str, object]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, object]] = []
    for name, axis, value in rows:
        key = (axis, str(value).strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append((name, axis, value))
    return out
