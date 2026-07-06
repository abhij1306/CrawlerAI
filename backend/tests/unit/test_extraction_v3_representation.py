from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config.evaluation import EXTRACTION_V3_MAX_INPUT_TOKENS
from eval.representation import audit_sample_report
from app.extraction.documents import HtmlDocument
from app.extraction.representation import build_flat_map, build_scoped_flat_map, ground


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = ROOT / "artifacts" / "runs" / "1"
AUDIT_SUMMARY = ROOT.parent / "chatgpt_audit" / "summary.json"


def test_flat_map_uses_absolute_paths_and_text_only() -> None:
    document = HtmlDocument(
        "html",
        """
        <html><body>
          <main id="pdp" style="display:block">
            <h1 class="name">Trail Shoe</h1>
            <script>{"price": "999"}</script>
            <p>Fast hiking shoe</p>
          </main>
        </body></html>
        """,
    )

    flat_map = build_flat_map(document)

    assert "/html[1]/body[1]/main[1]/h1[1]" in flat_map
    assert flat_map["/html[1]/body[1]/main[1]/h1[1]"] == "Trail Shoe"
    assert all("script" not in path for path in flat_map)
    assert all("class" not in path and "style" not in path for path in flat_map)


def test_scoping_falls_back_when_region_is_too_small() -> None:
    document = HtmlDocument(
        "html",
        """
        <html><body>
          <main><h1>Trail Shoe</h1></main>
          <section>
            <p>Price $19.98</p>
            <p>SKU RUN-1</p>
            <p>Description has enough useful product words for fallback.</p>
          </section>
        </body></html>
        """,
    )

    scoped = build_scoped_flat_map(document)

    assert scoped.fallback_reason == "scoped_region_below_min_tokens"
    assert scoped.token_count > 0
    assert scoped.scope_path is None


def test_grounding_exact_normalized_and_miss() -> None:
    flat_map = build_flat_map(
        HtmlDocument(
            "html",
            """
            <html><body>
              <main><h1>Trail Shoe</h1><p>Price $19.98</p><p>List $19</p></main>
            </body></html>
            """,
        )
    )

    exact = ground("Trail Shoe", flat_map)
    normalized = ground("1998", flat_map)
    whole_dollars = ground("19.00", flat_map)
    miss = ground("Imaginary Product", flat_map)

    assert exact.grounded is True
    assert exact.match_type == "exact"
    assert normalized.grounded is True
    assert normalized.match_type == "normalized"
    assert whole_dollars.grounded is True
    assert whole_dollars.match_type == "normalized"
    assert miss.grounded is False
    assert miss.match_type == "none"


def test_audit_sample_scoping_is_nonempty_and_capped() -> None:
    if not AUDIT_SUMMARY.exists():
        pytest.skip("audit summary is not present")
    samples = json.loads(AUDIT_SUMMARY.read_text(encoding="utf-8"))[
        "representation_tokens"
    ]

    by_dir = {}
    for sample in samples:
        result_dir = RUN_DIR / "results" / str(sample["dir"])
        html_path = result_dir / "page.html"
        if not html_path.exists():
            pytest.skip("frozen run corpus is not present")
        document = HtmlDocument(
            "html",
            html_path.read_text(encoding="utf-8", errors="ignore"),
        )
        scoped = build_scoped_flat_map(document)
        by_dir[int(sample["dir"])] = scoped
        assert scoped.token_count > 0
        assert scoped.token_count <= EXTRACTION_V3_MAX_INPUT_TOKENS

    assert by_dir[47].fallback_reason == "scoped_region_below_min_tokens"
    assert by_dir[94].vision_recommended is True
    assert by_dir[94].fallback_reason == "full_flat_map_above_token_cap"


def test_audit_sample_report_summarizes_representation_gate() -> None:
    if not AUDIT_SUMMARY.exists():
        pytest.skip("audit summary is not present")

    report = audit_sample_report(
        run_dir=RUN_DIR,
        audit_summary_path=AUDIT_SUMMARY,
    )

    assert report["sample_count"] == 10
    assert report["all_non_empty"] is True
    assert report["all_under_token_cap"] is True
    assert 47 in report["fallback_dirs"]
