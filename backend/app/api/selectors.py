from __future__ import annotations

import logging
from typing import Annotated, NoReturn
from urllib.parse import urlparse

import httpx
from soupsieve import SelectorSyntaxError

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.selectors import (
    SelectorCreateRequest,
    SelectorDomainSummaryResponse,
    SelectorRecordResponse,
    SelectorSuggestRequest,
    SelectorSuggestResponse,
    SelectorTestRequest,
    SelectorTestResponse,
    SelectorUpdateRequest,
)
from app.services.selectors_runtime import (
    build_preview_html,
    create_selector_record,
    delete_domain_selector_records,
    delete_selector_record,
    fetch_selector_document,
    list_selector_domain_summaries,
    list_selector_records,
    suggest_selectors,
    test_selector,
    update_selector_record,
)
from app.services.url_safety import SecurityError, validate_public_target
from app.services.acquisition.playwright_compat import (
    PlaywrightError,
    PlaywrightTimeoutError,
    is_recoverable_playwright_error,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/selectors", tags=["selectors"])
logger = logging.getLogger(__name__)


def _raise_selector_fetch_error(
    exc: Exception,
    *,
    message: str,
    detail: str,
) -> NoReturn:
    if isinstance(exc, RuntimeError) and not is_recoverable_playwright_error(exc):
        raise exc
    logger.warning(message, exc_info=True)
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=detail,
    ) from exc


@router.get("/summary")
async def selectors_summary(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SelectorDomainSummaryResponse]:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    return [
        SelectorDomainSummaryResponse.model_validate(row)
        for row in await list_selector_domain_summaries(
            session,
            domain=normalized_domain,
            surface=normalized_surface,
            limit=limit,
            offset=offset,
        )
    ]


@router.get("")
async def selectors_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
) -> list[SelectorRecordResponse]:
    return [
        SelectorRecordResponse.model_validate(row)
        for row in await list_selector_records(
            session,
            domain=domain,
            surface=surface,
        )
    ]


@router.post("")
async def selectors_create(
    payload: SelectorCreateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorRecordResponse:
    record = await create_selector_record(
        session,
        domain=payload.domain,
        surface=payload.surface,
        payload=payload.model_dump(),
    )
    return SelectorRecordResponse.model_validate(record)


@router.put("/{selector_id}")
async def selectors_update(
    selector_id: int,
    payload: SelectorUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorRecordResponse:
    record = await update_selector_record(
        session,
        selector_id=selector_id,
        payload=payload.model_dump(exclude_none=True),
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selector not found")
    return SelectorRecordResponse.model_validate(record)


@router.delete("/{selector_id}", status_code=status.HTTP_204_NO_CONTENT)
async def selectors_delete(
    selector_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> Response:
    deleted = await delete_selector_record(session, selector_id=selector_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selector not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/domain/{domain}")
async def selectors_delete_domain(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    surface: str | None = None,
) -> dict[str, int]:
    deleted = await delete_domain_selector_records(
        session,
        domain=domain,
        surface=surface,
    )
    return {"deleted": deleted}


@router.post("/suggest")
async def selectors_suggest(
    payload: SelectorSuggestRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorSuggestResponse:
    try:
        result = await suggest_selectors(
            session,
            url=str(payload.url),
            expected_columns=list(payload.expected_columns or []),
            surface=payload.surface,
        )
    except (ValueError, SecurityError, SelectorSyntaxError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (TimeoutError, PlaywrightTimeoutError) as exc:
        logger.warning("Timed out suggesting selectors", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out fetching preview HTML from the upstream page.",
        ) from exc
    except (httpx.HTTPError, OSError, RuntimeError, PlaywrightError) as exc:
        _raise_selector_fetch_error(
            exc,
            message="Failed suggesting selectors",
            detail="Unable to fetch preview HTML from the upstream page.",
        )
    return SelectorSuggestResponse.model_validate(result)


@router.post("/test")
async def selectors_test(
    payload: SelectorTestRequest,
    _: Annotated[User, Depends(get_current_user)],
) -> SelectorTestResponse:
    try:
        result = await test_selector(
            url=str(payload.url),
            css_selector=payload.css_selector,
            xpath=payload.xpath,
            regex=payload.regex,
        )
    except (ValueError, SecurityError, SelectorSyntaxError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (TimeoutError, PlaywrightTimeoutError) as exc:
        logger.warning("Timed out testing selector", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out fetching HTML from the upstream page.",
        ) from exc
    except (httpx.HTTPError, OSError, RuntimeError, PlaywrightError) as exc:
        _raise_selector_fetch_error(
            exc,
            message="Failed testing selector",
            detail="Unable to fetch HTML from the upstream page.",
        )
    return SelectorTestResponse.model_validate(result)


@router.get("/preview-html", response_class=HTMLResponse)
async def selectors_preview_html(
    _: Annotated[User, Depends(get_current_user)],
    url: str,
) -> HTMLResponse:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Preview URL must use http:// or https://.",
        )
    try:
        await validate_public_target(url)
        document = await fetch_selector_document(url)
    except (ValueError, SecurityError) as exc:
        logger.info("Rejected selector preview URL", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (TimeoutError, PlaywrightTimeoutError) as exc:
        logger.warning(
            "Timed out fetching selector preview HTML",
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out fetching preview HTML from the upstream page.",
        ) from exc
    except (httpx.HTTPError, OSError, RuntimeError, PlaywrightError) as exc:
        _raise_selector_fetch_error(
            exc,
            message="Failed fetching selector preview HTML",
            detail="Unable to fetch preview HTML from the upstream page.",
        )
    return HTMLResponse(
        content=build_preview_html(
            source_url=str(document["url"]),
            html=str(document["html"]),
        )
    )
