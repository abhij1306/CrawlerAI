"""Slice 4.3: Tier 0 structured floor for listing — no LLM.

Joins deterministic structured sources (JSON-LD ``Product``/``ItemList`` today;
microdata / network JSON later) to the record boundaries discovered by
``listing_records`` using **url-identity**. When every discovered record grounds
(title + url traceable to a structured source), the listing is fully resolved
with **zero LLM invocations** — the HTTP-simple / clean-structured-data fast
path. Partial grounding returns ``None`` so the caller falls through to the
generalized exemplar-LLM tier (Slice 4.4).

No selectors and no per-site branches: the only site-specific input is the page
URL used to absolutize relative hrefs. Every emitted field carries a
``json_pointer`` locator back to the structured value it came from, so the
grounding gate is mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urljoin

from app.core.config.extraction_recipes import ECOMMERCE_LISTING_HTML_ARTIFACT_IDS
from app.core.shared.ids import stable_id
from app.extraction.collectors._helpers import (
    evidence,
    loads_jsonish,
    text_value,
)
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    Evidence,
    EntityHint,
    SourceLocator,
)
from app.extraction.documents import HtmlDocument
from app.extraction.listing_records import (
    RecordBoundary,
    _link_identity,
    discover_listing_records,
)
from app.extraction.surfaces import Surface

_ID_KEY = "@" + "id"
_STRUCTURED_CONFIDENCE = 0.9


@dataclass(frozen=True)
class _Field:
    """One grounded field with a pointer back to its structured source value."""

    fact_type: str
    value: str
    pointer: str


@dataclass(frozen=True)
class _Product:
    """A structured product record keyed by its url-identity."""

    identity: str
    url: str
    fields: tuple[_Field, ...]


def collect_structured_listing(
    bundle: CaptureBundle, reader: ArtifactReader
) -> list[Evidence]:
    """Return Tier-0 listing evidence, or ``[]`` when the floor does not hold.

    The floor holds only when **every** discovered record grounds to a
    structured source. An empty result signals the harvest path to fall back to
    the generalized tier. Emitting rows for a partial join would publish a
    truncated listing (only the structured subset), so partial is treated as
    no-floor on purpose.
    """
    for artifact_id in ECOMMERCE_LISTING_HTML_ARTIFACT_IDS:
        if not reader.exists(artifact_id):
            continue
        doc = reader.document_store.html(artifact_id)
        rows = _structured_evidence(bundle, doc, page_url=bundle.final_url)
        if rows is not None:
            return rows
    return []


def _structured_evidence(
    bundle: CaptureBundle, doc: HtmlDocument, *, page_url: str
) -> list[Evidence] | None:
    boundaries = discover_listing_records(doc, page_url=page_url)
    if not boundaries:
        return None
    grounded = ground_boundaries(doc, boundaries, page_url=page_url)
    if grounded is None:
        return None
    rows: list[Evidence] = []
    for boundary, product in grounded:
        subject_id = stable_id(
            "subject", bundle.bundle_id, doc.artifact_id, "product", boundary.index
        )
        for field in product.fields:
            rows.append(_structured_row(bundle, doc.artifact_id, subject_id, field))
    return rows


def ground_boundaries(
    doc: HtmlDocument,
    boundaries: tuple[RecordBoundary, ...],
    *,
    page_url: str,
) -> list[tuple[RecordBoundary, _Product]] | None:
    """Join discovered boundaries to structured products by url-identity.

    Returns the ``(boundary, product)`` pairs in record order when **all**
    boundaries ground, else ``None``. The join key is the same casefolded
    host+path identity the discovery module assigns, so a DOM anchor and a
    JSON-LD ``ItemList`` url for the same product collapse to one record.
    """
    products: dict[str, _Product] = {}
    for product in _jsonld_products(doc, page_url=page_url):
        products.setdefault(product.identity, product)  # first (document order) wins
    if not products:
        return None
    grounded: list[tuple[RecordBoundary, _Product]] = []
    for boundary in boundaries:
        matched = products.get(boundary.identity)
        if matched is None:
            return None
        grounded.append((boundary, matched))
    return grounded


# --- JSON-LD structured source ------------------------------------------------


def _jsonld_products(doc: HtmlDocument, *, page_url: str) -> list[_Product]:
    out: list[_Product] = []
    for index, tag in enumerate(doc.css('script[type*="ld+json"]')):
        data = loads_jsonish(tag.text())
        if data is None:
            continue
        _scan(
            data, list_url=None, pointer=f"jsonld:{index}", page_url=page_url, out=out
        )
    return out


def _scan(
    value: Any,
    *,
    list_url: str | None,
    pointer: str,
    page_url: str,
    out: list[_Product],
) -> None:
    if isinstance(value, dict):
        types = _types(value)
        # A schema.org ``ListItem`` carries the canonical url for the Product it
        # wraps; propagate it down so a Product lacking its own url still grounds.
        child_url = list_url
        if "ListItem" in types:
            candidate = value.get("url")
            if isinstance(candidate, str) and candidate.strip():
                child_url = candidate
        if "Product" in types and value.get("name"):
            product = _product_record(value, child_url, pointer, page_url=page_url)
            if product is not None:
                out.append(product)
        for key, child in value.items():
            _scan(
                child,
                list_url=child_url,
                pointer=f"{pointer}/{key}",
                page_url=page_url,
                out=out,
            )
    elif isinstance(value, list):
        for i, child in enumerate(value):
            _scan(
                child,
                list_url=list_url,
                pointer=f"{pointer}/{i}",
                page_url=page_url,
                out=out,
            )


def _product_record(
    obj: dict[str, Any], list_url: str | None, pointer: str, *, page_url: str
) -> _Product | None:
    name = text_value(obj.get("name"))
    if not name:
        return None
    raw_url = _product_url(obj) or list_url
    if not raw_url:
        return None
    absolute_url = urljoin(page_url, raw_url.strip())
    identity = _link_identity(absolute_url)
    if not identity:
        return None
    fields: list[_Field] = [
        _Field("product.title", name, f"{pointer}/name"),
        _Field("product.url", absolute_url, f"{pointer}/url"),
    ]
    price, price_pointer = _offer_price(obj, pointer)
    if price:
        fields.append(_Field("offer.price", price, price_pointer))
    image, image_pointer = _first_image(obj, pointer)
    if image:
        fields.append(
            _Field("asset.image_url", urljoin(page_url, image), image_pointer)
        )
    return _Product(identity=identity, url=absolute_url, fields=tuple(fields))


def _product_url(obj: dict[str, Any]) -> str:
    direct = obj.get("url")
    if isinstance(direct, str) and direct.strip():
        return direct
    for offer in _offers(obj):
        offer_url = offer.get("url")
        if isinstance(offer_url, str) and offer_url.strip():
            return offer_url
    identifier = obj.get(_ID_KEY)
    if isinstance(identifier, str) and identifier.strip():
        return identifier.split("#", 1)[0]
    return ""


def _offer_price(obj: dict[str, Any], pointer: str) -> tuple[str, str]:
    for index, offer in enumerate(_offers(obj)):
        for key in ("price", "lowPrice"):
            price = text_value(offer.get(key))
            if price:
                suffix = (
                    "offers"
                    if isinstance(obj.get("offers"), dict)
                    else f"offers/{index}"
                )
                return price, f"{pointer}/{suffix}/{key}"
    return "", ""


def _first_image(obj: dict[str, Any], pointer: str) -> tuple[str, str]:
    image = obj.get("image")
    if isinstance(image, str) and image.strip():
        return image.strip(), f"{pointer}/image"
    if isinstance(image, list):
        for i, item in enumerate(image):
            if isinstance(item, str) and item.strip():
                return item.strip(), f"{pointer}/image/{i}"
            if isinstance(item, dict):
                url = item.get("url") or item.get("contentUrl")
                if isinstance(url, str) and url.strip():
                    return url.strip(), f"{pointer}/image/{i}/url"
    if isinstance(image, dict):
        url = image.get("url") or image.get("contentUrl")
        if isinstance(url, str) and url.strip():
            return url.strip(), f"{pointer}/image/url"
    return "", ""


def _offers(obj: dict[str, Any]) -> list[dict[str, Any]]:
    offers = obj.get("offers")
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [o for o in offers if isinstance(o, dict)]
    return []


def _types(obj: dict[str, Any]) -> tuple[str, ...]:
    raw = obj.get("@type")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if item)
    return ()


# --- evidence -----------------------------------------------------------------


def _structured_row(
    bundle: CaptureBundle, artifact_id: str, subject_id: str, field: _Field
) -> Evidence:
    entity_type: Literal["offer", "asset", "product"] = (
        "offer"
        if field.fact_type.startswith("offer.")
        else "asset"
        if field.fact_type.startswith("asset.")
        else "product"
    )
    locator = SourceLocator(
        kind="json_pointer", value=field.pointer, preview=str(field.value)[:120]
    )
    row = evidence(
        bundle,
        artifact_id,
        "listing_structured_floor",
        field.fact_type,
        field.value,
        locator,
        group_id=subject_id,
        hint=EntityHint(entity_type=entity_type),
        confidence=_STRUCTURED_CONFIDENCE,
    )
    return row.model_copy(
        update={
            "surface": Surface.ECOMMERCE_LISTING,
            "subject_id": subject_id,
            "parent_subject_id": None,
            "directness": "direct",
        }
    )
