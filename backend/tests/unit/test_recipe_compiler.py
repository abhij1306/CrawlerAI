from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.extraction_memory.recipe_compiler import compile_recipe
from app.core.extraction_memory.recipe_executor import execute_recipe
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema, surface_spec
from tests.ast_helpers import collect_import_modules

pytestmark = pytest.mark.unit

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
COMPILER_PATH = APP_ROOT / "core" / "extraction_memory" / "recipe_compiler.py"

_DETAIL_HTML = (
    "<html><body><main>"
    '<h1>Trail Shoe Red</h1>'
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">$129.99</span>'
    '<img src="/img/red.jpg">'
    "</main></body></html>"
)
_LISTING_HTML = (
    "<html><body><ul>"
    '<li><a href="/p/1"><h3>Alpha</h3></a><span>$10</span></li>'
    '<li><a href="/p/2"><h3>Beta</h3></a><span>$20</span></li>'
    "</ul></body></html>"
)


def _detail_request(**kwargs):
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        kwargs.pop("html", _DETAIL_HTML),
        "https://shop.test/products/trail-shoe-red",
        requested_fields=("title", "price", "image"),
        **kwargs,
    )


def _listing_request(**kwargs):
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        kwargs.pop("html", _LISTING_HTML),
        "https://shop.test/c/shoes",
        max_records=10,
        requested_fields=("title", "price"),
        **kwargs,
    )


def _stub(response: str, calls: list[int] | None = None):
    async def _client(system_prompt: str, user_prompt: str) -> str:
        assert system_prompt
        assert user_prompt
        if calls is not None:
            calls.append(1)
        return response

    return _client


async def _compile(request, surface, response, calls=None):
    return await compile_recipe(
        request,
        surface_spec=surface_spec(surface),
        listing_schema=listing_schema(surface),
        model_client=_stub(response, calls),
    )


@pytest.mark.asyncio
async def test_grounded_detail_recipe_is_accepted_with_one_model_call() -> None:
    calls: list[int] = []
    response = (
        '{"record_root": "", "fields": {'
        '"title": "/html[1]/body[1]/main[1]/h1[1]", '
        '"price": "/html[1]/body[1]/main[1]/span[1]"}}'
    )
    result = await _compile(_detail_request(), Surface.ECOMMERCE_DETAIL, response, calls)

    assert len(calls) == 1
    assert result.failure_code is None
    assert result.candidate is not None
    recipe = result.candidate.recipe
    assert recipe.schema_version == "extraction_recipe.v2"
    assert "title" in recipe.fields and "url" in recipe.fields
    assert result.candidate.origin == "model_assisted"


@pytest.mark.asyncio
async def test_grounded_listing_recipe_replays_every_card() -> None:
    response = (
        '{"record_root": "/html[1]/body[1]/ul[1]/li[1]", "fields": {'
        '"title": "/html[1]/body[1]/ul[1]/li[1]/a[1]/h3[1]", '
        '"price": "/html[1]/body[1]/ul[1]/li[1]/span[1]"}}'
    )
    request = _listing_request()
    result = await _compile(request, Surface.ECOMMERCE_LISTING, response)

    assert result.failure_code is None
    assert result.candidate is not None
    execution = execute_recipe(request, result.candidate.recipe)
    assert [row["title"] for row in execution.records] == ["Alpha", "Beta"]
    assert [row["url"] for row in execution.records] == [
        "https://shop.test/p/1",
        "https://shop.test/p/2",
    ]


@pytest.mark.asyncio
async def test_two_card_listing_compiles_with_max_records_one() -> None:
    # Finding 4: the executor slices grounded roots to ``max_records``. A genuine
    # two-card grid compiled with ``max_records=1`` must still compile — the
    # compiler validates the RAW grounded roots, not the sliced output.
    response = (
        '{"record_root": "/html[1]/body[1]/ul[1]/li[1]", "fields": {'
        '"title": "/html[1]/body[1]/ul[1]/li[1]/a[1]/h3[1]", '
        '"price": "/html[1]/body[1]/ul[1]/li[1]/span[1]"}}'
    )
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        _LISTING_HTML,
        "https://shop.test/c/shoes",
        max_records=1,
        requested_fields=("title", "price"),
    )
    result = await _compile(request, Surface.ECOMMERCE_LISTING, response)

    assert result.failure_code is None
    assert result.candidate is not None


