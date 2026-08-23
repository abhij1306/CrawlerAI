"""test_evaluation_phase4 cases split by public behavior."""

from __future__ import annotations

from tests.unit.evaluation_phase4_test_support import (
    COMPACT_REPRESENTATION_MAX_NODES,
    EvaluationCase,
    GroundedLabel,
    GroundingReference,
    ModelAdapterResult,
    ModelPrediction,
    OfflineHarnessResult,
    UTC,
    ValidationError,
    _case,
    _fake_adapter,
    _human_field,
    _node,
    _path,
    build_compact_page_representation,
    cast,
    datetime,
    pytest,
    run_offline_adapter,
    validate_release_partitions,
)


def test_compact_page_representation_is_bounded_and_source_grounded() -> None:
    html = """
    <html><body>
      <script>var huge = 'ignored';</script>
      <main data-testid="primary">
        <article class="card"><h2 class="title">Trail Shoe</h2><span class="price">$10</span></article>
        <article class="card"><h2 class="title">Road Shoe</h2><span class="price">$20</span></article>
      </main>
    </body></html>
    """

    page = build_compact_page_representation(
        html=html, artifact_id="html", market_tags=("en-US",), max_nodes=4
    )

    assert page.schema_version == "compact_page.v2"
    assert len(page.nodes) == 4
    assert page.truncated is True
    assert page.source.artifact_id == "html"
    assert all(node.tag != "script" for node in page.nodes)
    assert any(node.attributes.get("data-testid") == "primary" for node in page.nodes)
    assert any(node.repeated_block_key for node in page.nodes)
    assert page.market_tags == ("en-US",)


def test_compact_representation_does_not_duplicate_descendant_text_on_containers() -> (
    None
):
    page = build_compact_page_representation(
        html="<main data-testid='product'><h1>Trail Shoe</h1><p>Fast shoe</p></main>",
        artifact_id="html",
    )

    main = next(node for node in page.nodes if node.tag == "main")
    title = next(node for node in page.nodes if node.tag == "h1")
    assert main.text == ""
    assert title.text == "Trail Shoe"


def test_compact_page_representation_carries_path_label_references() -> None:
    html = "<html><body><main><h1>Trail Shoe</h1></main></body></html>"
    initial = build_compact_page_representation(html=html, artifact_id="html")
    title_path = next(node.path for node in initial.nodes if node.tag == "h1")
    label = GroundedLabel(
        label_id="label-title-path",
        authority="human_verified",
        target_kind="field",
        subject_id="product-1",
        record_id="record-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_path(title_path),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    page = build_compact_page_representation(
        html=html, artifact_id="html", labels=(label,)
    )

    title_node = next(node for node in page.nodes if node.path == title_path)
    assert title_node.label_ids == ("label-title-path",)
    assert page.labels == (label,)
    assert page.grounding_references == label.grounding


def test_compact_representation_resolves_css_node_labels_and_enforces_global_cap() -> (
    None
):
    html = (
        "<main>"
        + "".join(
            f'<article class="card"><h2 class="title">Item {index}</h2></article>'
            for index in range(100)
        )
        + "</main>"
    )
    label = _human_field(grounding=(_node(),))

    page = build_compact_page_representation(
        html=html,
        artifact_id="html",
        labels=(label,),
        max_nodes=10_000,
    )

    assert len(page.nodes) <= COMPACT_REPRESENTATION_MAX_NODES
    assert page.truncated is True
    assert any("label-title" in node.label_ids for node in page.nodes)
    assert page.grounding_references == label.grounding


def test_compact_representation_rejects_non_positive_node_bound() -> None:
    with pytest.raises(ValueError, match="max_nodes"):
        build_compact_page_representation(
            html="<h1>Trail Shoe</h1>", artifact_id="html", max_nodes=0
        )


