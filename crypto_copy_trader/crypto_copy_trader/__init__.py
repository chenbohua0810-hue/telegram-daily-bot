from __future__ import annotations

from pathlib import Path


_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parent

if str(_PROJECT_ROOT) not in __path__:
    __path__.append(str(_PROJECT_ROOT))