_JOB_LISTING_HTML = (
    "<html><body><ul>"
    '<li class="job"><a class="t" href="/jobs/1">Engineer</a>'
    '<a class="apply" href="/apply/1">Apply</a><span class="co">Acme</span></li>'
    '<li class="job"><a class="t" href="/jobs/2">Designer</a>'
    '<a class="apply" href="/apply/2">Apply</a><span class="co">Acme</span></li>'
    "</ul></body></html>"
)


@pytest.mark.asyncio
async def test_job_listing_identity_is_url_and_apply_url_stays_scalar() -> None:
    # A job-listing card carries two anchors: its own posting link (url) and the
    # apply link (apply_url). Record identity must be ``url`` (finding 4) and each
    # attribute binding must anchor to its exact grounded node so the two links
    # do not collapse onto one list value (finding 8).
    response = (
        '{"record_root": "/html[1]/body[1]/ul[1]/li[1]", "fields": {'
        '"title": "/html[1]/body[1]/ul[1]/li[1]/a[1]", '
        '"url": "/html[1]/body[1]/ul[1]/li[1]/a[1]", '
        '"apply_url": "/html[1]/body[1]/ul[1]/li[1]/a[2]", '
        '"company": "/html[1]/body[1]/ul[1]/li[1]/span[1]"}}'
    )
    request = fixture_request_from_inputs(
        Surface.JOB_LISTING,
        _JOB_LISTING_HTML,
        "https://jobs.test/careers",
        max_records=10,
        requested_fields=("title", "url", "apply_url", "company"),
    )
    result = await _compile(request, Surface.JOB_LISTING, response)

    assert result.failure_code is None
    assert result.candidate is not None
    recipe = result.candidate.recipe
    assert [binding.field for binding in recipe.identity] == ["url"]
    execution = execute_recipe(request, recipe)
    assert [row["url"] for row in execution.records] == [
        "https://jobs.test/jobs/1",
        "https://jobs.test/jobs/2",
    ]
    assert [row["apply_url"] for row in execution.records] == [
        "https://jobs.test/apply/1",
        "https://jobs.test/apply/2",
    ]


@pytest.mark.asyncio
async def test_job_listing_url_required_even_when_not_requested() -> None:
    # requested_fields omits "url", but a job-listing record is identified by
    # url, so the compiler must still prompt for and require it (consistency
    # between _requested_field_names and _identity_field). The model grounds it
    # and the recipe compiles with url identity.
    response = (
        '{"record_root": "/html[1]/body[1]/ul[1]/li[1]", "fields": {'
        '"title": "/html[1]/body[1]/ul[1]/li[1]/a[1]", '
        '"url": "/html[1]/body[1]/ul[1]/li[1]/a[1]", '
        '"apply_url": "/html[1]/body[1]/ul[1]/li[1]/a[2]"}}'
    )
    request = fixture_request_from_inputs(
        Surface.JOB_LISTING,
        _JOB_LISTING_HTML,
        "https://jobs.test/careers",
        max_records=10,
        requested_fields=("title", "apply_url"),
    )
    result = await _compile(request, Surface.JOB_LISTING, response)

    assert result.failure_code is None
    assert result.candidate is not None
    recipe = result.candidate.recipe
    assert [binding.field for binding in recipe.identity] == ["url"]
    execution = execute_recipe(request, recipe)
    assert [row["url"] for row in execution.records] == [
        "https://jobs.test/jobs/1",
        "https://jobs.test/jobs/2",
    ]


