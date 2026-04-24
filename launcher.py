from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


APP_URL = "http://127.0.0.1:7861"
HEALTH_URL = f"{APP_URL}/health"
SCRIPT_NAME = "启动Memlink Shrine UI.ps1"


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


ROOT = get_app_root()


def show_message(title: str, message: str) -> None:
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)


def is_running() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def find_openmemory_env() -> Path | None:
    for base in [ROOT, *ROOT.parents]:
        candidate = base / "__mem0_repo" / "openmemory" / "api" / ".env"
        if candidate.exists():
            return candidate
    return None


def load_google_key() -> str | None:
    env_path = find_openmemory_env()
    if not env_path:
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GOOGLE_API_KEY="):
            return line.split("=", 1)[1].strip()

    return None


def resolve_python_command() -> list[str] | None:
    python_cmd = shutil.which("python")
    if python_cmd:
        return [python_cmd]

    py_cmd = shutil.which("py")
    if py_cmd:
        return [py_cmd, "-3"]

    return None


def resolve_powershell_command() -> list[str] | None:
    for candidate in (
        shutil.which("pwsh"),
        shutil.which("powershell"),
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    ):
        if candidate and Path(candidate).exists():
            return [candidate]
    return None


def start_service_via_script() -> bool:
    script_path = ROOT / SCRIPT_NAME
    powershell_cmd = resolve_powershell_command()
    if not script_path.exists() or not powershell_cmd:
        return False

    command = powershell_cmd + [
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        "-NoBrowser",
    ]

    try:
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False

    for _ in range(18):
        time.sleep(0.5)
        if is_running():
            return True
    return False


def start_service() -> bool:
    if start_service_via_script():
        return True

    python_cmd = resolve_python_command()
    if not python_cmd:
        show_message("Memlink Shrine 启动器", "没有找到可用的 Python 运行环境，无法启动本地服务。")
        return False

    env = os.environ.copy()
    google_key = load_google_key()
    if google_key:
        env["GOOGLE_API_KEY"] = google_key

    env["MEMLINK_SHRINE_GEMINI_MODEL"] = "gemini-3-flash-preview"
    env["OPENMEMORY_BASE_URL"] = "http://localhost:8765"
    env["OPENMEMORY_USER_ID"] = "administrator-main"
    env["OPENMEMORY_APP_NAME"] = "codex"
    env["MEMLINK_SHRINE_DB"] = str(ROOT / "data" / "memlink_shrine.db")

    command = python_cmd + [
        "-m",
        "uvicorn",
        "memlink_shrine.web:app",
        "--host",
        "127.0.0.1",
        "--port",
        "7861",
    ]

    try:
        subprocess.Popen(
            command,
            cwd=str(ROOT),
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        show_message("Memlink Shrine 启动器", f"启动本地服务失败：{exc}")
        return False

    for _ in range(18):
        time.sleep(0.5)
        if is_running():
            return True

    show_message("Memlink Shrine 启动器", "服务启动超时，请稍后再试。")
    return False


def main() -> int:
    if not is_running():
        if not start_service():
            return 1

    webbrowser.open(APP_URL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




