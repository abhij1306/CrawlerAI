# Public Algolia job-board adapter.
from __future__ import annotations

import re
from urllib.parse import urlencode

from app.services.adapters.base import PublicEndpointAdapter
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.extraction_html_helpers import html_to_text
from app.services.shared.field_coerce import clean_text


_ALGOLIA_APP_ID_RE = re.compile(
    r"algoliaApplicationId\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
)
_ALGOLIA_API_KEY_RE = re.compile(
    r"algoliaApiKey\s*:\s*['\"]([^'\"]+)['\"]", re.IGNORECASE
)
_ALGOLIA_INDEX_RE = re.compile(
    r"algoliaJobsIndex(?:SuperRanked|Closing|Alternative)?\s*:\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


class AlgoliaJobsAdapter(PublicEndpointAdapter):
    name = "algolia_jobs"
    platform_family = "algolia_jobs"
    job_surface_only = True

    async def can_handle(self, url: str, html: str) -> bool:
        del url
        return self._extract_config(html) is not None

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        del url, surface
        config = self._extract_config(html)
        if config is None:
            return []
        app_id, api_key, index_name = config
        endpoint = f"https://{app_id}-dsn.algolia.net/1/indexes/{index_name}/query"
        params = urlencode(
            {
                "hitsPerPage": adapter_runtime_settings.algolia_jobs_hits_per_page,
                "page": 0,
            }
        )
        payload = await self._request_json(
            endpoint,
            method="POST",
            headers={
                "X-Algolia-Application-Id": app_id,
                "X-Algolia-API-Key": api_key,
                "Content-Type": "application/json",
            },
            json_body={"params": params},
            proxy=proxy,
            timeout_seconds=adapter_runtime_settings.ats_request_timeout_seconds,
        )
        if not isinstance(payload, dict):
            return []
        hits = payload.get("hits")
        if not isinstance(hits, list):
            return []
        records = [self._normalize_hit(hit) for hit in hits]
        return [record for record in records if record]

    def _extract_config(self, html: str) -> tuple[str, str, str] | None:
        text = str(html or "")
        app_id = _first_match(_ALGOLIA_APP_ID_RE, text)
        api_key = _first_match(_ALGOLIA_API_KEY_RE, text)
        index_name = _first_match(_ALGOLIA_INDEX_RE, text)
        if not app_id or not api_key or not index_name:
            return None
        return app_id, api_key, index_name

    def _normalize_hit(self, hit: object) -> dict | None:
        if not isinstance(hit, dict):
            return None
        title = clean_text(hit.get("title"))
        url = clean_text(
            hit.get("url_external")
            or hit.get("apply_url")
            or hit.get("url")
            or hit.get("permalink")
        )
        if not title or not url:
            return None
        job_id = clean_text(
            hit.get("objectID")
            or hit.get("post_pk")
            or hit.get("id_external_80_000_hours")
            or hit.get("id")
        )
        company = clean_text(
            hit.get("company_name") or _nested_text(hit.get("company"), "name")
        )
        description = html_to_text(
            clean_text(hit.get("description_short") or hit.get("description"))
        )
        record = {
            "title": title,
            "url": url,
            "apply_url": url,
            "job_id": job_id,
            "company": company,
            "location": _first_list_text(
                hit.get("card_locations")
                or hit.get("tags_city")
                or hit.get("tags_location_80k")
                or hit.get("tags_country")
            ),
            "salary": clean_text(hit.get("salary")),
            "job_type": _first_list_text(hit.get("tags_role_type")),
            "posted_date": clean_text(hit.get("posted_at_relative") or hit.get("posted_at")),
            "department": _first_list_text(hit.get("tags_area")),
            "description": description,
        }
        return {
            key: value
            for key, value in record.items()
            if value not in (None, "", [], {})
        }


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return clean_text(match.group(1)) if match else ""


def _nested_text(value: object, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    return clean_text(value.get(key))


def _first_list_text(value: object) -> str:
    if isinstance(value, list):
        return clean_text(next((item for item in value if clean_text(item)), ""))
    return clean_text(value)
