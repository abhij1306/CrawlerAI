from __future__ import annotations

import json

import pytest
from app.models.crawl_run import CrawlRecord
from app.persistence import record_export_service
from app.persistence.record_export_service import (
    build_json_export_response,
    stream_export_artifacts_json,
    stream_export_csv,
    stream_export_json,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


async def _collect_chunks(stream) -> str:
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
    return "".join(chunks)


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_streams_serialize_clean_record_data(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={
                "title": "Widget Prime",
                "price": "19.99",
                "_source": "dom",
                "empty_field": "",
            },
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    await db_session.commit()

    exported_json = await _collect_chunks(stream_export_json(db_session, run.id))
    exported_csv = await _collect_chunks(stream_export_csv(db_session, run.id))
    json_rows = json.loads(exported_json)

    assert json_rows == [{"price": "19.99", "title": "Widget Prime"}]
    assert "_source" not in exported_csv
    assert "Widget Prime" in exported_csv


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_streams_include_records_from_failed_partial_run(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        run_type="batch",
    )
    run.status = "failed"
    run.result_summary = {
        "extraction_verdict": "partial",
        "record_count": 1,
        "url_verdicts": ["error", "success"],
    }
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={"title": "Widget Prime", "price": "19.99"},
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    await db_session.commit()

    exported_json = await _collect_chunks(stream_export_json(db_session, run.id))
    exported_csv = await _collect_chunks(stream_export_csv(db_session, run.id))

    assert json.loads(exported_json) == [{"price": "19.99", "title": "Widget Prime"}]
    assert "Widget Prime" in exported_csv


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_response_exposes_required_field_quality_gate(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=["title", "price"],
    )
    db_session.add(
        CrawlRecord(
            run_id=run.id,
            source_url=run.url,
            data={"title": "Widget Prime"},
            raw_data={},
            discovered_data={},
            source_trace={},
        )
    )
    await db_session.commit()

    response = await build_json_export_response(db_session, run_id=run.id)

    assert response.headers["X-Export-Quality-Gate"] == "fail"
    report = json.loads(response.headers["X-Export-Quality-Report"])
    assert report["failed_fields"] == ["price"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_streamers_preserve_order_across_paged_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        CrawlRecord(
            id=1,
            run_id=7,
            source_url="https://example.com/a",
            data={"title": "A"},
            raw_data={},
            discovered_data={},
            source_trace={
                "field_discovery": {
                    "title": {
                        "status": "found",
                        "value": {"native": 1},
                        "sources": ["dom"],
                    }
                }
            },
        ),
        CrawlRecord(
            id=2,
            run_id=7,
            source_url="https://example.com/b",
            data={"title": "B"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
        CrawlRecord(
            id=3,
            run_id=7,
            source_url="https://example.com/c",
            data={"title": "C"},
            raw_data={},
            discovered_data={},
            source_trace={},
        ),
    ]

    async def _fake_get_run_records(session, run_id, page, page_size):
        del session, page_size
        assert run_id == 7
        pages = {
            1: (rows[:2], 3),
            2: (rows[2:], 3),
        }
        return pages.get(page, ([], 3))

    monkeypatch.setattr(record_export_service, "get_run_records", _fake_get_run_records)
    monkeypatch.setattr(record_export_service, "MAX_RECORD_PAGE_SIZE", 2)

    exported_json = await _collect_chunks(stream_export_json(None, 7))
    exported_csv = await _collect_chunks(stream_export_csv(None, 7))
    exported_artifacts = await _collect_chunks(stream_export_artifacts_json(None, 7))

    json_rows = json.loads(exported_json)
    artifact_rows = json.loads(exported_artifacts)

    assert [row["title"] for row in json_rows] == ["A", "B", "C"]
    assert exported_csv.index("A") < exported_csv.index("B") < exported_csv.index("C")
    assert [row["source_url"] for row in artifact_rows] == [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    assert record_export_service.export_record_from_row(
        rows[0],
        data=dict(rows[0].data),
        source_trace=dict(rows[0].source_trace),
    ).field_discovery[
        "title"
    ].value == {"native": 1}


@pytest.mark.asyncio
@pytest.mark.component
async def test_export_stream_rejects_bad_provenance_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        CrawlRecord(
            id=1,
            run_id=7,
            source_url="https://example.com/a",
            data={"title": "A"},
            raw_data={},
            discovered_data={},
            source_trace={"field_discovery": {"title": "bad"}},
        )
    ]

    async def _fake_get_run_records(session, run_id, page, page_size):
        del session, run_id, page_size
        return (rows, 1) if page == 1 else ([], 1)

    monkeypatch.setattr(record_export_service, "get_run_records", _fake_get_run_records)

    with pytest.raises(ValidationError):
        await _collect_chunks(stream_export_json(None, 7))


@pytest.mark.component
def test_export_image_dedupe_preserves_comma_containing_urls() -> None:
    sanitized = record_export_service._sanitize_export_data(
        {
            "image_url": "https://cdn.example.com/images/widget-1.jpg",
            "additional_images": [
                "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg",
                "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg",
            ],
        }
    )

    assert sanitized["additional_images"] == (
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-2.jpg, "
        "https://cdn.example.com/images/f_auto,q_auto,w_1080/widget-3.jpg"
    )


@pytest.mark.component
def test_clean_export_data_keeps_variant_payloads_but_hides_internal_fields() -> None:
    cleaned = record_export_service.clean_export_data(
        {
            "title": "Widget Prime",
            "variants": [{"sku": "W-1", "color": "Black"}],
            "variant_axes": {"color": ["Black"]},
            "selected_variant": {"sku": "W-1", "color": "Black"},
            "_source": "dom",
        }
    )

    assert cleaned == {
        "title": "Widget Prime",
        "variants": [{"sku": "W-1", "color": "Black"}],
        "variant_axes": {"color": ["Black"]},
        "selected_variant": {"sku": "W-1", "color": "Black"},
    }
