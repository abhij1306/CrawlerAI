# Bullhorn public job board adapter.
from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from app.services.adapters.base import AdapterResult, BaseAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.shared.field_coerce import clean_text

HTML_PARSER = "html.parser"
_API_BASE_RE = re.compile(
    r"https://public-rest\d+\.bullhornstaffing\.com/rest-services/[^\"'\s]+/query/JobBoardPost",
    re.I,
)
_WHERE_RE = re.compile(
    r"where=\((.*?)\)&fields=|where=\s*['\"]([^'\"]+)['\"]",
    re.I | re.S,
)
_FIELDS = (
    "id,title,publishedCategory(id,name),address(city,state),"
    "employmentType,dateLastPublished,publicDescription"
)


class BullhornAdapter(BaseAdapter):
    name = "bullhorn"
    platform_family = "bullhorn"
    job_surface_only = True

    async def can_handle(self, url: str, html: str) -> bool:
        return self._matches_platform_family(url, html) or bool(self._discover_api_base(html))

    async def extract(
        self,
        url: str,
        html: str,
        surface: str,
        proxy: str | None = None,
    ) -> AdapterResult:
        if not self._is_job_surface(surface):
            return self._result([])
        records = await self._extract_listing(url, html, proxy=proxy)
        return self._result(records)

    async def _extract_listing(
        self,
        page_url: str,
        html: str,
        *,
        proxy: str | None,
    ) -> list[dict]:
        api_base = self._discover_api_base(html)
        if not api_base:
            return []
        records: list[dict] = []
        seen_ids: set[str] = set()
        where_clause = self._discover_where_clause(html)
        for offset in range(
            0,
            adapter_runtime_settings.bullhorn_max_offset,
            adapter_runtime_settings.bullhorn_page_size,
        ):
            payload = await self._request_json(
                self._build_query_url(api_base, where_clause, offset),
                proxy=proxy,
                timeout_seconds=adapter_runtime_settings.bullhorn_request_timeout_seconds,
            )
            if not isinstance(payload, dict):
                break
            rows = payload.get("data")
            if not isinstance(rows, list) or not rows:
                break
            for item in rows:
                if not isinstance(item, dict):
                    continue
                record = self._record_from_item(item, page_url=page_url)
                job_id = str(record.get("job_id") or "").strip()
                if not record or not job_id or job_id in seen_ids:
                    continue
                seen_ids.add(job_id)
                records.append(record)
            if len(rows) < adapter_runtime_settings.bullhorn_page_size:
                break
        return records

    def _discover_api_base(self, html: str) -> str:
        match = _API_BASE_RE.search(str(html or ""))
        return match.group(0) if match else ""

    def _discover_where_clause(self, html: str) -> str:
        text = str(html or "")
        match = _WHERE_RE.search(text)
        if not match:
            return "(isOpen=true) AND (isDeleted=false)"
        raw = next((group for group in match.groups() if group), "")
        cleaned = unescape(str(raw or "").strip())
        cleaned = cleaned.replace("%27", "'")
        if cleaned and match.group(1):
            cleaned = f"({cleaned})"
        return cleaned or "(isOpen=true) AND (isDeleted=false)"

    def _build_query_url(self, api_base: str, where_clause: str, offset: int) -> str:
        query = urlencode(
            {
                "where": where_clause,
                "fields": _FIELDS,
                "count": str(adapter_runtime_settings.bullhorn_page_size),
                "start": str(offset),
                "orderBy": "-dateLastPublished",
            }
        )
        return f"{api_base}?{query}"

    def _record_from_item(self, item: dict, *, page_url: str) -> dict:
        title = clean_text(item.get("title"))
        job_id = clean_text(item.get("id"))
        if not title or not job_id:
            return {}
        record = {
            "title": title,
            "job_id": job_id,
            "url": self._job_url(page_url, job_id),
            "apply_url": self._job_url(page_url, job_id),
            "source_url": page_url,
        }
        address = item.get("address")
        if isinstance(address, dict):
            location = clean_text(
                ", ".join(
                    value
                    for value in (
                        str(address.get("city") or "").strip(),
                        str(address.get("state") or "").strip(),
                    )
                    if value
                )
            )
            if location:
                record["location"] = location
        category = item.get("publishedCategory")
        if isinstance(category, dict):
            department = clean_text(category.get("name"))
            if department:
                record["department"] = department
        job_type = clean_text(item.get("employmentType"))
        if job_type:
            record["job_type"] = job_type
        posted_date = self._format_timestamp(item.get("dateLastPublished"))
        if posted_date:
            record["posted_date"] = posted_date
        description = self._clean_description(item.get("publicDescription"))
        if description:
            record["description"] = description
        return record

    def _job_url(self, page_url: str, job_id: str) -> str:
        parsed = urlparse(page_url)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        params["jobId"] = job_id
        return urlunparse(parsed._replace(query=urlencode(params), fragment=job_id))

    def _format_timestamp(self, value: object) -> str:
        try:
            timestamp = int(str(value)) / 1000
        except (TypeError, ValueError):
            return ""
        return datetime.fromtimestamp(timestamp, UTC).date().isoformat()

    def _clean_description(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        return clean_text(BeautifulSoup(raw, HTML_PARSER).get_text(" ", strip=True))
