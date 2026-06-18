from __future__ import annotations

from app.services.extraction_v2.collectors.dom import DomCollector
from app.services.extraction_v2.collectors.jsonld import JsonLdCollector
from app.services.extraction_v2.collectors.js_state import JsStateCollector
from app.services.extraction_v2.collectors.microdata import MicrodataCollector
from app.services.extraction_v2.collectors.network import NetworkCollector
from app.services.extraction_v2.collectors.opengraph import OpenGraphCollector
from app.services.extraction_v2.collectors.url import UrlCollector


def default_collectors():
    return (
        JsonLdCollector(),
        OpenGraphCollector(),
        MicrodataCollector(),
        JsStateCollector(),
        NetworkCollector(),
        DomCollector(),
        UrlCollector(),
    )
