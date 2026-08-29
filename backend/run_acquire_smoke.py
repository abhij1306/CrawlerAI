r"""
Acquire-only smoke runner aligned to the current acquisition facade.

Usage:
    cd backend
    set PYTHONPATH=.
    .venv\Scripts\python.exe run_acquire_smoke.py
    .venv\Scripts\python.exe run_acquire_smoke.py api commerce jobs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.acquisition.acquirer import (
    AcquisitionRequest,
    acquire,
)
from app.acquisition.runtime import is_blocked_html
from app.acquisition.runtime_plan import AcquisitionIntent
from app.acquisition.platform_policy import detect_platform_family

from harness.support import require_explicit_surface

BATCHES: dict[str, list[tuple[str, str, str]]] = {
    "api": [
        (
            "Allbirds products.json",
            "https://www.allbirds.com/products.json",
            "ecommerce_listing",
        ),
        (
            "OpenFoodFacts sodas.json",
            "https://world.openfoodfacts.org/category/sodas.json",
            "ecommerce_listing",
        ),
        ("Remotive API", "https://remotive.com/api/remote-jobs", "job_listing"),
        ("RemoteOK API", "https://remoteok.com/api", "job_listing"),
    ],
    "commerce": [
        (
            "Allbirds PDP",
            "https://www.allbirds.com/products/mens-wool-runners",
            "ecommerce_detail",
        ),
        (
            "Allbirds listing",
            "https://www.allbirds.com/collections/mens",
            "ecommerce_listing",
        ),
        (
            "Gymshark listing",
            "https://www.gymshark.com/collections/all-products",
            "ecommerce_listing",
        ),
        (
            "Puma mens listing",
            "https://us.puma.com/us/en/men/shop-all-mens",
            "ecommerce_listing",
        ),
        (
            "Converse mens listing",
            "https://www.converse.com/shop/mens-shoes",
            "ecommerce_listing",
        ),
        (
            "UnderArmour mens listing",
            "https://www.underarmour.com/en-us/c/mens/",
            "ecommerce_listing",
        ),
    ],
    "jobs": [
        (
            "Greenhouse board",
            "https://boards.greenhouse.io/embed/job_board?for=stripe",
            "job_listing",
        ),
        ("Lever board", "https://jobs.lever.co/reddit", "job_listing"),
        ("Remotive jobs page", "https://remotive.com/remote-jobs", "job_listing"),
        ("RemoteOK jobs page", "https://remoteok.com/remote-dev-jobs", "job_listing"),
        (
            "Himalayas detail",
            "https://himalayas.app/jobs/product-designer/runway",
            "job_detail",
        ),
    ],
    "hard": [
        (
            "Footlocker mens shoes",
            "https://www.footlocker.com/category/mens/shoes.html",
            "ecommerce_listing",
        ),
        (
            "John Lewis electricals",
            "https://www.johnlewis.com/browse/electricals/c6000014",
            "ecommerce_listing",
        ),
        (
            "Nike mens shoes",
            "https://www.nike.com/w/mens-shoes-nik1zy7ok",
            "ecommerce_listing",
        ),
        (
            "Dyson air treatment",
            "https://www.dyson.in/air-treatment",
            "ecommerce_listing",
        ),
    ],
    "ats": [
        (
            "Greenhouse Doordash",
            "https://boards.greenhouse.io/embed/job_board?for=doordash",
            "job_listing",
        ),
        (
            "Greenhouse Notion",
            "https://boards.greenhouse.io/embed/job_board?for=notion",
            "job_listing",
        ),
        ("Lever Figma", "https://jobs.lever.co/figma", "job_listing"),
        ("Lever Linear", "https://jobs.lever.co/linear", "job_listing"),
    ],
    "specialist": [
        ("Adafruit PDP", "https://www.adafruit.com/product/5700", "ecommerce_detail"),
        ("SparkFun PDP", "https://www.sparkfun.com/products/19030", "ecommerce_detail"),
        (
            "McMaster listing",
            "https://www.mcmaster.com/pipe-fittings/high-pressure-stainless-steel-threaded-pipe-fittings/",
            "ecommerce_listing",
        ),
        (
            "B&H Sony PDP",
            "https://www.bhphotovideo.com/c/product/1730114-REG/sony_ilce_7rm5_b_alpha_a7r_v_mirrorless.html",
            "ecommerce_detail",
        ),
    ],
}


async def _run_one(
    run_id: int, name: str, url: str, surface: str, timeout_seconds: int
) -> dict:
    started = time.perf_counter()
    surface = require_explicit_surface(surface)
    try:
        result = await asyncio.wait_for(
            acquire(
                AcquisitionRequest(
                    run_id=run_id,
                    url=url,
                    plan=AcquisitionIntent(
                        surface=surface,
                        max_pages=3,
                        max_scrolls=3,
                    ),
                )
            ),
            timeout=timeout_seconds,
        )
        blocked = (
            is_blocked_html(result.html or "", result.status_code)
            if result.content_type and result.content_type.startswith("text/html")
            else False
        )
        return {
            "name": name,
            "url": url,
            "surface": surface,
            "platform_family": detect_platform_family(url, result.html or ""),
            "ok": True,
            "method": result.method,
            "status_code": result.status_code,
            "content_type": result.content_type,
            "html_len": len(result.html or ""),
            "network_payloads": len(result.network_payloads or []),
            "blocked": blocked,
            "browser_diagnostics": dict(result.browser_diagnostics or {}),
            "seconds": round(time.perf_counter() - started, 2),
        }
    except Exception as exc:  # noqa: BLE001 - smoke runner reports each target failure
        return {
            "name": name,
            "url": url,
            "surface": surface,
            "platform_family": detect_platform_family(url),
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "seconds": round(time.perf_counter() - started, 2),
        }


async def _run_batch(
    batch_name: str, timeout_seconds: int, *, start_run_id: int
) -> list[dict]:
    results: list[dict] = []
    for offset, (name, url, surface) in enumerate(BATCHES[batch_name], start=1):
        results.append(
            await _run_one(
                start_run_id + offset - 1, name, url, surface, timeout_seconds
            )
        )
    return results


def _report_dir() -> Path:
    return settings.artifacts_dir / "acquisition_smoke"


def _build_summary(overall: dict[str, list[dict]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for batch_name, rows in overall.items():
        ok = sum(1 for row in rows if row.get("ok"))
        summary[batch_name] = {"ok": ok, "failed": len(rows) - ok, "total": len(rows)}
    return summary


def _write_report(
    overall: dict[str, list[dict]], selected: list[str], timeout_seconds: int
) -> Path:
    report_dir = _report_dir()
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    batch_slug = "-".join(selected)
    path = report_dir / f"{stamp}__{batch_slug}.json"
    payload = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "timeout_seconds": timeout_seconds,
        "batches": selected,
        "summary": _build_summary(overall),
        "results": overall,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Run small acquire-only smoke batches."
    )
    parser.add_argument(
        "batches", nargs="*", choices=sorted(BATCHES), help="Batch names to run"
    )
    parser.add_argument(
        "--timeout", type=int, default=75, help="Per-site timeout in seconds"
    )
    args = parser.parse_args(argv)

    selected = args.batches or ["api", "commerce"]
    overall: dict[str, list[dict]] = {}
    run_id_base = 40000
    for batch_name in selected:
        overall[batch_name] = await _run_batch(
            batch_name, args.timeout, start_run_id=run_id_base
        )
        run_id_base += len(BATCHES[batch_name])

    report_path = _write_report(overall, selected, args.timeout)
    print(
        json.dumps(
            {
                "summary": _build_summary(overall),
                "report_path": str(report_path),
                "results": overall,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
