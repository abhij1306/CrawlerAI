from __future__ import annotations

from app.services.extraction_v2.collectors.js_state import network_row
from app.services.extraction_v2.contracts import CaptureBundle, Evidence


class NetworkCollector:
    collector_id = "network"
    collector_version = "1"

    def collect(self, bundle: CaptureBundle, artifacts) -> tuple[Evidence, ...]:
        out: list[Evidence] = []
        for ref in bundle.artifacts:
            if ref.artifact_type != "network_json":
                continue
            data = artifacts.read_json(ref)
            from app.services.extraction_v2.collectors._helpers import json_objects

            for path, obj in json_objects(data):
                if isinstance(obj, dict):
                    out.extend(network_row(bundle, ref.artifact_id, path, obj))
        return tuple(out)
