# Public Firestore job-board adapter.
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.services.adapters.base import PublicEndpointAdapter, adapter_host_matches
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.extraction_html_helpers import html_to_text
from app.services.shared.field_coerce import clean_text


class FirestoreJobsAdapter(PublicEndpointAdapter):
    name = "firestore_jobs"
    platform_family = "firestore_jobs"
    job_surface_only = True

    async def can_handle(self, url: str, html: str) -> bool:
        del html
        host = str(urlsplit(str(url or "")).hostname or "").lower()
        return adapter_host_matches(host, "dynamitejobs.com")

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        del html, surface
        payload = await self._request_json(
            _run_query_url("djplatform"),
            method="POST",
            headers={"Content-Type": "application/json"},
            json_body=_published_jobs_query(adapter_runtime_settings.firestore_jobs_page_size),
            proxy=proxy,
            timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
        )
        if not isinstance(payload, list):
            return []
        records = [self._normalize_document(item, page_url=url) for item in payload]
        return [record for record in records if record]

    def _normalize_document(self, item: object, *, page_url: str) -> dict | None:
        if not isinstance(item, dict):
            return None
        document = item.get("document")
        if not isinstance(document, dict):
            return None
        data = _decode_firestore_value({"mapValue": {"fields": document.get("fields")}})
        if not isinstance(data, dict):
            return None
        title = clean_text(data.get("title"))
        slug = clean_text(data.get("slug"))
        company_raw = data.get("company")
        company = company_raw if isinstance(company_raw, dict) else {}
        company_slug = clean_text(company.get("username") or company.get("usernameLow"))
        if not title or not slug:
            return None
        url = _job_url(page_url=page_url, company_slug=company_slug, job_slug=slug)
        record = {
            "title": title,
            "url": url,
            "apply_url": clean_text(data.get("applyLink")),
            "job_id": _document_id(document.get("name")),
            "company": clean_text(company.get("name")),
            "location": _join_text(data.get("locationSlugs")),
            "job_type": _nested_text(data.get("type"), "name", "display"),
            "posted_date": clean_text(data.get("publishedAt") or data.get("createdAt")),
            "department": _nested_text(data.get("primaryCategory"), "name"),
            "salary": _salary_text(data.get("salary")),
            "description": html_to_text(
                clean_text(data.get("descriptionHTML") or data.get("description"))
            ),
            "image_url": _company_icon_url(company.get("icon")),
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }


def _run_query_url(project_id: str) -> str:
    return (
        "https://firestore.googleapis.com/v1/projects/"
        f"{project_id}/databases/(default)/documents:runQuery"
    )


def _published_jobs_query(limit: int) -> dict[str, object]:
    return {
        "structuredQuery": {
            "from": [{"collectionId": "jobs"}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": "status"},
                    "op": "EQUAL",
                    "value": {"stringValue": "published"},
                }
            },
            "limit": int(limit),
        }
    }


def _decode_firestore_value(value: object) -> Any:
    if not isinstance(value, dict):
        return None
    if "stringValue" in value:
        return value.get("stringValue")
    if "timestampValue" in value:
        return value.get("timestampValue")
    if "booleanValue" in value:
        return value.get("booleanValue")
    for number_key in ("integerValue", "doubleValue"):
        if number_key in value:
            raw = value.get(number_key)
            if raw is None:
                return None
            try:
                return float(raw) if "." in str(raw) else int(str(raw))
            except (TypeError, ValueError):
                return raw
    if "mapValue" in value:
        map_value = value.get("mapValue")
        if not isinstance(map_value, dict):
            return {}
        fields = map_value.get("fields")
        if not isinstance(fields, dict):
            return {}
        return {key: _decode_firestore_value(item) for key, item in fields.items()}
    if "arrayValue" in value:
        array_value = value.get("arrayValue")
        if not isinstance(array_value, dict):
            return []
        values = array_value.get("values")
        if not isinstance(values, list):
            return []
        return [_decode_firestore_value(item) for item in values]
    return None


def _job_url(*, page_url: str, company_slug: str, job_slug: str) -> str:
    parsed = urlsplit(str(page_url or ""))
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    base = origin or "https://dynamitejobs.com"
    if company_slug:
        return f"{base}/company/{company_slug}/remote-job/{job_slug}"
    return f"{base}/remote-job/{job_slug}"


def _document_id(name: object) -> str:
    return clean_text(str(name or "").rstrip("/").rsplit("/", 1)[-1])


def _nested_text(value: object, *keys: str) -> str:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return ""
        current = current.get(key)
    return clean_text(current)


def _join_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value)


def _salary_text(value: object) -> str:
    if not isinstance(value, dict) or value.get("public") is False:
        return ""
    currency = clean_text(value.get("currency"))
    salary_type = clean_text(value.get("type"))
    from_value = value.get("from")
    to_value = value.get("to")
    if from_value in (None, "", [], {}) and to_value in (None, "", [], {}):
        return ""
    amount = (
        f"{_format_number(from_value)} - {_format_number(to_value)}"
        if from_value not in (None, "", [], {}) and to_value not in (None, "", [], {})
        else _format_number(from_value or to_value)
    )
    suffix = f" {salary_type}" if salary_type else ""
    prefix = f"{currency} " if currency else ""
    return clean_text(f"{prefix}{amount}{suffix}")


def _format_number(value: object) -> str:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return clean_text(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _company_icon_url(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    for key in ("mdw", "md", "smw", "sm", "lgw", "lg"):
        url = clean_text(value.get(key))
        if url:
            return url
    return ""