def test_release_partition_gate_fails_closed_when_required_partitions_are_missing() -> (
    None
):
    cases = (
        _case("known_template", _human_field(), case_id="known"),
        _case(
            "unseen_template", _human_field(label_id="label-unseen"), case_id="unseen"
        ),
    )

    gate = validate_release_partitions(cases)

    assert gate["passed"] is False
    assert gate["release_label_counts"] == {"known_template": 1, "unseen_template": 1}
    missing = cast(tuple[str, ...], gate["missing_partitions"])
    assert "temporal_change" in missing


def test_release_partition_gate_counts_only_release_eligible_labels() -> None:
    weak = GroundedLabel(
        label_id="weak-title",
        authority="weak",
        target_kind="field",
        subject_id="product-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_path(),),
    )
    case = EvaluationCase(
        case_id="weak-case",
        input_bundle_ref="bundle://weak",
        partition="known_template",
        surface="ecommerce_detail",
        labels=(weak,),
        release_evaluation_label_ids=(),
        expected_trust_outcome="review",
        required_metrics=("field_f1",),
    )

    gate = validate_release_partitions(
        (case,),
        required_partitions=("known_template",),
        required_surfaces=(),
        required_scenarios=(),
    )

    assert gate == {
        "passed": False,
        "missing_partitions": ("known_template",),
        "missing_surfaces": (),
        "missing_scenarios": (),
        "release_label_counts": {},
        "release_label_counts_by_surface": {},
        "release_label_counts_by_scenario": {},
    }


def test_offline_model_harness_emits_evidence_only_predictions() -> None:
    page = build_compact_page_representation(
        html="<html><body><h1>Trail Shoe</h1></body></html>", artifact_id="html"
    )

    title_path = next(node.path for node in page.nodes if node.text == "Trail Shoe")
    adapter_result = ModelAdapterResult(
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(
            ModelPrediction(
                prediction_id="pred-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.99,
                grounding=(_path(title_path),),
            ),
        ),
        latency_ms=3.0,
        memory_mb=12.0,
        cost_usd=0.001,
    )
    result = run_offline_adapter(
        case_id="case-1",
        page=page,
        adapter=_fake_adapter(adapter_id="fake-universal", result=adapter_result),
    )

    assert result.adapter_id == "fake-universal"
    assert result.public_records == ()
    assert result.predictions[0].grounding[0].locator == title_path


def test_offline_harness_rejects_adapter_identity_mismatch() -> None:
    page = build_compact_page_representation(
        html="<h1 class='title'>Trail Shoe</h1>", artifact_id="html"
    )
    result = ModelAdapterResult(
        adapter_id="different-adapter",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )
    adapter = _fake_adapter(adapter_id="expected-adapter", result=result)

    with pytest.raises(ValueError, match="identity"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_rejects_evaluation_truth_leakage() -> None:
    label = _human_field()
    page = build_compact_page_representation(
        html="<h1>Trail Shoe</h1>", artifact_id="html", labels=(label,)
    )
    adapter = _fake_adapter(
        adapter_id="must-not-run",
        predict=lambda page: pytest.fail("adapter must not receive evaluation truth"),
    )

    with pytest.raises(ValueError, match="cannot expose evaluation labels"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_rejects_grounding_outside_compact_source() -> None:
    page = build_compact_page_representation(
        html="<h1>Trail Shoe</h1>", artifact_id="html"
    )
    result = ModelAdapterResult(
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(
            ModelPrediction(
                prediction_id="pred-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(
                    GroundingReference(
                        kind="path",
                        artifact_id="other-artifact",
                        locator="/html[1]/body[1]/h1[1]",
                    ),
                ),
            ),
        ),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )
    adapter = _fake_adapter(adapter_id="fake-universal", result=result)

    with pytest.raises(ValueError, match="represented source artifact"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_result_rejects_publication_payload() -> None:
    with pytest.raises(ValidationError, match="cannot emit public records"):
        OfflineHarnessResult(
            case_id="case-1",
            adapter_id="fake-universal",
            model_family="deterministic-fixture",
            deployment_mode="offline_fixture",
            artifact_version="fixture-v1",
            representation_hash="abc123",
            predictions=(),
            latency_ms=1.0,
            memory_mb=1.0,
            cost_usd=0.0,
            public_records=({},),
        )
