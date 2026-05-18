from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import urljoin, urlparse, urlunparse
from uuid import uuid4

import httpx
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.ucp_audit import UCPAuditJob, UCPAuditPageResult, UCPAuditReport
from app.models.user import User
from app.services.config import ucp_audit as config
from app.services.domain_utils import normalize_domain
from app.services.exceptions import AcquisitionError
from app.services.network_resolution import build_async_http_client
from app.services.ucp_audit.agent_delta import build_agent_view_delta
from app.services.ucp_audit.catalog_checks import (
    build_metafield_coverage_report,
    build_taxonomy_consistency_report,
)
from app.services.ucp_audit.compliance_checks import (
    build_policy_readability_report,
    build_variant_fidelity_report,
)
from app.services.ucp_audit.discovery import discover_ucp_manifest
from app.services.ucp_audit.product_schema import score_product_schema
from app.services.ucp_audit.reporting import build_markdown_report, build_report_payload
from app.services.ucp_audit.scoring import (
    build_compliance_report,
    dimension_from_agent_delta,
)
from app.services.ucp_audit.types import (
    AgentViewDelta,
    UCPComplianceReport,
    UCPDimensionScore,
    UCPFinding,
    UCPSchemaScore,
)

logger = logging.getLogger(__name__)


async def create_ucp_audit_job(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
) -> UCPAuditJob:
    domain = _normalized_domain(payload.get("domain"))
    options = _normalized_options(payload.get("options"))
    job = UCPAuditJob(
        user_id=user.id,
        domain=domain,
        status=config.UCP_AUDIT_JOB_STATUS_QUEUED,
        options=options,
        summary={
            "page_result_count": 0,
            "overall_score": None,
        },
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def run_ucp_audit_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.scalar(
            select(UCPAuditJob)
            .where(
                UCPAuditJob.id == job_id,
                UCPAuditJob.status == config.UCP_AUDIT_JOB_STATUS_QUEUED,
            )
            .with_for_update(skip_locked=True)
        )
        if job is None:
            return
        try:
            await run_job(session, job)
        except Exception as exc:
            logger.exception("UCP audit job failed: %s", job_id)
            await session.refresh(job)
            job.status = config.UCP_AUDIT_JOB_STATUS_FAILED
            job.summary = {
                **dict(job.summary or {}),
                "error": f"{type(exc).__name__}: {exc}",
            }
            job.completed_at = datetime.now(UTC)
            await session.commit()


async def run_job(session: AsyncSession, job: UCPAuditJob) -> None:
    job.status = config.UCP_AUDIT_JOB_STATUS_RUNNING
    job.summary = {**dict(job.summary or {}), "started_at": datetime.now(UTC).isoformat()}
    await session.commit()

    audit_id = f"ucp-{job.id}-{uuid4().hex[:8]}"
    report = await build_ucp_report_for_domain(
        job.domain,
        audit_id,
        dict(job.options or {}),
    )
    payload = build_report_payload(report)
    markdown = build_markdown_report(report)

    session.add(
        UCPAuditPageResult(
            job_id=job.id,
            url=_root_url(job.domain),
            acquisition_mode=config.UCP_HTTP_ONLY_MODE,
            dimension_payloads=payload,
            findings=payload["findings"],
        )
    )
    session.add(
        UCPAuditReport(
            job_id=job.id,
            overall_score=report.overall_score,
            dimension_scores=payload["dimension_scores"],
            findings=payload["findings"],
            report_json=payload,
            markdown_report=markdown,
        )
    )
    await session.flush()
    job.status = config.UCP_AUDIT_JOB_STATUS_COMPLETE
    job.summary = {
        **dict(job.summary or {}),
        "overall_score": report.overall_score,
        "page_result_count": 1,
        "finding_count": len(report.all_findings),
    }
    job.completed_at = datetime.now(UTC)
    await session.commit()


async def build_ucp_report_for_domain(
    domain: str,
    audit_id: str,
    options: dict[str, object],
) -> UCPComplianceReport:
    normalized_options = _normalized_options(options)
    manifest = await discover_ucp_manifest(domain)
    discovery_score = 100 if manifest.manifest_valid else 0
    findings: list[UCPFinding] = []
    if not manifest.manifest_found:
        findings.append(
            UCPFinding(
                code=config.FINDING_MANIFEST_MISSING,
                dimension_id=config.D_UCP1_ID,
                severity=config.UCP_FINDING_BLOCKING,
            )
        )
    elif not manifest.manifest_valid:
        findings.append(
            UCPFinding(
                code=config.FINDING_MANIFEST_INVALID,
                dimension_id=config.D_UCP1_ID,
                severity=config.UCP_FINDING_BLOCKING,
            )
        )
    sample_size = _bounded_int(
        normalized_options.get("sample_size"),
        default=config.UCP_AUDIT_DEFAULT_SAMPLE_SIZE,
        upper=config.UCP_AUDIT_MAX_SAMPLE_SIZE,
    )
    sampled_pages = await _sample_product_pages(domain, sample_size=sample_size)
    schema_scores = [
        score_product_schema(url, html)
        for url, html in sampled_pages
        if str(html or "").strip()
    ]
    agent_dimension, agent_samples = await _agent_delta_dimension(
        sampled_pages,
        schema_scores,
        include_agent_delta=bool(normalized_options.get("include_agent_delta")),
    )
    dimensions = [
        _dimension(config.D_UCP1_ID, discovery_score, findings),
        _product_schema_dimension(schema_scores, sampled_count=len(sampled_pages)),
        _metafield_dimension(schema_scores),
        _taxonomy_dimension(schema_scores),
        _variant_dimension(
            _records_from_schema_offers(schema_scores),
            schema_scores,
            sampled_pages,
        ),
        _policy_dimension(schema_scores, sampled_pages),
        agent_dimension,
    ]
    return build_compliance_report(
        domain=domain,
        audit_id=audit_id,
        dimension_scores=dimensions,
        agent_view_samples=agent_samples,
    )


async def list_ucp_audit_jobs(
    session: AsyncSession,
    *,
    user: User,
    limit: int = 25,
) -> list[UCPAuditJob]:
    statement = select(UCPAuditJob).order_by(UCPAuditJob.id.desc()).limit(limit)
    if getattr(user, "role", "") != "admin":
        statement = statement.where(UCPAuditJob.user_id == user.id)
    return list((await session.scalars(statement)).all())


async def get_ucp_audit_job(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> UCPAuditJob:
    job = await session.get(UCPAuditJob, job_id)
    if job is None or (getattr(user, "role", "") != "admin" and job.user_id != user.id):
        raise LookupError("UCP audit job not found")
    return job


async def get_ucp_audit_report(
    session: AsyncSession,
    job_id: int,
) -> UCPAuditReport | None:
    return await session.scalar(
        select(UCPAuditReport).where(UCPAuditReport.job_id == job_id)
    )


async def build_ucp_audit_job_payload(
    session: AsyncSession,
    *,
    job: UCPAuditJob,
) -> dict[str, object]:
    page_results = list(
        (
            await session.scalars(
                select(UCPAuditPageResult)
                .where(UCPAuditPageResult.job_id == job.id)
                .order_by(UCPAuditPageResult.id)
            )
        ).all()
    )
    report = await session.scalar(
        select(UCPAuditReport).where(UCPAuditReport.job_id == job.id)
    )
    return {
        "job": job,
        "page_results": page_results,
        "report": report,
    }


async def _sample_product_pages(
    domain: str,
    *,
    sample_size: int,
) -> list[tuple[str, str]]:
    urls = await _discover_product_urls(domain, limit=sample_size)
    semaphore = asyncio.Semaphore(config.UCP_SAMPLE_FETCH_CONCURRENCY)

    async def fetch_sample(url: str) -> tuple[str, str] | None:
        async with semaphore:
            page = await _fetch_audit_page(url)
        if page is None:
            return None
        final_url = str(getattr(page, "final_url", "") or url)
        html = str(getattr(page, "html", "") or "")
        if not html.strip():
            return None
        return final_url, html

    results = await asyncio.gather(*(fetch_sample(url) for url in urls))
    return [item for item in results if item is not None][:sample_size]


async def _collect_discovery_urls(
    domain: str,
    product_urls: list[str],
    seen: set[str],
    child_seen: set[str],
    url: str,
    *,
    limit: int,
) -> None:
    page = await _fetch_audit_page(url)
    if page is None:
        return
    html = str(getattr(page, "html", "") or "")
    child_sitemaps: list[str] = []
    for candidate in _product_urls_from_html(html, url, domain):
        _append_unique(product_urls, seen, candidate, limit=limit)
    for candidate in _urls_from_xml(html, url):
        if _is_product_url(candidate, domain):
            _append_unique(product_urls, seen, candidate, limit=limit)
        elif _is_sitemap_url(candidate):
            child_sitemaps.append(candidate)
    for sitemap_url in child_sitemaps:
        if len(product_urls) >= limit:
            break
        if sitemap_url in child_seen:
            continue
        child_seen.add(sitemap_url)
        if len(child_seen) > config.UCP_SAMPLE_CHILD_SITEMAP_LIMIT:
            break
        page = await _fetch_audit_page(sitemap_url)
        if page is None:
            continue
        sitemap_html = str(getattr(page, "html", "") or "")
        for candidate in _urls_from_xml(sitemap_html, sitemap_url):
            if _is_product_url(candidate, domain):
                _append_unique(product_urls, seen, candidate, limit=limit)


async def _discover_product_urls(domain: str, *, limit: int) -> list[str]:
    seen: set[str] = set()
    product_urls: list[str] = []
    child_seen: set[str] = set()

    for path in config.UCP_SAMPLE_DISCOVERY_PATHS:
        if len(product_urls) >= limit:
            break
        await _collect_discovery_urls(
            domain,
            product_urls,
            seen,
            child_seen,
            _site_url(domain, path),
            limit=limit,
        )

    return product_urls[:limit]


async def _fetch_audit_page(url: str):
    try:
        async with build_async_http_client(
            follow_redirects=True,
            timeout=config.UCP_DISCOVERY_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(url)
        return SimpleNamespace(
            url=url,
            final_url=str(response.url),
            html=response.text,
            status_code=response.status_code,
            content_type=response.headers.get("content-type", ""),
        )
    except (httpx.HTTPError, OSError, TimeoutError, asyncio.TimeoutError) as exc:
        logger.debug("UCP audit fetch failed for %s: %s", url, exc, exc_info=True)
        return None


def _product_urls_from_html(html: str, base_url: str, domain: str) -> list[str]:
    raw = str(html or "").lstrip("\ufeff").strip()
    if raw.startswith(("<?xml", "<urlset", "<sitemapindex")):
        return []
    soup = BeautifulSoup(raw, "html.parser")
    urls: list[str] = []
    for node in soup.find_all(["a", "link"]):
        href = str(node.get("href") or "").strip()
        if not href:
            continue
        candidate = urljoin(base_url, href)
        if _is_product_url(candidate, domain):
            urls.append(_strip_fragment(candidate))
    return urls


def _urls_from_xml(text: str, base_url: str) -> list[str]:
    raw = str(text or "").lstrip("\ufeff").strip()
    if not raw.startswith(("<", "<?xml")):
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    urls: list[str] = []
    for node in root.iter():
        if str(node.tag or "").rsplit("}", 1)[-1] != "loc":
            continue
        value = " ".join(str(node.text or "").split()).strip()
        if value:
            urls.append(_strip_fragment(urljoin(base_url, value)))
    return urls


def _append_unique(
    values: list[str],
    seen: set[str],
    value: str,
    *,
    limit: int,
) -> None:
    if len(values) >= limit or value in seen:
        return
    seen.add(value)
    values.append(value)


def _is_product_url(url: str, domain: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"}:
        return False
    if not _same_domain(parsed.netloc, domain):
        return False
    path = str(parsed.path or "").lower()
    return any(marker in path for marker in config.UCP_PRODUCT_URL_MARKERS)


def _is_sitemap_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    path = str(parsed.path or "").lower()
    return "sitemap" in path and (path.endswith(".xml") or ".xml" in path)


def _same_domain(host: str, domain: str) -> bool:
    normalized_host = str(host or "").lower().removeprefix("www.")
    normalized_domain = str(domain or "").lower().removeprefix("www.")
    return normalized_host == normalized_domain or normalized_host.endswith(
        f".{normalized_domain}"
    )


def _strip_fragment(url: str) -> str:
    parsed = urlparse(str(url or ""))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _site_url(domain: str, path: str) -> str:
    root = _root_url(domain)
    return urljoin(f"{root}/", str(path or "").lstrip("/"))


def _records_from_schema_offers(schema_scores: list[UCPSchemaScore]) -> list[dict]:
    records: list[dict] = []
    for score in schema_scores:
        variants = [
            {
                config.PUBLIC_VARIANT_PRICE_FIELD: offer.get("price"),
                config.PUBLIC_VARIANT_CURRENCY_FIELD: offer.get(
                    config.POLICY_JSONLD_CURRENCY_FIELD
                ),
                config.PUBLIC_VARIANT_SKU_FIELD: offer.get("sku"),
                config.PUBLIC_VARIANT_AVAILABILITY_FIELD: offer.get("availability"),
            }
            for offer in score.raw_offers
            if isinstance(offer, dict)
        ]
        if variants:
            records.append({config.PUBLIC_VARIANTS_FIELD: variants})
    return records


def _product_schema_dimension(
    schema_scores: list[UCPSchemaScore],
    *,
    sampled_count: int,
) -> UCPDimensionScore:
    if not sampled_count:
        return _dimension(
            config.D_UCP2_ID,
            0,
            [
                UCPFinding(
                    code=config.FINDING_PRODUCT_SAMPLE_MISSING,
                    dimension_id=config.D_UCP2_ID,
                    severity=config.UCP_FINDING_WARNING,
                )
            ],
        )
    score = _average_score([item.completeness_score for item in schema_scores])
    missing_jsonld_scores = [
        item for item in schema_scores if not item.product_jsonld_found
    ]
    missing_required_scores = [item for item in schema_scores if item.missing_required]
    missing_recommended_scores = [item for item in schema_scores if item.missing_recommended]
    missing_additional_property_scores = [
        item for item in schema_scores if not item.ucp_fields_present
    ]
    missing_jsonld = len(missing_jsonld_scores)
    missing_required = sum(len(item.missing_required) for item in missing_required_scores)
    missing_recommended = sum(
        len(item.missing_recommended) for item in missing_recommended_scores
    )
    missing_additional_property = len(missing_additional_property_scores)
    findings = [
        UCPFinding(
            code=config.FINDING_PRODUCT_JSONLD_MISSING,
            dimension_id=config.D_UCP2_ID,
            severity=config.UCP_FINDING_WARNING,
            affected_count=missing_jsonld,
            count_kind="urls",
            affected_urls=[item.url for item in missing_jsonld_scores if item.url],
            evidence=[
                {
                    "url": item.url,
                    "has_product_jsonld": False,
                    "missing_required": item.missing_required,
                    "missing_recommended": item.missing_recommended,
                }
                for item in missing_jsonld_scores
            ],
        )
        if missing_jsonld
        else None,
        UCPFinding(
            code=config.FINDING_PRODUCT_SCHEMA_REQUIRED_MISSING,
            dimension_id=config.D_UCP2_ID,
            severity=config.UCP_FINDING_WARNING,
            affected_count=missing_required,
            count_kind="field_instances",
            affected_urls=[item.url for item in missing_required_scores if item.url],
            evidence=[
                {"url": item.url, "missing_required": item.missing_required}
                for item in missing_required_scores
            ],
        )
        if missing_required
        else None,
        UCPFinding(
            code=config.FINDING_PRODUCT_SCHEMA_RECOMMENDED_MISSING,
            dimension_id=config.D_UCP2_ID,
            severity=config.UCP_FINDING_WARNING,
            affected_count=missing_recommended,
            count_kind="field_instances",
            affected_urls=[item.url for item in missing_recommended_scores if item.url],
            evidence=[
                {"url": item.url, "missing_recommended": item.missing_recommended}
                for item in missing_recommended_scores
            ],
        )
        if missing_recommended
        else None,
        UCPFinding(
            code=config.FINDING_PRODUCT_ADDITIONAL_PROPERTY_MISSING,
            dimension_id=config.D_UCP2_ID,
            severity=config.UCP_FINDING_WARNING,
            affected_count=missing_additional_property,
            count_kind="urls",
            affected_urls=[
                item.url for item in missing_additional_property_scores if item.url
            ],
            evidence=[
                {
                    "url": item.url,
                    "has_additional_property": bool(item.ucp_fields_present),
                }
                for item in missing_additional_property_scores
            ],
        )
        if missing_additional_property
        else None,
    ]
    return _dimension(config.D_UCP2_ID, score, _compact_findings(findings))


def _metafield_dimension(schema_scores: list[UCPSchemaScore]) -> UCPDimensionScore:
    report = build_metafield_coverage_report(schema_scores)
    score = _average_score(
        [int(value * 100) for value in report.coverage_by_attribute.values()]
    )
    findings = [
        UCPFinding(
            code=config.FINDING_METAFIELD_CRITICAL_GAP,
            dimension_id=config.D_UCP3_ID,
            severity=config.UCP_FINDING_BLOCKING,
            affected_count=len(report.critical_gaps),
            count_kind="attribute_gaps",
            evidence=[{"critical_gaps": report.critical_gaps}],
        )
    ] if report.critical_gaps else []
    return _dimension(config.D_UCP3_ID, score, findings)


def _taxonomy_dimension(schema_scores: list[UCPSchemaScore]) -> UCPDimensionScore:
    report = build_taxonomy_consistency_report(schema_scores)
    score = report.consistency_score
    if score == 0 and report.unique_raw_values:
        score = 40
    findings = [
        UCPFinding(
            code=config.FINDING_TAXONOMY_INCONSISTENT,
            dimension_id=config.D_UCP4_ID,
            severity=config.UCP_FINDING_WARNING,
            affected_count=(
                len(report.duplicate_clusters) + len(report.shallow_categories)
            ),
            count_kind="taxonomy_gaps",
            evidence=[
                {
                    "duplicate_clusters": report.duplicate_clusters,
                    "shallow_categories": report.shallow_categories,
                }
            ],
        )
    ] if report.duplicate_clusters or report.shallow_categories else []
    return _dimension(config.D_UCP4_ID, score, findings)


def _variant_dimension(
    records: list[dict],
    schema_scores: list[UCPSchemaScore],
    sampled_pages: list[tuple[str, str]],
) -> UCPDimensionScore:
    report = build_variant_fidelity_report(records)
    findings = list(report.findings)
    score = report.fidelity_score
    if _jsonld_variant_offers_present(schema_scores):
        score = max(score, 75)
        findings = [
            item
            for item in findings
            if item.code
            not in {
                config.FINDING_VARIANT_AVAILABILITY_MISSING,
                config.FINDING_VARIANT_OFFERS_COLLAPSED,
            }
        ]
    discount_count = _in_cart_discount_count(sampled_pages)
    if discount_count:
        score = min(score, 75)
        findings.append(
            UCPFinding(
                code=config.FINDING_PRICE_INTEGRITY_DISCOUNT_MISMATCH,
                dimension_id=config.D_UCP5_ID,
                severity=config.UCP_FINDING_WARNING,
                message=(
                    "In-cart discount messaging is visible but not reflected in "
                    "structured offers.price."
                ),
                affected_count=discount_count,
            )
        )
    return _dimension(config.D_UCP5_ID, score, findings)


def _policy_dimension(
    schema_scores: list[UCPSchemaScore],
    sampled_pages: list[tuple[str, str]],
) -> UCPDimensionScore:
    report = build_policy_readability_report(
        structured_shipping_found=_shipping_found(schema_scores),
        period_machine_readable=_return_period_found(sampled_pages),
        currency_value=_first_currency(schema_scores),
        policy_page_http_accessible=_policy_link_found(sampled_pages),
    )
    return _dimension(config.D_UCP6_ID, report.readability_score, report.findings)


async def _agent_delta_dimension(
    sampled_pages: list[tuple[str, str]],
    schema_scores: list[UCPSchemaScore],
    *,
    include_agent_delta: bool,
) -> tuple[UCPDimensionScore, list[AgentViewDelta]]:
    if not include_agent_delta:
        return (
            _dimension(
                config.D_UCP7_ID,
                100,
                [
                    UCPFinding(
                        code=config.FINDING_AGENT_DELTA_DISABLED,
                        dimension_id=config.D_UCP7_ID,
                        severity=config.UCP_FINDING_INFO,
                    )
                ],
            ),
            [],
        )
    if not sampled_pages:
        return (
            _dimension(
                config.D_UCP7_ID,
                0,
                [
                    UCPFinding(
                        code=config.FINDING_PRODUCT_SAMPLE_MISSING,
                        dimension_id=config.D_UCP7_ID,
                        severity=config.UCP_FINDING_WARNING,
                    )
                ],
            ),
            [],
        )
    try:
        delta = await build_agent_view_delta(
            _best_agent_delta_url(sampled_pages, schema_scores)
        )
    except (
        AcquisitionError,
        httpx.HTTPError,
        OSError,
        TimeoutError,
        asyncio.TimeoutError,
    ) as exc:
        logger.debug("UCP agent-view delta failed: %s", exc, exc_info=True)
        return (
            _dimension(
                config.D_UCP7_ID,
                0,
                [
                    UCPFinding(
                        code=config.FINDING_AGENT_DELTA_UNAVAILABLE,
                        dimension_id=config.D_UCP7_ID,
                        severity=config.UCP_FINDING_WARNING,
                    )
                ],
            ),
            [],
        )
    return dimension_from_agent_delta(delta), [delta]


def _best_agent_delta_url(
    sampled_pages: list[tuple[str, str]],
    schema_scores: list[UCPSchemaScore],
) -> str:
    score_by_url = {item.url: item for item in schema_scores}

    def rank(page: tuple[str, str]) -> tuple[int, int, int]:
        url, html = page
        score = score_by_url.get(url)
        offer_count = len(score.raw_offers) if score else 0
        discount_signal = 1 if _in_cart_discount_count([page]) else 0
        schema_signal = 1 if score and score.product_jsonld_found else 0
        return discount_signal, offer_count, schema_signal

    return max(sampled_pages, key=rank)[0]


def _shipping_found(schema_scores: list[UCPSchemaScore]) -> bool:
    return any(
        isinstance(offer, dict)
        and offer.get(config.POLICY_JSONLD_SHIPPING_FIELD) not in (None, "", [], {})
        for score in schema_scores
        for offer in score.raw_offers
    )


def _first_currency(schema_scores: list[UCPSchemaScore]) -> str:
    for score in schema_scores:
        for offer in score.raw_offers:
            if not isinstance(offer, dict):
                continue
            value = offer.get(config.POLICY_JSONLD_CURRENCY_FIELD)
            if value not in (None, "", [], {}):
                return str(value)
    return ""


def _jsonld_variant_offers_present(schema_scores: list[UCPSchemaScore]) -> bool:
    return any(
        isinstance(offer, dict)
        and offer.get(config.POLICY_JSONLD_CURRENCY_FIELD) not in (None, "", [], {})
        and offer.get("price") not in (None, "", [], {})
        for score in schema_scores
        for offer in score.raw_offers
    )


def _in_cart_discount_count(sampled_pages: list[tuple[str, str]]) -> int:
    return sum(
        1
        for _, html in sampled_pages
        if re.search(r"\b(off|discount|sale)\b.{0,40}\bin\s+cart\b", html, flags=re.I)
        or re.search(r"\bin\s+cart\b.{0,40}\b(off|discount|sale)\b", html, flags=re.I)
    )


def _return_period_found(sampled_pages: list[tuple[str, str]]) -> bool:
    text = " ".join(html for _, html in sampled_pages)
    return bool(re.search(r"\b\d{1,3}\s+days?\b", text, flags=re.I))


def _policy_link_found(sampled_pages: list[tuple[str, str]]) -> bool:
    policy_terms = ("return", "refund", "shipping", "delivery")
    for url, html in sampled_pages:
        soup = BeautifulSoup(str(html or ""), "html.parser")
        for node in soup.find_all("a"):
            href = str(node.get("href") or "").casefold()
            label = str(node.get_text(" ") or "").casefold()
            if any(term in href or term in label for term in policy_terms):
                candidate = urljoin(url, href)
                if urlparse(candidate).scheme in {"http", "https"}:
                    return True
    return False


def _average_score(values: list[int]) -> int:
    if not values:
        return 0
    return int(sum(values) / len(values))


def _dimension(
    dimension_id: str,
    score: int,
    findings: list[UCPFinding],
) -> UCPDimensionScore:
    normalized_score = max(0, min(100, int(score)))
    return UCPDimensionScore(
        dimension_id=dimension_id,
        score=normalized_score,
        status=_dimension_status(dimension_id, normalized_score, findings),
        findings=findings,
        weight=config.DIMENSION_WEIGHTS[dimension_id],
    )


def _compact_findings(findings: list[UCPFinding | None]) -> list[UCPFinding]:
    return [item for item in findings if item is not None]


def _dimension_status(
    dimension_id: str,
    score: int,
    findings: list[UCPFinding],
) -> str:
    if dimension_id == config.D_UCP1_ID:
        return _status(score)
    if findings:
        return config.UCP_STATUS_WARNING
    return _status(score)


def _normalized_domain(value: object) -> str:
    domain = normalize_domain(str(value or "").strip())
    if not domain:
        raise ValueError("UCP audit needs a domain")
    return domain


def _normalized_options(value: object) -> dict[str, object]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    sample_size = _bounded_int(
        raw.get("sample_size"),
        default=config.UCP_AUDIT_DEFAULT_SAMPLE_SIZE,
        upper=config.UCP_AUDIT_MAX_SAMPLE_SIZE,
    )
    formats = raw.get("report_formats")
    return {
        "sample_size": sample_size,
        "include_agent_delta": bool(
            raw.get("include_agent_delta", config.UCP_AUDIT_DEFAULT_INCLUDE_AGENT_DELTA)
        ),
        "llm_enabled": bool(raw.get("llm_enabled", False)),
        "report_formats": _string_list(formats)
        or list(config.UCP_AUDIT_DEFAULT_REPORT_FORMATS),
    }


def _bounded_int(value: object, *, default: int, upper: int) -> int:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, upper))


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip().lower() for item in value if str(item).strip()]


def _root_url(domain: str) -> str:
    return f"{config.UCP_DEFAULT_URL_SCHEME}://{domain}"


def _status(score: int) -> str:
    if score >= 80:
        return config.UCP_STATUS_PASS
    if score >= 50:
        return config.UCP_STATUS_WARNING
    return config.UCP_STATUS_FAIL
