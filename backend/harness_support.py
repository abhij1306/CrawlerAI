from __future__ import annotations

import sys

from harness import support as _support

if __name__ != "__main__":
    sys.modules[__name__] = _support

for _name in dir(_support):
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = getattr(_support, _name)

__all__ = [
    _name
    for _name in globals()
    if not (_name.startswith("__") and _name.endswith("__"))
]
