from __future__ import annotations

import sys

from browser_surface_probe import core as _core

if __name__ != "__main__":
    sys.modules[__name__] = _core

for _name in dir(_core):
    if not (_name.startswith("__") and _name.endswith("__")):
        globals()[_name] = getattr(_core, _name)

__all__ = [
    _name
    for _name in globals()
    if not (_name.startswith("__") and _name.endswith("__"))
]

if __name__ == "__main__":
    raise SystemExit(_core.main())
