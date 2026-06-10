from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from . import _common as _common_module
from . import _product_mapping as _product_mapping_module
from . import _variant_mapping as _variant_mapping_module
from app.services.config.js_state_field_specs import (
    JS_STATE_VARIANT_FIELD_SPEC as _VARIANT_FIELD_SPEC,
)
from ._common import (
    PRODUCT_FIELD_SPEC,
    glom,
    map_configured_state_payload,
)
from ._facade import *
from ._identity import *
from ._payloads import *
from ._product_mapping import *
from ._variant_mapping import *
from ._variant_rows import *

def _sync_compat_hooks() -> None:
    _product_mapping_module.glom = glom
    _variant_mapping_module.glom = glom


def _map_product_payload(*args, **kwargs):
    _sync_compat_hooks()
    return _product_mapping_module._map_product_payload(*args, **kwargs)


def _normalize_variant(*args, **kwargs):
    _sync_compat_hooks()
    return _variant_mapping_module._normalize_variant(*args, **kwargs)


__all__ = [
    "PRODUCT_FIELD_SPEC",
    "_VARIANT_FIELD_SPEC",
    "_map_product_payload",
    "_normalize_variant",
    "map_configured_state_payload",
    "map_js_state_to_fields",
]
