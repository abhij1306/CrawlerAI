"""Schema-driven materialization of repeated records in network responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import parse_qsl, urljoin, urlsplit

from app.core.shared.ids import stable_id
from app.extraction.collectors._helpers import evidence, text_value
from app.extraction.contracts import (
    ArtifactReader,
    CaptureBundle,
    EntityHint,
    Evidence,
    SourceLocator,
)
from app.extraction.json_walk import walk_json
from app.extraction.surfaces import ListingSchema, Surface, listing_schema

_CONFIDENCE = 0.86
_MIN_ROWS = 2
_URL_TEMPLATE_RE = re.compile(r"(?:https?://|/)[^\"'\s<>]+[?&][^\"'\s<>]*")
_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def collect_network_listing(
    bundle: CaptureBundle, reader: ArtifactReader, *, surface: Surface
) -> list[Evidence]:
    """Materialize the strongest repeated JSON row group without site rules.

    A candidate needs ≥2 members from one array, each with the schema's title
    and a same-site detail URL, rejecting singletons and response metadata.
    """
    schema = listing_schema(surface)
    if schema is None:
        return []
    detail_urls = _detail_urls_by_identity(bundle, reader)
    detail_url_templates = _detail_url_templates(bundle, reader)
    candidates: list[tuple[str, str, list[dict[str, str]]]] = []
    for ref in bundle.artifacts:
        if ref.artifact_type != "network_json":
            continue
        for node in walk_json(reader.read_json(ref)):
            if not isinstance(node.value, list):
                continue
            rows = _rows_from_array(
                node.value,
                page_url=bundle.final_url,
                schema=schema,
                detail_urls=detail_urls,
                detail_url_templates=detail_url_templates,
            )
            if len(rows) >= _MIN_ROWS:
                candidates.append((ref.artifact_id, node.pointer, rows))
    if not candidates:
        return []
    artifact_id, pointer, rows = max(candidates, key=lambda item: len(item[2]))
    return _evidence_rows(bundle, artifact_id, pointer, rows, schema)


def _rows_from_array(
    values: list[Any],
    *,
    page_url: str,
    schema: ListingSchema,
    detail_urls: Mapping[str, str],
    detail_url_templates: tuple[str, ...],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    identities: set[str] = set()
    for value in values:
        if not isinstance(value, Mapping):
            return []
        row = _record_fields(
            value,
            page_url=page_url,
            schema=schema,
            detail_urls=detail_urls,
            detail_url_templates=detail_url_templates,
        )
        title, url = row.get(schema.title_fact, ""), row.get(schema.url_fact, "")
        identity = _url_identity(url)
        if not title or not identity or identity in identities:
            return []
        identities.add(identity)
        rows.append(row)
    return rows


def _record_fields(
    value: Mapping[str, object],
    *,
    page_url: str,
    schema: ListingSchema,
    detail_urls: Mapping[str, str],
    detail_url_templates: tuple[str, ...],
) -> dict[str, str]:
    fields: dict[str, str] = {}
    for fact_type, keys in schema.network_fact_keys:
        raw = _first_value(value, keys)
        text = text_value(raw)
        if not text:
            continue
        if fact_type == schema.url_fact:
            text = urljoin(page_url, text)
            if not _same_host(page_url, text):
                continue
        fields[fact_type] = text
    if schema.url_fact not in fields:
        for key in schema.network_identity_keys:
            identity = text_value(_first_value(value, (key,))).casefold()
            grounded = detail_urls.get(identity) or _detail_url_from_template(
                detail_url_templates, identity=identity
            )
            if grounded:
                fields[schema.url_fact] = grounded
                break
    return fields


def _detail_urls_by_identity(
    bundle: CaptureBundle, reader: ArtifactReader
) -> dict[str, str]:
    """Ground response IDs to page-local detail anchors without CSS rules."""
    links: dict[str, str] = {}
    for ref in bundle.artifacts:
        if ref.artifact_type != "rendered_html":
            continue
        doc = reader.document_store.html(ref.artifact_id)
        for anchor in doc.css("a[href]"):
            url = urljoin(bundle.final_url, str(anchor.attribute("href") or ""))
            if not _same_host(bundle.final_url, url):
                continue
            for identity in _url_identity_parts(url):
                links.setdefault(identity, url)
    return links


def _detail_url_templates(
    bundle: CaptureBundle, reader: ArtifactReader
) -> tuple[str, ...]:
    templates: list[str] = []
    for ref in bundle.artifacts:
        if ref.artifact_type != "rendered_html":
            continue
        for candidate in _URL_TEMPLATE_RE.findall(reader.read_text(ref)):
            url = urljoin(bundle.final_url, candidate)
            if _same_host(bundle.final_url, url) and _has_identifier_placeholder(url):
                templates.append(url)
    return tuple(dict.fromkeys(templates))


def _detail_url_from_template(templates: tuple[str, ...], *, identity: str) -> str:
    for template in templates:
        parsed = urlsplit(template)
        for _, value in parse_qsl(parsed.query, keep_blank_values=True):
            if _is_identifier_placeholder(value):
                return template.replace(value, identity)
    return ""


def _has_identifier_placeholder(url: str) -> bool:
    return any(
        _is_identifier_placeholder(value) for _, value in parse_qsl(urlsplit(url).query)
    )


def _is_identifier_placeholder(value: str) -> bool:
    text = str(value or "").strip()
    return (
        text.casefold() == _ZERO_UUID
        or (text.startswith("{") and text.endswith("}"))
        or (text.startswith(":") and len(text) > 1)
    )


def _url_identity_parts(url: str) -> tuple[str, ...]:
    parsed = urlsplit(url)
    values = [value.casefold() for _, value in parse_qsl(parsed.query) if value]
    values.extend(part.casefold() for part in parsed.path.split("/") if part)
    return tuple(value for value in values if len(value) >= 3)


def _first_value(value: Mapping[str, object], keys: tuple[str, ...]) -> object:
    lowered = {str(key).casefold(): item for key, item in value.items()}
    for key in keys:
        candidate = lowered.get(key.casefold())
        if candidate not in (None, "", [], {}):
            return candidate
    return None


def _same_host(page_url: str, candidate: str) -> bool:
    host = (urlsplit(page_url).hostname or "").casefold()
    return bool(host) and host == (urlsplit(candidate).hostname or "").casefold()


def _url_identity(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/").casefold()
    if not path:
        return ""
    query = "&".join(
        f"{key.casefold()}={item.casefold()}"
        for key, item in sorted(parse_qsl(parsed.query, keep_blank_values=True))
        if key and item
    )
    base = f"{(parsed.hostname or '').casefold()}{path}"
    return f"{base}?{query}" if query else base


def _evidence_rows(
    bundle: CaptureBundle,
    artifact_id: str,
    pointer: str,
    rows: list[dict[str, str]],
    schema: ListingSchema,
) -> list[Evidence]:
    evidence_rows: list[Evidence] = []
    for index, row in enumerate(rows):
        subject_id = stable_id("subject", bundle.bundle_id, artifact_id, pointer, index)
        url = row[schema.url_fact]
        for fact_type, field_value in row.items():
            entity_type = schema.entity_type_for(fact_type)
            evidence_rows.append(
                evidence(
                    bundle,
                    artifact_id,
                    "network_listing_floor",
                    fact_type,
                    field_value,
                    SourceLocator(
                        kind="json_pointer",
                        value=f"{pointer}/{index}",
                        preview=field_value[:120],
                    ),
                    group_id=subject_id,
                    hint=EntityHint(entity_type=cast(Any, entity_type), url=url),
                    confidence=_CONFIDENCE,
                ).model_copy(
                    update={
                        "surface": schema.surface,
                        "subject_id": subject_id,
                        "subject_scope": entity_type,
                        "directness": "direct",
                    }
                )
            )
    return evidence_rows


__all__ = ["collect_network_listing"]
