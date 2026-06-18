from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from typing import Any

from app.services.config import extraction_price_rules as _price_rules

from ._common import *
from ._common import _STATIC_EXPORTS
from ._images import *
from ._detail import *
from ._jobs import *
from ._detail_sections import *
from ._variants import *
from ._variant_options import *
from ._listing_structured import *
from ._extra_exports import _EXTRA_EXPORTS


def __getattr__(name: str) -> Any:
    if name in _price_rules.__all__:
        return getattr(_price_rules, name)
    try:
        return _STATIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc


__all__ = sorted(list(_STATIC_EXPORTS.keys()) + _EXTRA_EXPORTS)
