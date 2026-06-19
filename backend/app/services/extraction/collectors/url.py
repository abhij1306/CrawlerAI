from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit

from app.services.config.extraction_rules._variants import VARIANT_URL_AXIS_PARAMS
from app.services.extraction.collectors._helpers import evidence
from app.services.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class UrlCollector:
    collector_id = "url"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        del artifacts
        parsed = urlsplit(bundle.final_url or bundle.requested_url)
        title = parsed.path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
        if not title:
            return ()
        product_hint = EntityHint(entity_type="product", url=bundle.final_url)
        product_url = evidence(
            bundle,
            "url",
            "url",
            "product.url",
            bundle.final_url,
            SourceLocator(kind="url_component", value="url"),
            hint=product_hint,
            directness="inferred",
            confidence=0.55,
        )
        rows = [
            product_url,
            evidence(
                bundle,
                "url",
                "url",
                "product.title",
                title,
                SourceLocator(kind="url_component", value="path"),
                hint=product_hint,
                directness="inferred",
                confidence=0.35,
                subject_id=product_url.subject_id,
            ),
        ]
        rows.extend(_selected_variant_from_query(bundle, parsed.query, product_url.subject_id))
        return tuple(rows)


def _selected_variant_from_query(
    bundle: CaptureBundle,
    query: str,
    product_subject_id: str,
) -> list[Evidence]:
    axes = {
        VARIANT_URL_AXIS_PARAMS[key.casefold()]: value
        for key, value in parse_qsl(query, keep_blank_values=False)
        if key.casefold() in VARIANT_URL_AXIS_PARAMS and value.strip()
    }
    if not axes:
        return []
    group = "variant:url:selected"
    hint = EntityHint(entity_type="variant", selected=True, option_values=axes)
    rows = [
        evidence(
            bundle,
            "url",
            "url",
            "variant.selected",
            True,
            SourceLocator(kind="url_component", value="query:selected_variant"),
            group_id=group,
            hint=hint,
            directness="inferred",
            confidence=0.5,
            parent_subject_id=product_subject_id,
        )
    ]
    for axis, value in sorted(axes.items()):
        rows.append(
            evidence(
                bundle,
                "url",
                "url",
                f"variant.option.{axis}",
                value,
                SourceLocator(kind="url_component", value=f"query:{axis}"),
                group_id=group,
                hint=hint,
                directness="inferred",
                confidence=0.5,
                parent_subject_id=product_subject_id,
            )
        )
    return rows
