from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


APP_TITLE = "Memlink Shrine Quick Start"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def show_message(title: str, message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)


def target_executable() -> Path:
    root = app_root()
    return root / "MemlinkShrineQuickStartConsole" / "MemlinkShrineQuickStartConsole.exe"


def start_quick_start() -> bool:
    target = target_executable()
    if not target.exists():
        return False
    try:
        subprocess.Popen(
            [str(target)],
            cwd=str(target.parent),
            creationflags=CREATE_NO_WINDOW,
        )
        return True
    except OSError:
        return False


def main() -> int:
    if not start_quick_start():
        show_message(APP_TITLE, "没有找到独立运行包：MemlinkShrineQuickStartConsole。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