@pytest.mark.asyncio
async def test_optional_ungrounded_binding_is_dropped() -> None:
    html = "<html><body><main><h1>Shoe</h1><a href='/p/1'>l</a></main></body></html>"
    response = (
        '{"record_root": "", "fields": {'
        '"title": "/html[1]/body[1]/main[1]/h1[1]", '
        '"price": "/nonexistent[9]"}}'
    )
    result = await _compile(
        _detail_request(html=html), Surface.ECOMMERCE_DETAIL, response
    )

    assert result.failure_code is None
    assert result.candidate is not None
    assert "price" not in result.candidate.recipe.fields
    assert "title" in result.candidate.recipe.fields


@pytest.mark.asyncio
async def test_required_ungrounded_field_yields_no_recipe() -> None:
    # No <a href> on the page -> the required url identity cannot ground.
    html = "<html><body><main><h1>Trail Shoe</h1><span>$5</span></main></body></html>"
    response = (
        '{"record_root": "", "fields": {'
        '"title": "/html[1]/body[1]/main[1]/h1[1]"}}'
    )
    result = await _compile(
        _detail_request(html=html), Surface.ECOMMERCE_DETAIL, response
    )

    assert result.candidate is None
    assert result.failure_code is not None


@pytest.mark.asyncio
async def test_compiler_ignores_published_record_like_bundle_data() -> None:
    # A network payload shaped like already-published records is present in the
    # bundle. The compiler must never surface those values; it only grounds
    # against the DOM, so the learned price comes from the page ($129.99), not
    # the fabricated 999.99 in the payload.
    payloads = [
        {
            "body": {
                "records": [
                    {"title": "FAKE PUBLISHED", "price": 999.99, "url": "/fake"}
                ]
            }
        }
    ]
    response = (
        '{"record_root": "", "fields": {'
        '"title": "/html[1]/body[1]/main[1]/h1[1]", '
        '"price": "/html[1]/body[1]/main[1]/span[1]"}}'
    )
    request = _detail_request(network_payloads=payloads)
    result = await _compile(request, Surface.ECOMMERCE_DETAIL, response)

    assert result.candidate is not None
    execution = execute_recipe(request, result.candidate.recipe)
    record = execution.records[0]
    assert record["title"] == "Trail Shoe Red"
    assert record["price"] == "129.99"
    assert "FAKE PUBLISHED" not in str(record)


@pytest.mark.asyncio
async def test_compiler_abstains_when_model_returns_no_json() -> None:
    result = await _compile(_detail_request(), Surface.ECOMMERCE_DETAIL, "not json")
    assert result.candidate is None
    assert result.failure_code is not None


def test_compiler_has_no_publication_persistence_or_model_imports() -> None:
    tree = ast.parse(COMPILER_PATH.read_text(encoding="utf-8"))
    imports = collect_import_modules(tree)

    forbidden_prefixes = (
        "app.persistence",
        "app.models",
        "app.extraction.model_runtime",
        "app.extraction.adapters",
        "app.extraction.resolution",
        "app.observability",
    )
    offenders = [
        name
        for name in imports
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in forbidden_prefixes
        )
    ]
    assert not offenders, offenders

    source = COMPILER_PATH.read_text(encoding="utf-8")
    # The compiler must never read published records / publication output.
    assert "record_extraction_result" not in source
    assert "PublicRecord" not in source
    assert ".publication" not in source
    assert "result.records" not in source


