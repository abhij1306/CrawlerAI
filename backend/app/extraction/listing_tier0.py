"""Universal deterministic structured floor for schema-backed listings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urljoin, urlparse

from app.core.config.cascade import (
    CASCADE_DOM_LISTING_CONFIDENCE,
    CASCADE_STRUCTURED_LISTING_CONFIDENCE,
)
from app.core.config.extraction_recipes import LISTING_HTML_ARTIFACT_IDS
from app.core.shared.ids import stable_id
from app.extraction.collectors._helpers import evidence, loads_jsonish, text_value
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
    RecordSignal,
    _link_identity,
    _schema_wants_visual_signal,
    discover_listing_records,
    record_key_attributes_for_schema,
    record_signal_for_schema,
)
from app.extraction.listing import collect_ecommerce_listing
from app.extraction.jobs import collect_job_listing
from app.extraction.surfaces import ListingSchema, Surface, listing_schema
from app.core.config.extraction_rules import (
    JOB_LISTING_DETAIL_ROOT_MARKERS,
    JOB_LISTING_HUB_TERMINAL_SUFFIXES,
    JOB_LISTING_HUB_TITLE_PREFIXES,
    JOB_LISTING_HUB_TITLE_SUFFIXES,
    JOB_POSTING_PATH_MARKERS,
)

_ID_KEY = "@" + "id"
_STRUCTURED_CONFIDENCE = CASCADE_STRUCTURED_LISTING_CONFIDENCE
_DOM_FLOOR_CONFIDENCE = CASCADE_DOM_LISTING_CONFIDENCE


@dataclass(frozen=True)
class _Field:
    fact_type: str
    value: str
    pointer: str


@dataclass(frozen=True)
class _StructuredRecord:
    identity: str
    url: str
    fields: tuple[_Field, ...]


def collect_structured_listing(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    surface: Surface,
) -> list[Evidence]:
    """Return only a fully-grounded structured listing; never invoke a model."""
    schema = listing_schema(surface)
    if schema is None:
        return []
    for artifact_id in LISTING_HTML_ARTIFACT_IDS:
        if not reader.exists(artifact_id):
            continue
        doc = reader.document_store.html(artifact_id)
        rows = _structured_evidence(
            bundle, doc, page_url=bundle.final_url, schema=schema
        )
        if rows is not None:
            return rows
    return []


def collect_dom_listing(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    surface: Surface,
) -> list[Evidence]:
    """DOM floor — the weakest deterministic listing signal.

    Keeps only repeated record boundaries with a record-local title and the
    boundary URL; it never promotes one-off navigation or footer links into a
    listing. The tier *ordering* (this floor runs last, after structured and
    network) is owned by ``app.extraction.cascade``, not by this module.
    """
    # The DOM floor selects its record-mapper from the ``ListingSchema`` lens,
    # not from a ``surface ==`` identity check: a schema whose record signals are
    # *visual* (image/price — commerce) reuses the legacy card collector, which
    # owns the full admissibility contract (single-record listings, badge
    # skipping, utility-label rejection, market-locale URL restore). A non-visual
    # schema (jobs) uses the schema-driven generic discovery so JS-rendered
    # boards are covered with no image/price requirement. The cascade seam
    # (app.extraction.cascade) stays branch-free; this capability switch is owned
    # by the DOM-floor module.
    schema = listing_schema(surface)
    if schema is None:
        return []
    if _schema_wants_visual_signal(schema):
        # Commerce defers its DOM floor entirely to the legacy card collector.
        # Returning its result verbatim keeps behaviour identical to the legacy
        # ``_harvest_listing`` path when no structured / network source exists.
        return list(collect_ecommerce_listing(bundle, reader))
    return _schema_dom_listing(bundle, reader, schema=schema)


def _schema_dom_listing(
    bundle: CaptureBundle,
    reader: ArtifactReader,
    *,
    schema: ListingSchema,
) -> list[Evidence]:
    """Generic, schema-driven DOM floor for non-visual (job) listings.

    Runs the selector-free ``discover_listing_records`` with the schema's record
    signal / off-host allowance / record-key attributes across the shared HTML
    artifact set (so a JS-rendered board is covered), emitting title + url
    evidence per record. When the repetition-gated generic floor finds nothing
    (a single-posting board, or a shape only the legacy CSS cards match), it
    falls back to the legacy ``collect_job_listing`` collector so behaviour is at
    least as strong as today's path.
    """
    record_signal = record_signal_for_schema(schema)
    key_attributes = record_key_attributes_for_schema(schema)
    for artifact_id in LISTING_HTML_ARTIFACT_IDS:
        if not reader.exists(artifact_id):
            continue
        doc = reader.document_store.html(artifact_id)
        rows = _dom_floor_evidence(
            bundle,
            doc,
            page_url=bundle.final_url,
            schema=schema,
            record_signal=record_signal,
            key_attributes=key_attributes,
        )
        if rows:
            return rows
    return list(collect_job_listing(bundle, reader))


def _is_hub_or_nav_title(title: str, url: str) -> bool:
    """True when a candidate is a listing-of-listings hub or nav link, not a job.

    Rejects category/hub chips ("Remote Jobs", "Engineering Careers") and hub
    URLs (``/engineering-jobs``, ``/careers``) so the job floor keeps only real
    postings. A URL carrying a positive posting-path marker (``/careers/123``,
    ``/positions/123``) is always a real posting and is never rejected. All
    markers are config tables (``app.core.config.extraction_rules``), never
    inline literals.
    """
    normalized = " ".join(str(title or "").split()).casefold()
    path = urlparse(url).path.casefold().rstrip("/")
    terminal = path.rsplit("/", 1)[-1] if path else ""
    # Positive posting-path markers win outright: a real posting URL is a job.
    if any(marker in f"{path}/" for marker in JOB_POSTING_PATH_MARKERS):
        return False
    if normalized.endswith(JOB_LISTING_HUB_TITLE_SUFFIXES):
        return True
    if normalized.startswith(JOB_LISTING_HUB_TITLE_PREFIXES) and (
        len(re.findall(r"\w+", normalized)) <= 3
    ):
        return True
    if terminal.endswith(JOB_LISTING_HUB_TERMINAL_SUFFIXES):
        return True
    return bool(terminal) and terminal in JOB_LISTING_DETAIL_ROOT_MARKERS


def _dom_floor_evidence(
    bundle: CaptureBundle,
    doc: HtmlDocument,
    *,
    page_url: str,
    schema: ListingSchema,
    record_signal: RecordSignal | None = None,
    key_attributes: tuple[str, ...] = (),
) -> list[Evidence]:
    boundaries = discover_listing_records(
        doc,
        page_url=page_url,
        record_signal=record_signal,
        off_host_allowed=schema.off_host_records_allowed,
        record_key_attributes=key_attributes,
    )
    if not boundaries:
        return []
    rows: list[Evidence] = []
    for boundary in boundaries:
        title, path = _boundary_title(boundary, page_url=page_url)
        if not title or _is_hub_or_nav_title(title, boundary.url):
            return []
        subject_id = stable_id(
            "subject",
            bundle.bundle_id,
            doc.artifact_id,
            schema.root_entity,
            boundary.index,
        )
        rows.append(
            _dom_row(
                bundle,
                doc.artifact_id,
                subject_id,
                schema.title_fact,
                title,
                path,
                schema=schema,
                url=boundary.url,
            )
        )
        # Anchor-less JS-onclick cards carry no detail URL; emit the url fact
        # only when the boundary resolved to a real link (anchor grids).
        if boundary.url:
            rows.append(
                _dom_row(
                    bundle,
                    doc.artifact_id,
                    subject_id,
                    schema.url_fact,
                    boundary.url,
                    boundary.node.dom_path(),
                    schema=schema,
                    url=boundary.url,
                )
            )
    return rows


def _boundary_title(boundary: RecordBoundary, *, page_url: str) -> tuple[str, str]:
    for anchor in boundary.node.css("a[href]"):
        href = str(anchor.attribute("href") or "").strip()
        if not href or _link_identity(urljoin(page_url, href)) != boundary.identity:
            continue
        value = text_value(anchor.attribute("title") or anchor.content_text())
        if value and len(value) >= 2:
            return value, anchor.dom_path()
    # Anchor-less (JS-onclick) card: no matching detail ``<a href>`` inside the
    # record, so the title comes from the most prominent heading text in the
    # record subtree. Runs whenever the anchor scan produced nothing (an
    # anchor-less card still carries a recovered detail URL on the boundary).
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        heading = boundary.node.css_first(tag)
        if heading is not None:
            value = text_value(heading.content_text())
            if value and len(value) >= 2:
                return value, heading.dom_path()
    return "", ""


def _dom_row(
    bundle: CaptureBundle,
    artifact_id: str,
    subject_id: str,
    fact_type: str,
    value: str,
    path: str,
    *,
    schema: ListingSchema,
    url: str,
) -> Evidence:
    return Evidence(
        evidence_id=stable_id(
            "ev",
            bundle.bundle_id,
            artifact_id,
            "listing_dom_floor",
            fact_type,
            subject_id,
        ),
        bundle_id=bundle.bundle_id,
        artifact_id=artifact_id,
        collector_id="listing_dom_floor",
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="dom_path", value=path, preview=value[:120]),
        entity_hint=EntityHint(
            entity_type=cast(Any, schema.entity_type_for(fact_type)), url=url
        ),
        group_id=subject_id,
        directness="direct",
        confidence=_DOM_FLOOR_CONFIDENCE,
        surface=schema.surface,
        subject_id=subject_id,
        subject_scope=cast(Any, schema.entity_type_for(fact_type)),
    )


def _structured_evidence(
    bundle: CaptureBundle, doc: HtmlDocument, *, page_url: str, schema: ListingSchema
) -> list[Evidence] | None:
    # A singleton is admissible only on this structured path. The JSON-LD or
    # microdata join must corroborate the same boundary; DOM-only discovery
    # remains repetition-gated. Discovery runs through the SAME schema-driven
    # seam as the DOM floor so a job listing's non-visual record signal,
    # off-host allowance, and record-key attributes apply here too (a lone
    # off-host Lever anchor corroborated by JobPosting JSON-LD must ground).
    boundaries = discover_listing_records(
        doc,
        page_url=page_url,
        allow_singleton=True,
        record_signal=record_signal_for_schema(schema),
        off_host_allowed=schema.off_host_records_allowed,
        record_key_attributes=record_key_attributes_for_schema(schema),
    )
    if not boundaries:
        return None
    grounded = ground_boundaries(
        doc, boundaries, page_url=page_url, surface=schema.surface
    )
    if grounded is None:
        return None
    rows: list[Evidence] = []
    for boundary, record in grounded:
        subject_id = stable_id(
            "subject",
            bundle.bundle_id,
            doc.artifact_id,
            schema.root_entity,
            boundary.index,
        )
        rows.extend(
            _structured_row(bundle, doc.artifact_id, subject_id, field, schema=schema)
            for field in record.fields
        )
    return rows


def ground_boundaries(
    doc: HtmlDocument,
    boundaries: tuple[RecordBoundary, ...],
    *,
    page_url: str,
    surface: Surface,
) -> list[tuple[RecordBoundary, _StructuredRecord]] | None:
    """URL-identity join. Partial coverage deliberately fails the whole floor."""
    schema = listing_schema(surface)
    if schema is None:
        return None
    records = {
        record.identity: record
        for record in _jsonld_records(doc, page_url=page_url, schema=schema)
    }
    if not records:
        return None
    grounded: list[tuple[RecordBoundary, _StructuredRecord]] = []
    for boundary in boundaries:
        record = records.get(boundary.identity)
        if record is None:
            return None
        grounded.append((boundary, record))
    return grounded


def _jsonld_records(
    doc: HtmlDocument, *, page_url: str, schema: ListingSchema
) -> list[_StructuredRecord]:
    out: list[_StructuredRecord] = []
    for index, tag in enumerate(doc.css('script[type*="ld+json"]')):
        data = loads_jsonish(tag.text())
        if data is not None:
            _scan(
                data,
                list_url=None,
                pointer=f"jsonld:{index}",
                page_url=page_url,
                schema=schema,
                out=out,
            )
    return out


def _scan(
    value: Any,
    *,
    list_url: str | None,
    pointer: str,
    page_url: str,
    schema: ListingSchema,
    out: list[_StructuredRecord],
) -> None:
    if isinstance(value, dict):
        types = _types(value)
        child_url = list_url
        if "ListItem" in types:
            candidate = value.get("url")
            if isinstance(candidate, str) and candidate.strip():
                child_url = candidate
        if schema.structured_types.intersection(types):
            record = _structured_record(
                value, child_url, pointer, page_url=page_url, schema=schema
            )
            if record is not None:
                out.append(record)
        for key, child in value.items():
            _scan(
                child,
                list_url=child_url,
                pointer=f"{pointer}/{key}",
                page_url=page_url,
                schema=schema,
                out=out,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan(
                child,
                list_url=list_url,
                pointer=f"{pointer}/{index}",
                page_url=page_url,
                schema=schema,
                out=out,
            )


def _structured_record(
    obj: dict[str, Any],
    list_url: str | None,
    pointer: str,
    *,
    page_url: str,
    schema: ListingSchema,
) -> _StructuredRecord | None:
    fields = _structured_fields(
        obj, list_url, pointer, page_url=page_url, schema=schema
    )
    values = {field.fact_type: field.value for field in fields}
    raw_url = values.get(schema.url_fact, "")
    if not values.get(schema.title_fact) or not raw_url:
        return None
    identity = _link_identity(raw_url)
    if not identity:
        return None
    return _StructuredRecord(identity=identity, url=raw_url, fields=tuple(fields))


def _structured_fields(
    obj: dict[str, Any],
    list_url: str | None,
    pointer: str,
    *,
    page_url: str,
    schema: ListingSchema,
) -> list[_Field]:
    fields: list[_Field] = []
    for fact_type, kind in schema.structured_fact_kinds:
        value, suffix = _value_for_kind(obj, kind, list_url=list_url, page_url=page_url)
        if value:
            fields.append(_Field(fact_type, value, f"{pointer}/{suffix}"))
    return fields


def _value_for_kind(
    obj: dict[str, Any], kind: str, *, list_url: str | None, page_url: str
) -> tuple[str, str]:
    if kind == "name_or_title":
        for key in ("name", "title"):
            if value := text_value(obj.get(key)):
                return value, key
    elif kind == "url":
        raw_url, suffix = _record_url(obj, list_url)
        return (urljoin(page_url, raw_url.strip()), suffix) if raw_url else ("", "")
    elif kind == "offer_price":
        for index, offer in enumerate(_offers(obj)):
            for key in ("price", "lowPrice"):
                if value := text_value(offer.get(key)):
                    suffix = (
                        "offers"
                        if isinstance(obj.get("offers"), dict)
                        else f"offers/{index}"
                    )
                    return value, f"{suffix}/{key}"
    elif kind == "image":
        value, suffix = _first_image(obj)
        return (urljoin(page_url, value), suffix) if value else ("", "")
    elif kind == "organization":
        value = _organization(obj.get("hiringOrganization"))
        return (value, "hiringOrganization") if value else ("", "")
    elif kind == "location":
        value = _location(obj.get("jobLocation"))
        return (value, "jobLocation") if value else ("", "")
    return "", ""


def _record_url(obj: dict[str, Any], list_url: str | None) -> tuple[str, str]:
    direct = obj.get("url")
    if isinstance(direct, str) and direct.strip():
        return direct, "url"
    for index, offer in enumerate(_offers(obj)):
        value = offer.get("url")
        if isinstance(value, str) and value.strip():
            suffix = (
                "offers/url"
                if isinstance(obj.get("offers"), dict)
                else f"offers/{index}/url"
            )
            return value, suffix
    identifier = obj.get(_ID_KEY)
    if isinstance(identifier, str) and identifier.strip():
        return identifier.split("#", 1)[0], _ID_KEY
    return (list_url or ""), "url"


def _offers(obj: dict[str, Any]) -> list[dict[str, Any]]:
    value = obj.get("offers")
    return (
        [value]
        if isinstance(value, dict)
        else [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _first_image(obj: dict[str, Any]) -> tuple[str, str]:
    image = obj.get("image")
    if isinstance(image, str) and image.strip():
        return image.strip(), "image"
    values = image if isinstance(image, list) else [image]
    for index, item in enumerate(values):
        if isinstance(item, dict):
            value = item.get("url") or item.get("contentUrl")
            if isinstance(value, str) and value.strip():
                return value.strip(), f"image/{index}/url" if isinstance(
                    image, list
                ) else "image/url"
    return "", ""


def _organization(value: object) -> str:
    return (
        text_value(value.get("name")) if isinstance(value, dict) else text_value(value)
    )


def _location(value: object) -> str:
    rows = value if isinstance(value, list) else [value]
    parts: list[str] = []
    for row in rows:
        address = row.get("address") if isinstance(row, dict) else row
        if isinstance(address, dict):
            parts.extend(
                text_value(address.get(key))
                for key in ("addressLocality", "addressRegion", "addressCountry")
            )
        elif item := text_value(address):
            parts.append(item)
    return ", ".join(dict.fromkeys(part for part in parts if part))


def _types(obj: dict[str, Any]) -> frozenset[str]:
    raw = obj.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return frozenset(str(value) for value in values if value)


def _structured_row(
    bundle: CaptureBundle,
    artifact_id: str,
    subject_id: str,
    field: _Field,
    *,
    schema: ListingSchema,
) -> Evidence:
    entity_type = schema.entity_type_for(field.fact_type)
    row = evidence(
        bundle,
        artifact_id,
        "listing_structured_floor",
        field.fact_type,
        field.value,
        SourceLocator(
            kind="json_pointer", value=field.pointer, preview=field.value[:120]
        ),
        group_id=subject_id,
        hint=EntityHint(entity_type=cast(Any, entity_type)),
        confidence=_STRUCTURED_CONFIDENCE,
    )
    return row.model_copy(
        update={
            "surface": schema.surface,
            "subject_id": subject_id,
            "parent_subject_id": None,
            "directness": "direct",
        }
    )
