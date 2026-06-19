from __future__ import annotations

from urllib.parse import urlsplit

from app.services.extraction.collectors._helpers import evidence
from app.services.extraction.contracts import CaptureBundle, EntityHint, Evidence, SourceLocator


class UrlCollector:
    collector_id = "url"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        path = urlsplit(bundle.final_url or bundle.requested_url).path
        title = path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
        if not title:
            return ()
        return (
            evidence(bundle, "url", "url", "product.url", bundle.final_url, SourceLocator(kind="url_component", value="url"), hint=EntityHint(entity_type="product", url=bundle.final_url), directness="inferred", confidence=0.55),
            evidence(bundle, "url", "url", "product.title", title, SourceLocator(kind="url_component", value="path"), hint=EntityHint(entity_type="product", url=bundle.final_url), directness="inferred", confidence=0.35),
        )