def _http_only_request(surface: Surface, html: str, url: str, **kwargs):
    """Build a request whose only HTML artifact is ``http_html`` (no rendered DOM)."""

    from app.core.shared.ids import content_sha256, stable_id
    from app.extraction.contracts import (
        ArtifactRef,
        CaptureBundle,
        ExtractionRequest,
        RequestContext,
    )
    from app.extraction.replay import MemoryArtifactReader

    refs = (
        ArtifactRef(
            artifact_id="html",
            artifact_type="http_html",
            content_sha256=content_sha256(html),
            storage_uri="memory://html",
            media_type="text/html",
        ),
    )
    bundle = CaptureBundle(
        schema_version="capture.v1",
        bundle_id=stable_id("bundle", url, html[:80]),
        run_id=0,
        requested_url=url,
        final_url=url,
        request_context=RequestContext(context_id=stable_id("ctx", url)),
        artifacts=refs,
        acquisition_outcome="ok",
    )
    reader = MemoryArtifactReader({"html": html})
    return ExtractionRequest(
        surface=surface,
        capture=bundle,
        artifact_reader=reader,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_http_only_capture_never_calls_model_and_fails() -> None:
    # Finding 6: an HTTP-only capture cannot satisfy the recipe's rendered-DOM
    # capture requirement, so the compiler must reject BEFORE spending the single
    # model call (the stub call counter stays at 0).
    calls: list[int] = []
    request = _http_only_request(
        Surface.ECOMMERCE_DETAIL,
        _DETAIL_HTML,
        "https://shop.test/products/trail-shoe-red",
        requested_fields=("title", "price", "image"),
    )
    result = await _compile(request, Surface.ECOMMERCE_DETAIL, _DETAIL_HTML, calls)

    assert calls == []
    assert result.candidate is None
    assert result.failure_code == "recipe_capture_requirement_missing"


_SINGLE_CARD_LISTING_HTML = (
    "<html><body><ul>"
    '<li><a href="/p/1"><h3>Alpha</h3></a><span>$10</span></li>'
    "</ul></body></html>"
)


@pytest.mark.asyncio
async def test_compiler_rejects_single_card_listing_page() -> None:
    # Finding 7: the compiler must enforce the min-repeated-records floor at
    # compile time — a listing page grounding a single card yields no recipe.
    response = (
        '{"record_root": "/html[1]/body[1]/ul[1]/li[1]", "fields": {'
        '"title": "/html[1]/body[1]/ul[1]/li[1]/a[1]/h3[1]", '
        '"price": "/html[1]/body[1]/ul[1]/li[1]/span[1]"}}'
    )
    request = _listing_request(html=_SINGLE_CARD_LISTING_HTML)
    result = await _compile(request, Surface.ECOMMERCE_LISTING, response)

    assert result.candidate is None
    assert result.failure_code == "recipe_cardinality_changed"


_SCOPED_FILLER = "price add to cart availability sku description " * 60
_SCOPED_DETAIL_HTML = (
    "<html><body>"
    "<main>"
    "<h1>Trail Shoe Red</h1>"
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">$129.99</span>'
    f"<p>{_SCOPED_FILLER}</p>"
    '<img src="/img/red.jpg">'
    "</main>"
    '<footer><span class="foot">Outside Region Title</span></footer>'
    "</body></html>"
)
_FOOTER_PATH = "/html[1]/body[1]/footer[1]/span[1]"


_OUT_OF_SCOPE_ATTR_HTML = (
    "<html><body>"
    "<main>"
    "<h1>Trail Shoe Red</h1>"
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">$129.99</span>'
    f"<p>{_SCOPED_FILLER}</p>"
    '<img src="/img/red.jpg">'
    "</main>"
    '<footer><a href="/promo/out-of-scope">Promo Link</a></footer>'
    "</body></html>"
)
_OUT_OF_SCOPE_ANCHOR_PATH = "/html[1]/body[1]/footer[1]/a[1]"


@pytest.mark.asyncio
async def test_attribute_binding_rejects_path_outside_scoped_map() -> None:
    # Finding 1: attribute fields (url/apply_url/image_url) must not ground onto
    # a DOM node outside the scoped/capped region the model was shown, even
    # though it resolves on the full page. Here the model grounds ``url`` onto a
    # footer anchor outside ``main``; the exact-node binding must be rejected so
    # the recipe never anchors url to the out-of-scope promo link.
    response = (
        '{"record_root": "", "fields": {'
        '"title": "/html[1]/body[1]/main[1]/h1[1]", '
        '"price": "/html[1]/body[1]/main[1]/span[1]", '
        f'"url": "{_OUT_OF_SCOPE_ANCHOR_PATH}"}}}}'
    )
    request = _detail_request(html=_OUT_OF_SCOPE_ATTR_HTML)
    result = await _compile(request, Surface.ECOMMERCE_DETAIL, response)

    assert result.candidate is not None
    url_bindings = result.candidate.recipe.fields.get("url", ())
    # The out-of-scope footer anchor must never become the url binding path.
    assert all(
        binding.path != "a[1] > a[1]" and "footer" not in binding.path
        for binding in url_bindings
    )
    # The recipe still binds url via the in-scope canonical link, not the promo.
    execution = execute_recipe(request, result.candidate.recipe)
    assert execution.records
    assert all(
        "/promo/out-of-scope" not in str(row.get("url", ""))
        for row in execution.records
    )


def test_path_within_scope_matches_individual_capped_entries() -> None:
    # Finding 1 (re-review): the scope check must compare an attribute path
    # against each INDIVIDUAL capped flat-map entry (ancestor / descendant /
    # equal), NOT their broad common ancestor. Shown entries below share only
    # the common ancestor ``/html/body`` — a sibling that merely descends from
    # that ancestor was never in the prompt and must be rejected.
    from app.core.extraction_memory.recipe_compiler import _path_within_scope

    shown = (
        "/html[1]/body[1]/div[1]/h1[1]",
        "/html[1]/body[1]/div[2]/span[1]",
    )

    # Equal to a capped entry -> accepted.
    assert _path_within_scope("/html[1]/body[1]/div[1]/h1[1]", shown) is True
    # Descendant of a capped entry -> accepted.
    assert _path_within_scope("/html[1]/body[1]/div[1]/h1[1]/a[1]", shown) is True
    # Ancestor (container) of a capped entry -> accepted.
    assert _path_within_scope("/html[1]/body[1]/div[1]", shown) is True
    # Sibling sharing only the broad common ancestor ``/html/body`` -> REJECTED.
    assert _path_within_scope("/html[1]/body[1]/a[405]", shown) is False
    # A different sibling branch under the shared prefix -> REJECTED.
    assert _path_within_scope("/html[1]/body[1]/div[3]/span[1]", shown) is False
    # Empty universe -> nothing is in scope.
    assert _path_within_scope("/html[1]/body[1]/div[1]/h1[1]", ()) is False


def test_is_ancestor_or_descendant_or_equal_direction() -> None:
    # Finding 1 (re-review): segment-prefix comparison in EITHER direction.
    from app.core.extraction_memory.recipe_compiler import (
        _is_ancestor_or_descendant_or_equal,
    )

    entry = "/html[1]/body[1]/div[2]/span[1]"
    # equal
    assert _is_ancestor_or_descendant_or_equal(entry, entry) is True
    # path is a descendant of entry
    assert _is_ancestor_or_descendant_or_equal(f"{entry}/a[1]", entry) is True
    # path is an ancestor of entry
    assert _is_ancestor_or_descendant_or_equal("/html[1]/body[1]/div[2]", entry) is True
    # sibling: diverges at div[2] vs div[3]
    assert (
        _is_ancestor_or_descendant_or_equal("/html[1]/body[1]/div[3]", entry) is False
    )
    # sibling leaf under shared ancestor
    assert _is_ancestor_or_descendant_or_equal("/html[1]/body[1]/a[405]", entry) is False


@pytest.mark.asyncio
async def test_compiler_rejects_path_outside_scoped_map() -> None:
    # Finding 9: the model may only ground onto paths in the scoped/capped map it
    # was shown. A title path that is valid on the full page but lives outside the
    # scoped region (a footer) must be rejected — no field grounds onto it, so the
    # required title binding is missing and no recipe is returned.
    response = (
        '{"record_root": "", "fields": {'
        f'"title": "{_FOOTER_PATH}", '
        '"price": "/html[1]/body[1]/main[1]/span[1]"}}'
    )
    request = _detail_request(html=_SCOPED_DETAIL_HTML)
    result = await _compile(request, Surface.ECOMMERCE_DETAIL, response)

    assert result.candidate is None
    assert result.failure_code is not None
