from __future__ import annotations

from . import support as _support

for _name in dir(_support):
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = getattr(_support, _name)

__all__ = [
    _name
    for _name in globals()
    if not (_name.startswith("__") and _name.endswith("__"))
]
