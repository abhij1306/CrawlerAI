from __future__ import annotations

from app.services.extraction.collectors.dom import DomCollector
from app.services.extraction.collectors.jsonld import JsonLdCollector
from app.services.extraction.collectors.js_state import JsStateCollector
from app.services.extraction.collectors.microdata import MicrodataCollector
from app.services.extraction.collectors.network import NetworkCollector
from app.services.extraction.collectors.opengraph import OpenGraphCollector
from app.services.extraction.collectors.url import UrlCollector


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
