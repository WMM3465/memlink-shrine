from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return Path(__file__).resolve().parents[1]


def runtime_root() -> Path:
    override = str(os.getenv("MEMLINK_SHRINE_RUNTIME_ROOT") or "").strip()
    if override:
        root = Path(override).resolve()
    elif getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
    else:
        root = Path(__file__).resolve().parents[1]
    root.mkdir(parents=True, exist_ok=True)
    return root


def runtime_data_root() -> Path:
    path = runtime_root() / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path
